//! PyO3 engine construction, persistent resources, and public scan methods.

use crate::chunks::DEFAULT_RESULT_CHUNK_SIZE;
use crate::filters::NativeFilterConfig;
use crate::pacing::NativeDelayPacer;
use crate::result::NativeHttpResult;
use crate::routing::{ConnectionOverrideConfig, ConnectionRoutes};
use crate::scan::{
    collect_results, deliver_result_chunks, NativeRequestContext, ScanJob, ScanPaths,
};
use crate::session::NativeHttpSession;
use crate::transport::{build_http_client, HeaderPairs, OriginAuth, RandomUserAgentPool};
use crate::wordlist::NativeWordlistChunk;
use bytes::Bytes;
use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, COOKIE};
use reqwest::Method;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

const RANDOM_USER_AGENT_CONFLICT_ERROR: &str =
    "Random User-Agent values cannot be combined with a fixed User-Agent header";

#[pyclass]
pub(crate) struct NativeHttpEngine {
    runtime: tokio::runtime::Runtime,
    concurrency: usize,
    request_context: Arc<NativeRequestContext>,
    cancelled: Arc<AtomicBool>,
}

struct NativeHttpEngineConfig {
    concurrency: usize,
    timeout_secs: f64,
    max_rate: usize,
    delay_secs: f64,
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
    random_user_agents: Vec<String>,
    connection_overrides: ConnectionOverrideConfig,
    network_interface: String,
}

#[pymethods]
impl NativeHttpEngine {
    #[new]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        concurrency=25,
        timeout_secs=7.5,
        max_rate=0,
        delay_secs=0.0,
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
        random_user_agents=Vec::new(),
        connection_overrides=Vec::new(),
        network_interface="".to_string(),
        session=None,
    ))]
    fn new(
        concurrency: usize,
        timeout_secs: f64,
        max_rate: usize,
        delay_secs: f64,
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
        random_user_agents: Vec<String>,
        connection_overrides: ConnectionOverrideConfig,
        network_interface: String,
        session: Option<PyRef<'_, NativeHttpSession>>,
    ) -> PyResult<Self> {
        Self::from_config(
            NativeHttpEngineConfig {
                concurrency,
                timeout_secs,
                max_rate,
                delay_secs,
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
                random_user_agents,
                connection_overrides,
                network_interface,
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

    fn rate(&self) -> usize {
        self.request_context.session.rate_limiter.rate()
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        base_url,
        paths,
        query="".to_string(),
        max_retries=0,
        max_body_size=83886080,
        filter_config=None,
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
    ) -> PyResult<Vec<NativeHttpResult>> {
        let filter_config = filter_config
            .map(|config| config.borrow(py).clone())
            .unwrap_or_default();
        self.collect_scan(
            py,
            ScanJob {
                base_url,
                paths: ScanPaths::Materialized(paths),
                query,
                max_retries,
                max_body_size,
                filter_config: Arc::new(filter_config),
            },
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        base_url,
        paths,
        callback,
        query="".to_string(),
        max_retries=0,
        max_body_size=83886080,
        filter_config=None,
        chunk_size=DEFAULT_RESULT_CHUNK_SIZE,
    ))]
    fn scan_chunks(
        &self,
        py: Python<'_>,
        base_url: String,
        paths: Vec<String>,
        callback: Py<PyAny>,
        query: String,
        max_retries: usize,
        max_body_size: usize,
        filter_config: Option<Py<NativeFilterConfig>>,
        chunk_size: usize,
    ) -> PyResult<usize> {
        validate_chunk_callback(py, &callback)?;
        let filter_config = filter_config
            .map(|config| config.borrow(py).clone())
            .unwrap_or_default();
        self.deliver_chunks(
            py,
            ScanJob {
                base_url,
                paths: ScanPaths::Materialized(paths),
                query,
                max_retries,
                max_body_size,
                filter_config: Arc::new(filter_config),
            },
            callback,
            chunk_size,
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        base_url,
        chunk,
        callback,
        query="".to_string(),
        max_retries=0,
        max_body_size=83886080,
        filter_config=None,
        chunk_size=DEFAULT_RESULT_CHUNK_SIZE,
    ))]
    fn scan_owned_chunks(
        &self,
        py: Python<'_>,
        base_url: String,
        chunk: PyRef<'_, NativeWordlistChunk>,
        callback: Py<PyAny>,
        query: String,
        max_retries: usize,
        max_body_size: usize,
        filter_config: Option<Py<NativeFilterConfig>>,
        chunk_size: usize,
    ) -> PyResult<usize> {
        validate_chunk_callback(py, &callback)?;
        let owned_chunk = (*chunk).clone();
        let filter_config = filter_config
            .map(|config| config.borrow(py).clone())
            .unwrap_or_default();
        self.deliver_chunks(
            py,
            ScanJob {
                base_url,
                paths: ScanPaths::NativeWordlist(owned_chunk),
                query,
                max_retries,
                max_body_size,
                filter_config: Arc::new(filter_config),
            },
            callback,
            chunk_size,
        )
    }
}

