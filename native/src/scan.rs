//! Per-scan scheduling, worker ownership, cancellation, and result delivery.

use crate::chunks::{deliver_chunk, CompletionWriter, OrderedChunkBuffer, WorkerCompletion};
use crate::filters::NativeFilterConfig;
use crate::pacing::NativeDelayPacer;
use crate::raw_client::{raw_http_request, should_use_raw_http, RawHttpRequest};
use crate::request_target::{prepare_request_target, prepare_request_targets};
use crate::result::{native_error_result, NativeHttpResult};
use crate::routing::ConnectionRoutes;
use crate::session::NativeHttpSession;
use crate::transport::{
    request_with_client, ClientRequest, HeaderPairs, OriginAuth, RandomUserAgentPool,
};
use crate::wordlist::NativeWordlistChunk;
use bytes::Bytes;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use reqwest::header::HeaderValue;
use reqwest::Method;
use std::borrow::Cow;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinSet;

const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(50);
const CHUNK_FLUSH_INTERVAL: Duration = Duration::from_millis(20);
const PROXY_AUTHENTICATION_REQUIRED: u16 = 407;

/// Immutable request state reused by every scan performed by one engine.
///
/// The engine builds this context once. Scan workers borrow it through an
/// `Arc`; mutable cookie and rate state lives behind the explicit session
/// handle so rebuilding an engine does not discard either one.
pub(crate) struct NativeRequestContext {
    pub(crate) clients: Arc<Vec<reqwest::Client>>,
    /// Connection-bound authentication owns one client per worker and proxy.
    pub(crate) clients_per_proxy: usize,
    pub(crate) raw_headers: Arc<HeaderPairs>,
    pub(crate) timeout_secs: f64,
    pub(crate) max_rate: usize,
    pub(crate) follow_redirects: bool,
    pub(crate) use_raw_http: bool,
    pub(crate) method: Method,
    pub(crate) body: Bytes,
    pub(crate) initial_cookie_override: Option<HeaderValue>,
    pub(crate) session: NativeHttpSession,
    pub(crate) origin_auth: OriginAuth,
    pub(crate) random_user_agents: Option<RandomUserAgentPool>,
    pub(crate) connection_routes: Arc<ConnectionRoutes>,
    pub(crate) network_interface: String,
    pub(crate) delay_pacer: NativeDelayPacer,
}

/// Path storage owned by one scan call.
///
/// A Python list is already materialized. A native wordlist chunk keeps its
/// shared corpus and range in Rust, constructing only paths claimed by workers.
pub(crate) enum ScanPaths {
    Materialized(Vec<String>),
    NativeWordlist(NativeWordlistChunk),
}

impl ScanPaths {
    fn prepare(&mut self, query: &str) {
        if let Self::Materialized(paths) = self {
            prepare_request_targets(paths, query);
        }
    }

    fn len(&self) -> usize {
        match self {
            Self::Materialized(paths) => paths.len(),
            Self::NativeWordlist(chunk) => chunk.len_native(),
        }
    }

    fn get(&self, index: usize, query: &str) -> Option<Cow<'_, str>> {
        match self {
            Self::Materialized(paths) => paths.get(index).map(|path| Cow::Borrowed(path.as_str())),
            Self::NativeWordlist(chunk) => chunk.path_at_owned(index).map(|mut path| {
                prepare_request_target(&mut path, query);
                Cow::Owned(path)
            }),
        }
    }
}

/// Values supplied for one scan, independent of the persistent engine state.
pub(crate) struct ScanJob {
    pub(crate) base_url: String,
    pub(crate) paths: ScanPaths,
    pub(crate) query: String,
    pub(crate) max_retries: usize,
    pub(crate) max_body_size: usize,
    pub(crate) filter_config: Arc<NativeFilterConfig>,
}

enum ResultDelivery {
    CollectAll,
    Chunks(CompletionWriter),
}

impl ResultDelivery {
    fn omits_filtered_results(&self) -> bool {
        matches!(self, Self::Chunks(_))
    }
}

/// State shared only by the bounded worker set of one scan.
struct ScanTask {
    paths: Arc<ScanPaths>,
    query: String,
    /// Atomic work distributor; completion order is tracked separately.
    next_request: AtomicUsize,
    base_url: String,
    request_context: Arc<NativeRequestContext>,
    filter_config: Arc<NativeFilterConfig>,
    cancelled: Arc<AtomicBool>,
    max_retries: usize,
    max_body_size: usize,
    delivery: ResultDelivery,
}

