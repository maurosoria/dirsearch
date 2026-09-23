//! PyO3 engine lifecycle, bounded request scheduling, and cancellation.

use crate::filters::{NativeFilterConfig, NumericRange, TimeFilter};
use crate::raw_client::{raw_http_get, should_use_raw_http, RawHttpRequest};
use crate::request_target::prepare_request_targets;
use crate::result::{native_completion_marker, NativeHttpResult};
use crate::transport::{build_http_client, request_with_client, HeaderPairs};
use crate::wordlist::NativeWordlistBatch;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tokio::task::JoinSet;

const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(50);
const PROXY_AUTHENTICATION_REQUIRED: u16 = 407;

#[pyclass]
pub(crate) struct NativeHttpEngine {
    runtime: tokio::runtime::Runtime,
    clients: Vec<reqwest::Client>,
    raw_headers: HeaderPairs,
    concurrency: usize,
    timeout_secs: f64,
    follow_redirects: bool,
    use_raw_http: bool,
    cancelled: Arc<AtomicBool>,
}

#[derive(Clone, Eq, PartialEq)]
struct NativeHttpEngineConfig {
    concurrency: usize,
    timeout_bits: u64,
    headers: HeaderPairs,
    proxies: Vec<String>,
    follow_redirects: bool,
}

type CachedNativeHttpEngine = Option<(NativeHttpEngineConfig, Arc<NativeHttpEngine>)>;
static DEFAULT_HTTP_ENGINE: OnceLock<Mutex<CachedNativeHttpEngine>> = OnceLock::new();

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
    ))]
    fn new(
        concurrency: usize,
        timeout_secs: f64,
        headers: HeaderPairs,
        proxies: Vec<String>,
        follow_redirects: bool,
    ) -> PyResult<Self> {
        let mut header_map = HeaderMap::new();
        for (name, value) in &headers {
            let name = HeaderName::from_bytes(name.as_bytes())
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
            let value = HeaderValue::from_str(value)
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
            header_map.insert(name, value);
        }

        let use_raw_http = proxies.is_empty();
        let clients = if proxies.is_empty() {
            vec![build_http_client(
                &header_map,
                concurrency,
                timeout_secs,
                follow_redirects,
                None,
            )
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?]
        } else {
            proxies
                .iter()
                .map(|proxy_url| {
                    build_http_client(
                        &header_map,
                        concurrency,
                        timeout_secs,
                        follow_redirects,
                        Some(proxy_url),
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
            clients,
            raw_headers: headers,
            concurrency: concurrency.max(1),
            timeout_secs,
            follow_redirects,
            use_raw_http,
            cancelled: Arc::new(AtomicBool::new(false)),
        })
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
        let paths = py.allow_threads(move || owned_batch.to_paths());
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
        let clients = self.clients.clone();
        let raw_headers = self.raw_headers.clone();
        let concurrency = self.concurrency;
        let timeout_secs = self.timeout_secs;
        let follow_redirects = self.follow_redirects;
        let use_raw_http = self.use_raw_http;
        let runtime = &self.runtime;

        let result = py.allow_threads(move || {
            runtime.block_on(async move {
                prepare_request_targets(&mut paths, &query);
                let result_count = paths.len();
                let paths = Arc::new(paths);
                let next_request = Arc::new(AtomicUsize::new(0));
                // Reuse a bounded set of worker tasks for the whole batch.
                // This keeps HTTP concurrency unchanged while avoiding one
                // Tokio task allocation and context clone per URL.
                let mut tasks: JoinSet<WorkerScanResults> = JoinSet::new();
                let worker_count = concurrency.min(result_count);
                for _ in 0..worker_count {
                    let paths = paths.clone();
                    let next_request = next_request.clone();
                    let clients = clients.clone();
                    let base_url = base_url.clone();
                    let raw_headers = raw_headers.clone();
                    let filter_config = filter_config.clone();
                    let worker_cancelled = cancelled.clone();
                    tasks.spawn(run_scan_worker(
                        paths,
                        next_request,
                        clients,
                        base_url,
                        raw_headers,
                        filter_config,
                        worker_cancelled,
                        use_raw_http,
                        follow_redirects,
                        timeout_secs,
                        max_retries,
                        max_body_size,
                        compact_filtered,
                    ));
                }

                let mut results = Vec::with_capacity(if compact_filtered {
                    worker_count
                } else {
                    result_count
                });
                let mut last_processed_index = None;
                // Checking Python signals requires the GIL. Poll on a timer
                // instead of reacquiring it for every completed request.
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
                        Python::with_gil(|py| py.check_signals())?;
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

#[allow(clippy::too_many_arguments)]
async fn run_scan_worker(
    paths: Arc<Vec<String>>,
    next_request: Arc<AtomicUsize>,
    clients: Vec<reqwest::Client>,
    base_url: String,
    raw_headers: HeaderPairs,
    filter_config: Arc<NativeFilterConfig>,
    cancelled: Arc<AtomicBool>,
    use_raw_http: bool,
    follow_redirects: bool,
    timeout_secs: f64,
    max_retries: usize,
    max_body_size: usize,
    compact_filtered: bool,
) -> WorkerScanResults {
    let mut results = Vec::new();
    let mut last_processed_index = None;
    loop {
        if cancelled.load(Ordering::Acquire) {
            break;
        }
        // Workers only need a unique index here; results are ordered after
        // every worker finishes, so this counter does not synchronize data.
        let request_index = next_request.fetch_add(1, Ordering::Relaxed);
        let Some(path) = paths.get(request_index) else {
            break;
        };
        last_processed_index = Some(request_index);
        let client = &clients[request_index % clients.len()];
        let url = format!("{base_url}{path}");
        let start = Instant::now();

        let mut result =
            if use_raw_http && !follow_redirects && should_use_raw_http(&base_url, path) {
                raw_http_get(
                    RawHttpRequest {
                        base_url: &base_url,
                        path,
                        headers: &raw_headers,
                        timeout_secs,
                        max_body_size,
                        start,
                        cancelled: cancelled.clone(),
                    },
                    filter_config.as_ref(),
                )
                .await
            } else {
                request_with_client(
                    client,
                    url,
                    follow_redirects,
                    max_retries,
                    max_body_size,
                    start,
                    filter_config.as_ref(),
                    compact_filtered,
                )
                .await
            };
        result.request_index = request_index;
        // Filtered results only carry progress in compact mode. The coordinator
        // synthesizes one completion marker after every worker has joined.
        if compact_filtered
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
) -> PyResult<Vec<NativeHttpResult>> {
    let config = NativeHttpEngineConfig {
        concurrency,
        timeout_bits: timeout_secs.to_bits(),
        headers: headers.clone(),
        proxies: proxies.clone(),
        follow_redirects,
    };
    let engine = {
        let cache = DEFAULT_HTTP_ENGINE.get_or_init(|| Mutex::new(None));
        let mut cached = cache
            .lock()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        if cached
            .as_ref()
            .is_none_or(|(cached_config, _)| *cached_config != config)
        {
            *cached = Some((
                config,
                Arc::new(NativeHttpEngine::new(
                    concurrency,
                    timeout_secs,
                    headers,
                    proxies,
                    follow_redirects,
                )?),
            ));
        }
        cached.as_ref().unwrap().1.clone()
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