fn validate_chunk_callback(py: Python<'_>, callback: &Py<PyAny>) -> PyResult<()> {
    if callback.bind(py).is_callable() {
        Ok(())
    } else {
        Err(PyTypeError::new_err(
            "native chunk callback must be callable",
        ))
    }
}

impl NativeHttpEngine {
    fn from_config(
        mut config: NativeHttpEngineConfig,
        session: NativeHttpSession,
    ) -> PyResult<Self> {
        if !config.delay_secs.is_finite() || config.delay_secs < 0.0 {
            return Err(PyRuntimeError::new_err(
                "Native request delay must be a finite, non-negative number",
            ));
        }
        if !config.proxies.is_empty() && !config.connection_overrides.is_empty() {
            return Err(PyRuntimeError::new_err(
                "Native --ip overrides cannot be combined with a proxy because the proxy controls origin resolution",
            ));
        }
        let method = Method::from_bytes(config.method.as_bytes())
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        if !config.random_user_agents.is_empty()
            && config
                .headers
                .iter()
                .any(|(name, _)| name.eq_ignore_ascii_case("user-agent"))
        {
            return Err(PyRuntimeError::new_err(RANDOM_USER_AGENT_CONFLICT_ERROR));
        }
        let random_user_agents =
            RandomUserAgentPool::from_values(config.random_user_agents.clone())
                .map_err(PyRuntimeError::new_err)?;
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
        let connection_routes = Arc::new(
            ConnectionRoutes::from_config(&config.connection_overrides)
                .map_err(PyRuntimeError::new_err)?,
        );
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
                connection_routes.as_ref(),
                &config.network_interface,
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
                        connection_routes.as_ref(),
                        &config.network_interface,
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
                max_rate: config.max_rate,
                follow_redirects: config.follow_redirects,
                use_raw_http,
                method,
                body: Bytes::from(config.body),
                initial_cookie_override,
                session,
                origin_auth,
                random_user_agents,
                connection_routes,
                network_interface: config.network_interface,
                delay_pacer: NativeDelayPacer::new(config.concurrency, config.delay_secs),
            }),
            cancelled: Arc::new(AtomicBool::new(false)),
        })
    }

    fn collect_scan(&self, py: Python<'_>, job: ScanJob) -> PyResult<Vec<NativeHttpResult>> {
        // Pause may race ahead of the worker's first scan call.
        if self.cancelled.swap(false, Ordering::AcqRel) {
            return Ok(Vec::new());
        }
        let result = py.detach(|| {
            self.runtime.block_on(collect_results(
                job,
                self.concurrency,
                self.request_context.clone(),
                self.cancelled.clone(),
            ))
        });
        self.cancelled.store(false, Ordering::Release);
        result
    }

    fn deliver_chunks(
        &self,
        py: Python<'_>,
        job: ScanJob,
        callback: Py<PyAny>,
        chunk_size: usize,
    ) -> PyResult<usize> {
        if chunk_size == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "native chunk size must be greater than zero",
            ));
        }
        // Pause may race ahead of the worker's first scan call.
        if self.cancelled.swap(false, Ordering::AcqRel) {
            return Ok(0);
        }
        let result = py.detach(|| {
            self.runtime.block_on(deliver_result_chunks(
                job,
                self.concurrency,
                self.request_context.clone(),
                self.cancelled.clone(),
                callback,
                chunk_size,
            ))
        });
        self.cancelled.store(false, Ordering::Release);
        result
    }
}

pub(crate) fn runtime_worker_count() -> usize {
    std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .clamp(1, 256)
}