/// Collect every result for calibration and single-request backend calls.
pub(crate) async fn collect_results(
    mut job: ScanJob,
    concurrency: usize,
    request_context: Arc<NativeRequestContext>,
    cancelled: Arc<AtomicBool>,
) -> PyResult<Vec<NativeHttpResult>> {
    job.paths.prepare(&job.query);
    let result_count = job.paths.len();
    let paths = Arc::new(job.paths);
    let scan_task = Arc::new(ScanTask {
        paths: paths.clone(),
        query: String::new(),
        next_request: AtomicUsize::new(0),
        base_url: job.base_url,
        request_context,
        filter_config: job.filter_config,
        cancelled: cancelled.clone(),
        max_retries: job.max_retries,
        max_body_size: job.max_body_size,
        delivery: ResultDelivery::CollectAll,
    });
    let mut tasks = spawn_workers(scan_task, concurrency.min(result_count));
    let mut results = Vec::with_capacity(result_count);
    let mut signal_poll = signal_poll_interval();

    while !tasks.is_empty() {
        let mut check_signals = false;
        tokio::select! {
            joined = tasks.join_next() => {
                match joined {
                    Some(Ok(worker_results)) => results.extend(worker_results),
                    Some(Err(error)) => {
                        abort_and_drain(&mut tasks).await;
                        return Err(PyRuntimeError::new_err(error.to_string()));
                    }
                    None => break,
                }
            }
            _ = signal_poll.tick() => check_signals = true,
        }

        if cancelled.load(Ordering::Acquire) {
            abort_and_drain(&mut tasks).await;
            return Ok(Vec::new());
        }
        if check_signals {
            if let Err(error) = Python::attach(|py| py.check_signals()) {
                abort_and_drain(&mut tasks).await;
                return Err(error);
            }
            if cancelled.load(Ordering::Acquire) {
                abort_and_drain(&mut tasks).await;
                return Ok(Vec::new());
            }
        }
    }

    if cancelled.load(Ordering::Acquire) {
        return Ok(Vec::new());
    }

    results.sort_by_key(|(request_index, _)| *request_index);
    for (request_index, result) in &mut results {
        result.path = paths
            .get(*request_index, "")
            .expect("result index must refer to a prepared path")
            .into_owned();
    }
    Ok(results.into_iter().map(|(_, result)| result).collect())
}

/// Deliver ordered result chunks while workers are still scanning.
pub(crate) async fn deliver_result_chunks(
    mut job: ScanJob,
    concurrency: usize,
    request_context: Arc<NativeRequestContext>,
    cancelled: Arc<AtomicBool>,
    callback: Py<PyAny>,
    chunk_size: usize,
) -> PyResult<usize> {
    job.paths.prepare(&job.query);
    let result_count = job.paths.len();
    if result_count == 0 {
        return Ok(0);
    }

    let paths = Arc::new(job.paths);
    let mut chunks = OrderedChunkBuffer::new(result_count);
    let scan_task = Arc::new(ScanTask {
        paths,
        query: job.query,
        next_request: AtomicUsize::new(0),
        base_url: job.base_url,
        request_context,
        filter_config: job.filter_config,
        cancelled: cancelled.clone(),
        max_retries: job.max_retries,
        max_body_size: job.max_body_size,
        delivery: ResultDelivery::Chunks(chunks.writer()),
    });
    let mut tasks = spawn_workers(scan_task, concurrency.min(result_count));
    let mut flush_tick = tokio::time::interval_at(
        tokio::time::Instant::now() + CHUNK_FLUSH_INTERVAL,
        CHUNK_FLUSH_INTERVAL,
    );
    flush_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut signal_poll = signal_poll_interval();

    while !tasks.is_empty() {
        let mut force_flush = false;
        let mut check_signals = false;
        tokio::select! {
            joined = tasks.join_next() => {
                if let Some(Err(error)) = joined {
                    abort_and_drain(&mut tasks).await;
                    return Err(PyRuntimeError::new_err(error.to_string()));
                }
            }
            _ = flush_tick.tick() => force_flush = true,
            _ = signal_poll.tick() => check_signals = true,
        }

        if cancelled.load(Ordering::Acquire) {
            abort_and_drain(&mut tasks).await;
            return Ok(chunks.delivered_count());
        }
        if check_signals {
            if let Err(error) = Python::attach(|py| py.check_signals()) {
                abort_and_drain(&mut tasks).await;
                return Err(error);
            }
        }
        while let Some(chunk) = chunks.take_ready(chunk_size, force_flush) {
            if let Err(error) = deliver_chunk(&callback, chunk) {
                abort_and_drain(&mut tasks).await;
                return Err(error);
            }
        }
    }

    if cancelled.load(Ordering::Acquire) {
        return Ok(chunks.delivered_count());
    }
    while let Some(chunk) = chunks.take_ready(chunk_size, true) {
        deliver_chunk(&callback, chunk)?;
    }
    let delivered_count = chunks.delivered_count();
    if delivered_count != result_count {
        return Err(PyRuntimeError::new_err(format!(
            "native chunk delivery stopped after {delivered_count} of {result_count} paths",
        )));
    }
    Ok(delivered_count)
}

fn spawn_workers(
    scan_task: Arc<ScanTask>,
    worker_count: usize,
) -> JoinSet<Vec<(usize, NativeHttpResult)>> {
    let mut tasks = JoinSet::new();
    for worker_index in 0..worker_count {
        tasks.spawn(run_scan_worker(scan_task.clone(), worker_index));
    }
    tasks
}

