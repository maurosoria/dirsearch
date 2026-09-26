//! PyO3 engine lifecycle, bounded request scheduling, and cancellation.

use crate::filters::{NativeFilterConfig, NumericRange, TimeFilter};
use crate::raw_client::{raw_http_request, should_use_raw_http, RawHttpRequest};
use crate::request_target::prepare_request_targets;
use crate::result::{native_completion_marker, native_error_result, NativeHttpResult};
use crate::session::NativeHttpSession;
use crate::transport::{
    build_http_client, request_with_client, ClientRequest, HeaderPairs, OriginAuth,
};
use crate::wordlist::NativeWordlistBatch;
use bytes::Bytes;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, COOKIE};
use reqwest::Method;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tokio::task::JoinSet;

const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(50);
const PROXY_AUTHENTICATION_REQUIRED: u16 = 407;

#[pyclass]
pub(crate) struct NativeHttpEngine {
    runtime: tokio::runtime::Runtime,
    concurrency: usize,
    request_context: Arc<NativeRequestContext>,
    cancelled: Arc<AtomicBool>,
}

/// Engine-lifetime state reused by every scan batch.
///
/// Values in this context determine how a request is built or transported, so
/// changing one requires rebuilding the engine and its clients. The context is
/// otherwise immutable and cheap to share between workers. `session` is a
/// stable handle whose cookie jar intentionally uses interior mutability so
/// cookies can survive engine rebuilds and be shared with replay transports.
struct NativeRequestContext {
    // Prepared transport resources. There is one client per proxy (or one
    // direct client), while raw_headers serves the byte-preserving HTTP path.
    clients: Arc<Vec<reqwest::Client>>,
    raw_headers: Arc<HeaderPairs>,
    timeout_secs: f64,
    follow_redirects: bool,
    use_raw_http: bool,
    method: Method,
    body: Bytes,
    initial_cookie_override: Option<HeaderValue>,
    session: NativeHttpSession,
    origin_auth: OriginAuth,
}

#[derive(Clone, PartialEq)]
struct NativeHttpEngineConfig {
    concurrency: usize,
    timeout_secs: f64,
    headers: HeaderPairs,
    proxies: Vec<String>,
    follow_redirects: bool,
    max_redirects: usize,
    method: String,
    body: Vec<u8>,
    client_certificate: Vec<u8>,
    client_key: Vec<u8>,
    auth_type: String,
    auth_credential: String,
}

struct CachedNativeHttpEngine {
    config: NativeHttpEngineConfig,
    engine: Arc<NativeHttpEngine>,
}

type NativeHttpEngineCache = Option<CachedNativeHttpEngine>;
static DEFAULT_HTTP_ENGINE: OnceLock<Mutex<NativeHttpEngineCache>> = OnceLock::new();