fn signal_poll_interval() -> tokio::time::Interval {
    let mut interval = tokio::time::interval_at(
        tokio::time::Instant::now() + SIGNAL_POLL_INTERVAL,
        SIGNAL_POLL_INTERVAL,
    );
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    interval
}

/// Stop accepting completions and wait until every owned worker is reaped.
async fn abort_and_drain<T: 'static>(tasks: &mut JoinSet<T>) {
    tasks.abort_all();
    while tasks.join_next().await.is_some() {}
}

async fn run_scan_worker(
    task: Arc<ScanTask>,
    worker_index: usize,
) -> Vec<(usize, NativeHttpResult)> {
    let mut results = Vec::new();
    loop {
        if task.cancelled.load(Ordering::Acquire) {
            break;
        }
        let request_index = task.next_request.fetch_add(1, Ordering::Relaxed);
        let Some(path_value) = task.paths.get(request_index, &task.query) else {
            break;
        };
        let path = path_value.as_ref();
        let request_context = task.request_context.as_ref();
        request_context.delay_pacer.wait(worker_index).await;
        request_context
            .session
            .rate_limiter
            .wait(request_context.max_rate)
            .await;
        if task.cancelled.load(Ordering::Acquire) {
            break;
        }

        let client = if request_context.clients_per_proxy == 1 {
            &request_context.clients[request_index % request_context.clients.len()]
        } else {
            let proxy_count = request_context.clients.len() / request_context.clients_per_proxy;
            let proxy_index = request_index % proxy_count;
            &request_context.clients[proxy_index * request_context.clients_per_proxy + worker_index]
        };
        let url = format!("{}{path}", task.base_url);
        let start = Instant::now();
        let use_raw_path = request_context.use_raw_http
            && !request_context.follow_redirects
            && should_use_raw_http(&task.base_url, path);
        let mut result = if use_raw_path && request_context.origin_auth.requires_challenge() {
            native_error_result(
                String::new(),
                start.elapsed().as_secs_f64() * 1000.0,
                format!(
                    "Native {} authentication cannot be used with a byte-preserving raw HTTP target",
                    request_context.origin_auth.challenge_name()
                ),
            )
        } else if use_raw_path {
            raw_http_request(
                RawHttpRequest {
                    base_url: &task.base_url,
                    path,
                    method: request_context.method.as_str(),
                    body: request_context.body.as_ref(),
                    headers: &request_context.raw_headers,
                    random_user_agents: request_context.random_user_agents.as_ref(),
                    timeout_secs: request_context.timeout_secs,
                    max_body_size: task.max_body_size,
                    start,
                    cancelled: task.cancelled.clone(),
                    cookie_store: request_context.session.cookie_store.clone(),
                    connection_routes: request_context.connection_routes.as_ref(),
                    network_interface: &request_context.network_interface,
                },
                task.max_retries,
                task.filter_config.as_ref(),
            )
            .await
        } else {
            request_with_client(ClientRequest {
                client,
                url: &url,
                method: &request_context.method,
                body: &request_context.body,
                initial_cookie_override: request_context.initial_cookie_override.clone(),
                capture_redirect_history: request_context.follow_redirects,
                max_retries: task.max_retries,
                max_body_size: task.max_body_size,
                start,
                filter_config: task.filter_config.as_ref(),
                skip_status_filtered_body: task.delivery.omits_filtered_results(),
                origin_auth: &request_context.origin_auth,
                random_user_agents: request_context.random_user_agents.as_ref(),
            })
            .await
        };
        request_context.delay_pacer.mark_completed(worker_index);
        if result.final_url.is_empty() {
            result.final_url = url;
        }
        result.request_index = request_index;

        let omit_result = task.delivery.omits_filtered_results()
            && result.filtered
            && result.error.is_none()
            && result.status != PROXY_AUTHENTICATION_REQUIRED;
        match &task.delivery {
            ResultDelivery::CollectAll => results.push((request_index, result)),
            ResultDelivery::Chunks(writer) => {
                if !omit_result {
                    result.path = path_value.into_owned();
                }
                writer.push(WorkerCompletion {
                    request_index,
                    result: (!omit_result).then_some(result),
                });
            }
        }
    }
    results
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    struct CountDrop(Arc<AtomicUsize>);

    impl Drop for CountDrop {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[tokio::test]
    async fn abort_and_drain_reaps_every_started_worker() {
        let started = Arc::new(AtomicUsize::new(0));
        let dropped = Arc::new(AtomicUsize::new(0));
        let mut tasks = JoinSet::new();
        for _ in 0..2 {
            let started = started.clone();
            let dropped = dropped.clone();
            tasks.spawn(async move {
                let _drop_guard = CountDrop(dropped);
                started.fetch_add(1, Ordering::SeqCst);
                std::future::pending::<()>().await;
            });
        }
        while started.load(Ordering::SeqCst) != 2 {
            tokio::task::yield_now().await;
        }

        abort_and_drain(&mut tasks).await;

        assert!(tasks.is_empty());
        assert_eq!(dropped.load(Ordering::SeqCst), 2);
    }
}