#[pymethods]
impl NativeHttpEngine {
    #[new]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        concurrency=25,
        timeout_secs=7.5,
        headers=Vec::new(),
        proxies=Vec::new(),
        follow_redirects=false,
        max_redirects=30,
        method="GET".to_string(),
        body=Vec::new(),
        client_certificate=Vec::new(),
        client_key=Vec::new(),
        auth_type="".to_string(),
        auth_credential="".to_string(),
        session=None,
    ))]
    fn new(
        concurrency: usize,
        timeout_secs: f64,
        headers: HeaderPairs,
        proxies: Vec<String>,
        follow_redirects: bool,
        max_redirects: usize,
        method: String,
        body: Vec<u8>,
        client_certificate: Vec<u8>,
        client_key: Vec<u8>,
        auth_type: String,
        auth_credential: String,
        session: Option<PyRef<'_, NativeHttpSession>>,
    ) -> PyResult<Self> {
        Self::from_config(
            NativeHttpEngineConfig {
                concurrency,
                timeout_secs,
                headers,
                proxies,
                follow_redirects,
                max_redirects,
                method,
                body,
                client_certificate,
                client_key,
                auth_type,
                auth_credential,
            },
            session.as_deref().cloned().unwrap_or_default(),
        )
    }

    fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    fn reset_cancel(&self) {
        self.cancelled.store(false, Ordering::Release);
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        base_url,
        paths,
        query="".to_string(),
        max_retries=0,
        max_body_size=83886080,
        filter_config=None,
        compact_filtered=false,
    ))]
    fn scan(
        &self,
        py: Python<'_>,
        base_url: String,
        paths: Vec<String>,
        query: String,
        max_retries: usize,
        max_body_size: usize,
        filter_config: Option<Py<NativeFilterConfig>>,
        compact_filtered: bool,
    ) -> PyResult<Vec<NativeHttpResult>> {
        let filter_config = filter_config
            .map(|config| config.borrow(py).clone())
            .unwrap_or_default();
        self.scan_paths(
            py,
            base_url,
            paths,
            query,
            max_retries,
            max_body_size,
            Arc::new(filter_config),
            compact_filtered,
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        base_url,
        batch,
        query="".to_string(),
        max_retries=0,
        max_body_size=83886080,
        filter_config=None,
        compact_filtered=false,
    ))]
    fn scan_owned_batch(
        &self,
        py: Python<'_>,
        base_url: String,
        batch: PyRef<'_, NativeWordlistBatch>,
        query: String,
        max_retries: usize,
        max_body_size: usize,
        filter_config: Option<Py<NativeFilterConfig>>,
        compact_filtered: bool,
    ) -> PyResult<Vec<NativeHttpResult>> {
        let owned_batch = (*batch).clone();
        let paths = py.detach(move || owned_batch.to_paths());
        let filter_config = filter_config
            .map(|config| config.borrow(py).clone())
            .unwrap_or_default();
        self.scan_paths(
            py,
            base_url,
            paths,
            query,
            max_retries,
            max_body_size,
            Arc::new(filter_config),
            compact_filtered,
        )
    }
}

impl NativeHttpEngine {
    fn from_config(
        mut config: NativeHttpEngineConfig,
        session: NativeHttpSession,
    ) -> PyResult<Self> {
        let method = Method::from_bytes(config.method.as_bytes())
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        let origin_auth = OriginAuth::from_config(&config.auth_type, &config.auth_credential)
            .map_err(PyRuntimeError::new_err)?;
        if !matches!(&origin_auth, OriginAuth::None) {
            config
                .headers
                .retain(|(name, _)| !name.eq_ignore_ascii_case("authorization"));
        }
        let mut raw_headers = config.headers.clone();
        if let Some(authorization) = origin_auth.preemptive_authorization() {
            raw_headers.push(("authorization".to_string(), authorization));
        }
        let mut header_map = HeaderMap::new();
        let mut initial_cookie_override = None;
        for (name, value) in &config.headers {
            let name = HeaderName::from_bytes(name.as_bytes())
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
            let value = HeaderValue::from_str(value)
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
            if name == COOKIE {
                initial_cookie_override = Some(value);
            } else {
                header_map.insert(name, value);
            }
        }

        let use_raw_http = config.proxies.is_empty();
        let client_identity =
            (!config.client_certificate.is_empty() || !config.client_key.is_empty()).then_some((
                config.client_certificate.as_slice(),
                config.client_key.as_slice(),
            ));
        let clients = if config.proxies.is_empty() {
            vec![build_http_client(
                &header_map,
                config.concurrency,
                config.timeout_secs,
                config.follow_redirects,
                config.max_redirects,
                None,
                client_identity,
                session.cookie_store.clone(),
            )
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?]
        } else {
            config
                .proxies
                .iter()
                .map(|proxy_url| {
                    build_http_client(
                        &header_map,
                        config.concurrency,
                        config.timeout_secs,
                        config.follow_redirects,
                        config.max_redirects,
                        Some(proxy_url),
                        client_identity,
                        session.cookie_store.clone(),
                    )
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?
        };
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(runtime_worker_count())
            .build()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        Ok(Self {
            runtime,
            concurrency: config.concurrency.max(1),
            request_context: Arc::new(NativeRequestContext {
                clients: Arc::new(clients),
                raw_headers: Arc::new(raw_headers),
                timeout_secs: config.timeout_secs,
                follow_redirects: config.follow_redirects,
                use_raw_http,
                method,
                body: Bytes::from(config.body),
                initial_cookie_override,
                session,
                origin_auth,
            }),
            cancelled: Arc::new(AtomicBool::new(false)),
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn scan_paths(
        &self,
        py: Python<'_>,
        base_url: String,
        mut paths: Vec<String>,
        query: String,
        max_retries: usize,
        max_body_size: usize,
        filter_config: Arc<NativeFilterConfig>,
        compact_filtered: bool,
    ) -> PyResult<Vec<NativeHttpResult>> {
        // Pause may race ahead of the worker's first scan call.
        if self.cancelled.swap(false, Ordering::AcqRel) {
            return Ok(Vec::new());
        }
        let cancelled = self.cancelled.clone();
        let concurrency = self.concurrency;
        let request_context = self.request_context.clone();
        let runtime = &self.runtime;

        let result = py.detach(move || {
            runtime.block_on(async move {
                prepare_request_targets(&mut paths, &query);
                let result_count = paths.len();
                let paths = Arc::new(paths);
                let scan_task = Arc::new(ScanTask {
                    paths: paths.clone(),
                    next_request: AtomicUsize::new(0),
                    base_url,
                    request_context,
                    filter_config,
                    cancelled: cancelled.clone(),
                    max_retries,
                    max_body_size,
                    compact_filtered,
                });
                // Reuse a bounded set of worker tasks for the whole batch.
                // This keeps HTTP concurrency unchanged while avoiding one
                // Tokio task allocation and context clone per URL.
                let mut tasks: JoinSet<WorkerScanResults> = JoinSet::new();
                let worker_count = concurrency.min(result_count);
                for _ in 0..worker_count {
                    tasks.spawn(run_scan_worker(scan_task.clone()));
                }

                let mut results = Vec::with_capacity(if compact_filtered {
                    worker_count
                } else {
                    result_count
                });
                let mut last_processed_index = None;
                // Checking Python signals requires attaching this worker to
                // the interpreter. Poll instead of doing that per response.
                let mut signal_poll = tokio::time::interval_at(
                    tokio::time::Instant::now() + SIGNAL_POLL_INTERVAL,
                    SIGNAL_POLL_INTERVAL,
                );
                signal_poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
                while !tasks.is_empty() {
                    let mut check_signals = false;
                    tokio::select! {
                        joined = tasks.join_next() => {
                            match joined {
                                Some(Ok(worker_results)) => {
                                    results.extend(worker_results.events);
                                    last_processed_index = last_processed_index.max(
                                        worker_results.last_processed_index,
                                    );
                                }
                                Some(Err(error)) => {
                                    return Err(PyRuntimeError::new_err(error.to_string()));
                                }
                                None => break,
                            }
                        }
                        _ = signal_poll.tick() => check_signals = true,
                    }

                    if cancelled.load(Ordering::Acquire) {
                        tasks.abort_all();
                        return Ok(Vec::new());
                    }
                    if check_signals {
                        Python::attach(|py| py.check_signals())?;
                        if cancelled.load(Ordering::Acquire) {
                            tasks.abort_all();
                            return Ok(Vec::new());
                        }
                    }
                }

                if cancelled.load(Ordering::Acquire) {
                    return Ok(Vec::new());
                }

                results.sort_by_key(|(request_index, _)| *request_index);
                if compact_filtered {
                    // Gaps represent filtered misses. Add one marker only when
                    // the final processed path is not already actionable.
                    if let Some(last_index) = last_processed_index {
                        if results.last().map(|(index, _)| *index) != Some(last_index) {
                            results.push((last_index, native_completion_marker(last_index)));
                        }
                    }
                }

                // Request workers only carry indexes. Clone encoded targets
                // after compaction so filtered misses never allocate a result path.
                for (request_index, result) in &mut results {
                    result.path.clone_from(&paths[*request_index]);
                }
                Ok(results.into_iter().map(|(_, result)| result).collect())
            })
        });
        self.cancelled.store(false, Ordering::Release);
        result
    }
}

struct WorkerScanResults {
    events: Vec<(usize, NativeHttpResult)>,
    last_processed_index: Option<usize>,
}

/// Per-batch state shared by the bounded worker set.
///
/// Unlike `NativeRequestContext`, these values belong to one `scan` call and
/// must not leak into later batches. Workers only mutate `next_request` to
/// claim unique paths; results remain worker-local and are ordered by the
/// coordinator after all workers join.
struct ScanTask {
    paths: Arc<Vec<String>>,
    /// Atomic work distributor; it does not define result ordering.
    next_request: AtomicUsize,
    base_url: String,
    request_context: Arc<NativeRequestContext>,
    filter_config: Arc<NativeFilterConfig>,
    /// Shared with the engine so Python can cooperatively stop this batch.
    cancelled: Arc<AtomicBool>,
    max_retries: usize,
    max_body_size: usize,
    compact_filtered: bool,
}

async fn run_scan_worker(task: Arc<ScanTask>) -> WorkerScanResults {
    let mut results = Vec::new();
    let mut last_processed_index = None;
    loop {
        if task.cancelled.load(Ordering::Acquire) {
            break;
        }
        // Workers only need a unique index here; results are ordered after
        // every worker finishes, so this counter does not synchronize data.
        let request_index = task.next_request.fetch_add(1, Ordering::Relaxed);
        let Some(path) = task.paths.get(request_index) else {
            break;
        };
        last_processed_index = Some(request_index);
        let request_context = task.request_context.as_ref();
        let client = &request_context.clients[request_index % request_context.clients.len()];
        let url = format!("{}{path}", task.base_url);
        let start = Instant::now();

        let use_raw_path = request_context.use_raw_http
            && !request_context.follow_redirects
            && should_use_raw_http(&task.base_url, path);
        let mut result = if use_raw_path && request_context.origin_auth.requires_challenge() {
            native_error_result(
                String::new(),
                start.elapsed().as_secs_f64() * 1000.0,
                "Native Digest authentication cannot be used with a byte-preserving raw HTTP target"
                    .to_string(),
            )
        } else if use_raw_path {
            raw_http_request(
                RawHttpRequest {
                    base_url: &task.base_url,
                    path,
                    method: request_context.method.as_str(),
                    body: request_context.body.as_ref(),
                    headers: &request_context.raw_headers,
                    timeout_secs: request_context.timeout_secs,
                    max_body_size: task.max_body_size,
                    start,
                    cancelled: task.cancelled.clone(),
                    cookie_store: request_context.session.cookie_store.clone(),
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
                compact_filtered: task.compact_filtered,
                origin_auth: &request_context.origin_auth,
            })
            .await
        };
        if result.final_url.is_empty() {
            result.final_url = url;
        }
        result.request_index = request_index;
        // Filtered results only carry progress in compact mode. The coordinator
        // synthesizes one completion marker after every worker has joined.
        if task.compact_filtered
            && result.filtered
            && result.error.is_none()
            && result.status != PROXY_AUTHENTICATION_REQUIRED
        {
            continue;
        } else {
            results.push((request_index, result));
        }
    }
    WorkerScanResults {
        events: results,
        last_processed_index,
    }
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (
    base_url,
    paths,
    query="".to_string(),
    concurrency=25,
    timeout_secs=7.5,
    headers=Vec::new(),
    proxies=Vec::new(),
    max_retries=0,
    follow_redirects=false,
    max_body_size=83886080,
    include_status_codes=Vec::new(),
    exclude_status_codes=Vec::new(),
    minimum_response_size=0,
    maximum_response_size=0,
    matcher_mode="or".to_string(),
    filter_mode="or".to_string(),
    match_status_codes=Vec::new(),
    filter_status_codes=Vec::new(),
    match_sizes=Vec::new(),
    filter_sizes=Vec::new(),
    match_words=Vec::new(),
    filter_words=Vec::new(),
    match_lines=Vec::new(),
    filter_lines=Vec::new(),
    match_regex=None,
    filter_regex=None,
    match_headers=Vec::new(),
    filter_headers=Vec::new(),
    match_header_regex=None,
    filter_header_regex=None,
    match_time=Vec::new(),
    filter_time=Vec::new(),
    max_redirects=30,
    method="GET".to_string(),
    body=Vec::new(),
    client_certificate=Vec::new(),
    client_key=Vec::new(),
    auth_type="".to_string(),
    auth_credential="".to_string(),
))]
pub(crate) fn scan_http(
    py: Python<'_>,
    base_url: String,
    paths: Vec<String>,
    query: String,
    concurrency: usize,
    timeout_secs: f64,
    headers: HeaderPairs,
    proxies: Vec<String>,
    max_retries: usize,
    follow_redirects: bool,
    max_body_size: usize,
    include_status_codes: Vec<u16>,
    exclude_status_codes: Vec<u16>,
    minimum_response_size: usize,
    maximum_response_size: usize,
    matcher_mode: String,
    filter_mode: String,
    match_status_codes: Vec<u16>,
    filter_status_codes: Vec<u16>,
    match_sizes: Vec<NumericRange>,
    filter_sizes: Vec<NumericRange>,
    match_words: Vec<NumericRange>,
    filter_words: Vec<NumericRange>,
    match_lines: Vec<NumericRange>,
    filter_lines: Vec<NumericRange>,
    match_regex: Option<String>,
    filter_regex: Option<String>,
    match_headers: Vec<String>,
    filter_headers: Vec<String>,
    match_header_regex: Option<String>,
    filter_header_regex: Option<String>,
    match_time: Vec<TimeFilter>,
    filter_time: Vec<TimeFilter>,
    max_redirects: usize,
    method: String,
    body: Vec<u8>,
    client_certificate: Vec<u8>,
    client_key: Vec<u8>,
    auth_type: String,
    auth_credential: String,
) -> PyResult<Vec<NativeHttpResult>> {
    let config = NativeHttpEngineConfig {
        concurrency,
        timeout_secs,
        headers,
        proxies,
        follow_redirects,
        max_redirects,
        method,
        body,
        client_certificate,
        client_key,
        auth_type,
        auth_credential,
    };
    let engine = {
        let cache = DEFAULT_HTTP_ENGINE.get_or_init(|| Mutex::new(None));
        let mut cached = cache
            .lock()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        if cached.as_ref().is_none_or(|cached| cached.config != config) {
            let session = cached
                .as_ref()
                .map_or_else(NativeHttpSession::default, |cached| {
                    cached.engine.request_context.session.clone()
                });
            let engine = Arc::new(NativeHttpEngine::from_config(config.clone(), session)?);
            *cached = Some(CachedNativeHttpEngine { config, engine });
        }
        cached.as_ref().unwrap().engine.clone()
    };

    let filter_config = NativeFilterConfig::from_options(
        include_status_codes,
        exclude_status_codes,
        minimum_response_size,
        maximum_response_size,
        matcher_mode,
        filter_mode,
        match_status_codes,
        filter_status_codes,
        match_sizes,
        filter_sizes,
        match_words,
        filter_words,
        match_lines,
        filter_lines,
        match_regex,
        filter_regex,
        match_headers,
        filter_headers,
        match_header_regex,
        filter_header_regex,
        match_time,
        filter_time,
    )
    .map_err(PyRuntimeError::new_err)?;

    engine.scan_paths(
        py,
        base_url,
        paths,
        query,
        max_retries,
        max_body_size,
        Arc::new(filter_config),
        false,
    )
}

pub(crate) fn runtime_worker_count() -> usize {
    std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .clamp(1, 256)
}
