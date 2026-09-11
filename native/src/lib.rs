mod raw_http;

use async_compression::tokio::bufread::{BrotliDecoder, GzipDecoder, ZlibDecoder};
use futures_util::TryStreamExt;
use indexmap::IndexSet;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rayon::prelude::*;
use regex::{Regex, RegexBuilder};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use std::fs;
use std::io;
#[cfg(test)]
use std::io::Cursor;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, BufReader};
use tokio::task::JoinSet;
use tokio_util::io::StreamReader;

const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(50);

#[pyclass]
struct NativeHttpResult {
    #[pyo3(get)]
    path: String,
    #[pyo3(get)]
    status: u16,
    #[pyo3(get)]
    length: usize,
    #[pyo3(get)]
    elapsed_ms: f64,
    #[pyo3(get)]
    error: Option<String>,
    #[pyo3(get)]
    filtered: bool,
    #[pyo3(get)]
    filter_reason: Option<String>,
    #[pyo3(get)]
    headers: Vec<(String, String)>,
    #[pyo3(get)]
    body: Vec<u8>,
}

#[pyclass]
struct NativeHttpEngine {
    runtime: tokio::runtime::Runtime,
    clients: Vec<reqwest::Client>,
    raw_headers: HeaderPairs,
    concurrency: usize,
    timeout_secs: f64,
    follow_redirects: bool,
    use_raw_http: bool,
    cancelled: Arc<AtomicBool>,
}

type NumericRange = (usize, usize);
type TimeFilter = (String, f64);
type HeaderPairs = Vec<(String, String)>;
type RawHttpResponse = raw_http::Response;
type AsyncBodyReader = Pin<Box<dyn AsyncRead + Send>>;

struct RawHttpRequest<'a> {
    base_url: &'a str,
    path: String,
    headers: &'a HeaderPairs,
    timeout_secs: f64,
    max_body_size: usize,
    start: Instant,
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

#[derive(Clone)]
struct NativeFilterConfig {
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
    match_regex: Option<Regex>,
    filter_regex: Option<Regex>,
    match_headers: Vec<String>,
    filter_headers: Vec<String>,
    match_header_regex: Option<Regex>,
    filter_header_regex: Option<Regex>,
    match_time: Vec<TimeFilter>,
    filter_time: Vec<TimeFilter>,
}

impl NativeFilterConfig {
    #[allow(clippy::too_many_arguments)]
    fn new(
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
    ) -> Result<Self, String> {
        Ok(Self {
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
            match_regex: compile_regex(match_regex, "--match-regex")?,
            filter_regex: compile_regex(filter_regex, "--filter-regex")?,
            match_headers,
            filter_headers,
            match_header_regex: compile_header_regex(match_header_regex, "--match-header-regex")?,
            filter_header_regex: compile_header_regex(
                filter_header_regex,
                "--filter-header-regex",
            )?,
            match_time,
            filter_time,
        })
    }

    fn filter_reason(
        &self,
        status: u16,
        length: usize,
        headers: &[(String, String)],
        body: &[u8],
        elapsed_ms: f64,
    ) -> Option<&'static str> {
        if self.exclude_status_codes.contains(&status) {
            return Some("exclude_status");
        }

        if !self.include_status_codes.is_empty() && !self.include_status_codes.contains(&status) {
            return Some("include_status");
        }

        if length < self.minimum_response_size {
            return Some("minimum_response_size");
        }

        if self.maximum_response_size > 0 && length > self.maximum_response_size {
            return Some("maximum_response_size");
        }

        let text = self
            .needs_text()
            .then(|| String::from_utf8_lossy(body).into_owned());
        let text = text.as_deref();
        let headers_text = self.needs_headers().then(|| headers_to_text(headers));
        let headers_text = headers_text.as_deref();

        if !self.matches_advanced_matchers(status, length, text, headers_text, elapsed_ms) {
            return Some("advanced_matcher");
        }

        if self.matches_advanced_filters(status, length, text, headers_text, elapsed_ms) {
            return Some("advanced_filter");
        }

        None
    }

    fn needs_text(&self) -> bool {
        !self.match_words.is_empty()
            || !self.filter_words.is_empty()
            || !self.match_lines.is_empty()
            || !self.filter_lines.is_empty()
            || self.match_regex.is_some()
            || self.filter_regex.is_some()
    }

    fn needs_headers(&self) -> bool {
        !self.match_headers.is_empty()
            || !self.filter_headers.is_empty()
            || self.match_header_regex.is_some()
            || self.filter_header_regex.is_some()
    }

    fn matches_advanced_matchers(
        &self,
        status: u16,
        length: usize,
        text: Option<&str>,
        headers_text: Option<&str>,
        elapsed_ms: f64,
    ) -> bool {
        let mut checks = Vec::new();

        if !self.match_status_codes.is_empty() {
            checks.push(self.match_status_codes.contains(&status));
        }
        if !self.match_sizes.is_empty() {
            checks.push(matches_numeric_ranges(length, &self.match_sizes));
        }
        if !self.match_words.is_empty() {
            checks.push(matches_numeric_ranges(word_count(text), &self.match_words));
        }
        if !self.match_lines.is_empty() {
            checks.push(matches_numeric_ranges(line_count(text), &self.match_lines));
        }
        if let Some(regex) = &self.match_regex {
            checks.push(regex.is_match(text.unwrap_or_default()));
        }
        if !self.match_headers.is_empty() {
            checks.push(matches_header_text(headers_text, &self.match_headers));
        }
        if let Some(regex) = &self.match_header_regex {
            checks.push(regex.is_match(headers_text.unwrap_or_default()));
        }
        if !self.match_time.is_empty() {
            checks.push(matches_time_filters(elapsed_ms, &self.match_time));
        }

        combine_advanced_checks(&checks, &self.matcher_mode, true)
    }

    fn matches_advanced_filters(
        &self,
        status: u16,
        length: usize,
        text: Option<&str>,
        headers_text: Option<&str>,
        elapsed_ms: f64,
    ) -> bool {
        let mut checks = Vec::new();

        if !self.filter_status_codes.is_empty() {
            checks.push(self.filter_status_codes.contains(&status));
        }
        if !self.filter_sizes.is_empty() {
            checks.push(matches_numeric_ranges(length, &self.filter_sizes));
        }
        if !self.filter_words.is_empty() {
            checks.push(matches_numeric_ranges(word_count(text), &self.filter_words));
        }
        if !self.filter_lines.is_empty() {
            checks.push(matches_numeric_ranges(line_count(text), &self.filter_lines));
        }
        if let Some(regex) = &self.filter_regex {
            checks.push(regex.is_match(text.unwrap_or_default()));
        }
        if !self.filter_headers.is_empty() {
            checks.push(matches_header_text(headers_text, &self.filter_headers));
        }
        if let Some(regex) = &self.filter_header_regex {
            checks.push(regex.is_match(headers_text.unwrap_or_default()));
        }
        if !self.filter_time.is_empty() {
            checks.push(matches_time_filters(elapsed_ms, &self.filter_time));
        }

        combine_advanced_checks(&checks, &self.filter_mode, false)
    }
}

fn compile_regex(pattern: Option<String>, label: &str) -> Result<Option<Regex>, String> {
    match pattern {
        Some(pattern) => Regex::new(&pattern).map(Some).map_err(|error| {
            format!("Invalid {label} regular expression for native backend: {error}")
        }),
        None => Ok(None),
    }
}

fn compile_header_regex(pattern: Option<String>, label: &str) -> Result<Option<Regex>, String> {
    match pattern {
        Some(pattern) => RegexBuilder::new(&pattern)
            .case_insensitive(true)
            .build()
            .map(Some)
            .map_err(|error| {
                format!("Invalid {label} regular expression for native backend: {error}")
            }),
        None => Ok(None),
    }
}

fn matches_numeric_ranges(value: usize, ranges: &[NumericRange]) -> bool {
    ranges
        .iter()
        .any(|(minimum, maximum)| *minimum <= value && value <= *maximum)
}

fn matches_time_filters(elapsed_ms: f64, filters: &[TimeFilter]) -> bool {
    filters.iter().any(|(operator, value)| {
        (operator == ">" && elapsed_ms > *value)
            || (operator == "<" && elapsed_ms < *value)
            || (operator == "=" && elapsed_ms == *value)
    })
}

fn headers_to_text(headers: &[(String, String)]) -> String {
    headers
        .iter()
        .map(|(name, value)| format!("{name}: {value}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn matches_header_text(headers_text: Option<&str>, patterns: &[String]) -> bool {
    let headers_text = headers_text.unwrap_or_default().to_lowercase();
    patterns
        .iter()
        .any(|pattern| headers_text.contains(&pattern.to_lowercase()))
}

fn combine_advanced_checks(checks: &[bool], mode: &str, default: bool) -> bool {
    if checks.is_empty() {
        return default;
    }

    if mode == "and" {
        return checks.iter().all(|check| *check);
    }

    checks.iter().any(|check| *check)
}

fn word_count(text: Option<&str>) -> usize {
    text.unwrap_or_default().split_whitespace().count()
}

fn line_count(text: Option<&str>) -> usize {
    let text = text.unwrap_or_default();
    if text.is_empty() {
        return 0;
    }

    text.matches('\n').count() + 1
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (
    files,
    extensions,
    force_extensions=false,
    prefixes=Vec::new(),
    suffixes=Vec::new(),
    exclude_extensions=Vec::new(),
    overwrite_exclude_extensions=Vec::new(),
    lowercase=false,
    uppercase=false,
    capitalization=false,
    overwrite_extensions=false,
    max_size=None,
))]
fn generate_wordlist(
    files: Vec<String>,
    extensions: Vec<String>,
    force_extensions: bool,
    prefixes: Vec<String>,
    suffixes: Vec<String>,
    exclude_extensions: Vec<String>,
    overwrite_exclude_extensions: Vec<String>,
    lowercase: bool,
    uppercase: bool,
    capitalization: bool,
    overwrite_extensions: bool,
    max_size: Option<usize>,
) -> PyResult<Vec<String>> {
    let file_lines: Vec<Vec<String>> = files
        .par_iter()
        .map(|path| read_lines(path))
        .collect::<Result<Vec<_>, _>>()?;

    let mut wordlist = IndexSet::new();
    for lines in file_lines {
        for raw_line in lines {
            let line = lstrip_once(&raw_line, "/");
            for expanded in expand_ext(&line, &extensions) {
                if !is_valid(&expanded, &exclude_extensions) {
                    continue;
                }

                add_entry(&mut wordlist, expanded.clone(), max_size)?;

                if force_extensions && !expanded.contains('.') && !expanded.ends_with('/') {
                    add_entry(&mut wordlist, format!("{expanded}/"), max_size)?;
                    for extension in &extensions {
                        add_entry(&mut wordlist, format!("{expanded}.{extension}"), max_size)?;
                    }
                } else if overwrite_extensions
                    && should_overwrite_extension(
                        &expanded,
                        &extensions,
                        &overwrite_exclude_extensions,
                    )
                {
                    let base = expanded.split('.').next().unwrap_or_default();
                    for extension in &extensions {
                        add_entry(&mut wordlist, format!("{base}.{extension}"), max_size)?;
                    }
                }
            }
        }
    }

    if !prefixes.is_empty() || !suffixes.is_empty() {
        let mut altered = IndexSet::new();
        for path in &wordlist {
            for prefix in &prefixes {
                if !path.starts_with('/') && !path.starts_with(prefix) {
                    add_entry(&mut altered, format!("{prefix}{path}"), max_size)?;
                }
            }
            for suffix in &suffixes {
                if !path.ends_with('/')
                    && !path.ends_with(suffix)
                    && !path.contains('?')
                    && !path.contains('#')
                {
                    add_entry(&mut altered, format!("{path}{suffix}"), max_size)?;
                }
            }
        }
        if !altered.is_empty() {
            wordlist = altered;
        }
    }

    let items = wordlist
        .into_iter()
        .map(|path| apply_case(path, lowercase, uppercase, capitalization))
        .collect();
    Ok(items)
}

fn lstrip_once(input: &str, pattern: &str) -> String {
    input.strip_prefix(pattern).unwrap_or(input).to_string()
}

fn build_http_client(
    headers: &HeaderMap,
    concurrency: usize,
    timeout_secs: f64,
    follow_redirects: bool,
    proxy_url: Option<&str>,
) -> Result<reqwest::Client, reqwest::Error> {
    let mut builder = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .default_headers(headers.clone())
        .redirect(if follow_redirects {
            reqwest::redirect::Policy::limited(10)
        } else {
            reqwest::redirect::Policy::none()
        })
        .timeout(Duration::from_secs_f64(timeout_secs))
        .pool_max_idle_per_host(concurrency);

    if let Some(proxy_url) = proxy_url {
        builder = builder.proxy(reqwest::Proxy::all(proxy_url)?);
    }

    builder.build()
}

#[pymethods]
impl NativeHttpEngine {
    #[new]
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
        max_retries=0,
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
    fn scan(
        &self,
        py: Python<'_>,
        base_url: String,
        paths: Vec<String>,
        max_retries: usize,
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
        let filter_config = Arc::new(
            NativeFilterConfig::new(
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
            .map_err(PyRuntimeError::new_err)?,
        );

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
                let semaphore = Arc::new(tokio::sync::Semaphore::new(concurrency));
                let result_count = paths.len();
                let mut tasks = JoinSet::new();

                for (request_index, path) in paths.into_iter().enumerate() {
                    let client = clients[request_index % clients.len()].clone();
                    let base_url = base_url.clone();
                    let raw_headers = raw_headers.clone();
                    let semaphore = semaphore.clone();
                    let filter_config = filter_config.clone();
                    let request_cancelled = cancelled.clone();
                    tasks.spawn(async move {
                        let _permit = match semaphore.acquire_owned().await {
                            Ok(permit) => permit,
                            Err(error) => {
                                return (
                                    request_index,
                                    native_error_result(path, 0.0, error.to_string()),
                                );
                            }
                        };
                        let url = format!("{base_url}{path}");
                        let start = Instant::now();

                        let result = if use_raw_http
                            && !follow_redirects
                            && should_use_raw_http(&base_url, &path)
                        {
                            let raw_base_url = base_url.clone();
                            let raw_path = path.clone();
                            let raw_filter_config = filter_config.clone();
                            raw_http_get(
                                RawHttpRequest {
                                    base_url: &raw_base_url,
                                    path: raw_path,
                                    headers: &raw_headers,
                                    timeout_secs,
                                    max_body_size,
                                    start,
                                    cancelled: request_cancelled,
                                },
                                raw_filter_config.as_ref(),
                            )
                            .await
                        } else {
                            request_with_client(
                                &client,
                                url,
                                path,
                                max_retries,
                                max_body_size,
                                start,
                                filter_config.as_ref(),
                            )
                            .await
                        };
                        (request_index, result)
                    });
                }

                let mut results = Vec::with_capacity(result_count);
                while !tasks.is_empty() {
                    tokio::select! {
                        joined = tasks.join_next() => {
                            match joined {
                                Some(Ok(result)) => results.push(result),
                                Some(Err(error)) => {
                                    return Err(PyRuntimeError::new_err(error.to_string()));
                                }
                                None => break,
                            }
                        }
                        _ = tokio::time::sleep(SIGNAL_POLL_INTERVAL) => {}
                    }

                    if cancelled.load(Ordering::Acquire) {
                        tasks.abort_all();
                        return Ok(Vec::new());
                    }
                    Python::with_gil(|py| py.check_signals())?;
                    if cancelled.load(Ordering::Acquire) {
                        tasks.abort_all();
                        return Ok(Vec::new());
                    }
                }

                results.sort_by_key(|(request_index, _)| *request_index);
                Ok(results.into_iter().map(|(_, result)| result).collect())
            })
        });
        self.cancelled.store(false, Ordering::Release);
        result
    }
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (
    base_url,
    paths,
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
fn scan_http(
    py: Python<'_>,
    base_url: String,
    paths: Vec<String>,
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

    engine.scan(
        py,
        base_url,
        paths,
        max_retries,
        max_body_size,
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
}

async fn request_with_client(
    client: &reqwest::Client,
    url: String,
    path: String,
    max_retries: usize,
    max_body_size: usize,
    start: Instant,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    let mut response = None;
    let mut last_error = None;
    for _ in 0..=max_retries {
        match client.get(&url).send().await {
            Ok(value) => {
                response = Some(value);
                last_error = None;
                break;
            }
            Err(error) => {
                let error = format_error_chain(&error);
                let retryable = !error.contains("tunnel error: unsuccessful");
                last_error = Some(error);
                if !retryable {
                    break;
                }
            }
        }
    }
    let response = match response {
        Some(response) => response,
        None => {
            return native_error_result(
                path,
                start.elapsed().as_secs_f64() * 1000.0,
                last_error.unwrap_or_else(|| "request failed".to_string()),
            );
        }
    };
    let status = response.status().as_u16();
    let headers = response
        .headers()
        .iter()
        .map(|(name, value)| {
            (
                name.as_str().to_string(),
                value.to_str().unwrap_or_default().to_string(),
            )
        })
        .collect::<Vec<_>>();
    let (body, body_length) = match read_response_body(response, &headers, max_body_size).await {
        Ok(result) => result,
        Err(error) => {
            return native_error_result(
                path,
                start.elapsed().as_secs_f64() * 1000.0,
                error.to_string(),
            );
        }
    };
    native_http_result_with_length(
        path,
        status,
        headers,
        body,
        body_length,
        start.elapsed().as_secs_f64() * 1000.0,
        filter_config,
    )
}

fn format_error_chain(error: &dyn std::error::Error) -> String {
    let mut message = error.to_string();
    let mut source = error.source();
    while let Some(error) = source {
        message.push_str(": ");
        message.push_str(&error.to_string());
        source = error.source();
    }
    message
}

#[cfg(test)]
fn native_http_result(
    path: String,
    status: u16,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    elapsed_ms: f64,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    let body_length = body.len();
    native_http_result_with_length(
        path,
        status,
        headers,
        body,
        body_length,
        elapsed_ms,
        filter_config,
    )
}

fn native_http_result_with_length(
    path: String,
    status: u16,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    body_length: usize,
    elapsed_ms: f64,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    let length = response_length(&headers, body_length);
    let filter_reason = filter_config
        .filter_reason(status, length, &headers, &body, elapsed_ms)
        .map(str::to_string);
    let filtered = filter_reason.is_some();

    NativeHttpResult {
        path,
        status,
        length,
        elapsed_ms,
        error: None,
        filtered,
        filter_reason,
        headers,
        body: if filtered { Vec::new() } else { body },
    }
}

fn native_error_result(path: String, elapsed_ms: f64, error: String) -> NativeHttpResult {
    NativeHttpResult {
        path,
        status: 0,
        length: 0,
        elapsed_ms,
        error: Some(error),
        filtered: false,
        filter_reason: None,
        headers: Vec::new(),
        body: Vec::new(),
    }
}

fn runtime_worker_count() -> usize {
    std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .clamp(1, 256)
}

async fn read_response_body(
    response: reqwest::Response,
    headers: &HeaderPairs,
    max_body_size: usize,
) -> Result<(Vec<u8>, usize), String> {
    let capacity = response
        .content_length()
        .and_then(|length| usize::try_from(length).ok())
        .unwrap_or_default()
        .min(max_body_size);
    let encodings = raw_http::comma_separated_header_values(headers, "content-encoding");
    let stream = response.bytes_stream().map_err(io::Error::other);
    let mut reader: AsyncBodyReader = Box::pin(StreamReader::new(stream));
    for encoding in encodings.iter().rev() {
        if encoding.eq_ignore_ascii_case("identity") {
            continue;
        }

        let buffered = BufReader::new(reader);
        reader = if encoding.eq_ignore_ascii_case("gzip") {
            Box::pin(GzipDecoder::new(buffered))
        } else if encoding.eq_ignore_ascii_case("deflate") {
            Box::pin(ZlibDecoder::new(buffered))
        } else if encoding.eq_ignore_ascii_case("br") {
            Box::pin(BrotliDecoder::new(buffered))
        } else {
            return Err(format!("Unsupported HTTP Content-Encoding: {encoding}"));
        };
    }
    let mut body = Vec::with_capacity(capacity);
    let mut body_length = 0usize;
    let mut buffer = [0u8; 8192];

    loop {
        let read = reader.read(&mut buffer).await.map_err(|error| {
            if encodings.is_empty() {
                error.to_string()
            } else {
                format!(
                    "Failed to decode {} response body: {error}",
                    encodings.join(", ")
                )
            }
        })?;
        if read == 0 {
            break;
        }
        body_length = body_length.saturating_add(read);
        append_body_chunk(&mut body, &buffer[..read], max_body_size);
    }

    Ok((body, body_length))
}

fn append_body_chunk(body: &mut Vec<u8>, chunk: &[u8], max_body_size: usize) {
    let remaining = max_body_size.saturating_sub(body.len());
    body.extend_from_slice(&chunk[..chunk.len().min(remaining)]);
}

fn response_length(headers: &[(String, String)], body_length: usize) -> usize {
    headers
        .iter()
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        .and_then(|(_, value)| value.parse::<usize>().ok())
        .unwrap_or(body_length)
}

fn should_use_raw_http(base_url: &str, path: &str) -> bool {
    base_url.starts_with("http://")
        && (has_dot_segment(path) || path.contains('\\') || has_malformed_percent_escape(path))
}

fn has_dot_segment(path: &str) -> bool {
    path.split(['/', '?', '#'])
        .any(|segment| segment == "." || segment == "..")
}

fn has_malformed_percent_escape(path: &str) -> bool {
    let bytes = path.as_bytes();
    let mut index = 0;

    while index < bytes.len() {
        if bytes[index] == b'%' {
            if index + 2 >= bytes.len()
                || !bytes[index + 1].is_ascii_hexdigit()
                || !bytes[index + 2].is_ascii_hexdigit()
            {
                return true;
            }
            index += 3;
        } else {
            index += 1;
        }
    }

    false
}

async fn raw_http_get(
    request: RawHttpRequest<'_>,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    match raw_http_get_inner(&request).await {
        Ok((status, headers, body, length)) => native_http_result_with_length(
            request.path,
            status,
            headers,
            body,
            length,
            request.start.elapsed().as_secs_f64() * 1000.0,
            filter_config,
        ),
        Err(error) => native_error_result(
            request.path,
            request.start.elapsed().as_secs_f64() * 1000.0,
            error,
        ),
    }
}

async fn raw_http_get_inner(request: &RawHttpRequest<'_>) -> Result<RawHttpResponse, String> {
    let url = reqwest::Url::parse(request.base_url).map_err(|error| error.to_string())?;
    if url.scheme() != "http" {
        return Err("Raw HTTP path preservation only supports http:// URLs".to_string());
    }

    let host = url
        .host_str()
        .ok_or_else(|| "URL is missing a host".to_string())?
        .to_string();
    let port = url
        .port_or_known_default()
        .ok_or_else(|| "URL is missing a port".to_string())?;
    let host_header = match url.port() {
        Some(port) => format!("{host}:{port}"),
        None => host.clone(),
    };
    let target = raw_request_target(url.path(), &request.path);
    let mut wire_request =
        format!("GET {target} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n");
    for (name, value) in request.headers {
        wire_request.push_str(name);
        wire_request.push_str(": ");
        wire_request.push_str(value);
        wire_request.push_str("\r\n");
    }
    wire_request.push_str("\r\n");

    let timeout = Duration::from_secs_f64(request.timeout_secs);
    let deadline = request
        .start
        .checked_add(timeout)
        .ok_or_else(|| "Raw HTTP timeout exceeded the supported duration".to_string())?;
    let stream = tokio::time::timeout_at(
        tokio::time::Instant::from_std(deadline),
        tokio::net::TcpStream::connect((host.as_str(), port)),
    )
    .await
    .map_err(|_| "Raw HTTP connection timed out".to_string())?
    .map_err(|error| error.to_string())?;
    let stream = stream.into_std().map_err(|error| error.to_string())?;
    stream
        .set_nonblocking(false)
        .map_err(|error| error.to_string())?;
    let shutdown_stream = stream.try_clone().map_err(|error| error.to_string())?;
    let mut shutdown_guard = raw_http::ShutdownOnDrop::new(shutdown_stream);
    let cancelled = request.cancelled.clone();
    let max_body_size = request.max_body_size;
    let exchange = tokio::task::spawn_blocking(move || {
        raw_http::exchange(
            stream,
            wire_request.as_bytes(),
            deadline,
            cancelled,
            max_body_size,
        )
    })
    .await
    .map_err(|error| error.to_string())?;
    shutdown_guard.disarm();
    exchange
}

fn raw_request_target(base_path: &str, path: &str) -> String {
    let mut target = if base_path == "/" {
        "/".to_string()
    } else {
        base_path.trim_end_matches('/').to_string() + "/"
    };
    target.push_str(path.trim_start_matches('/'));
    target
}

#[cfg(test)]
fn parse_raw_http_response(
    raw_response: Vec<u8>,
    max_body_size: usize,
) -> Result<RawHttpResponse, String> {
    raw_http::parse_response(Cursor::new(raw_response), max_body_size)
}

fn read_lines(path: &str) -> PyResult<Vec<String>> {
    let content = fs::read(path).map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    let content = String::from_utf8_lossy(&content);
    Ok(content.lines().map(str::to_string).collect())
}

fn expand_ext(line: &str, extensions: &[String]) -> Vec<String> {
    if !line.to_ascii_lowercase().contains("%ext%") {
        return vec![line.to_string()];
    }

    extensions
        .iter()
        .map(|extension| replace_case_insensitive(line, "%ext%", extension))
        .collect()
}

fn replace_case_insensitive(input: &str, needle: &str, replacement: &str) -> String {
    let lower_input = input.to_ascii_lowercase();
    let lower_needle = needle.to_ascii_lowercase();
    let mut output = String::with_capacity(input.len() + replacement.len());
    let mut start = 0;

    while let Some(pos) = lower_input[start..].find(&lower_needle) {
        let absolute = start + pos;
        output.push_str(&input[start..absolute]);
        output.push_str(replacement);
        start = absolute + needle.len();
    }
    output.push_str(&input[start..]);
    output
}

fn is_valid(path: &str, exclude_extensions: &[String]) -> bool {
    if path.is_empty() || path.starts_with('#') {
        return false;
    }

    let cleaned_path = clean_path(path);
    !exclude_extensions
        .iter()
        .any(|extension| cleaned_path.ends_with(&format!(".{extension}")))
}

fn clean_path(path: &str) -> &str {
    path.split(['?', '#']).next().unwrap_or(path)
}

fn should_overwrite_extension(
    path: &str,
    extensions: &[String],
    overwrite_exclude_extensions: &[String],
) -> bool {
    if path.ends_with('/') || path.contains('?') || path.contains('#') {
        return false;
    }

    if extensions
        .iter()
        .chain(overwrite_exclude_extensions.iter())
        .any(|extension| path.ends_with(extension))
    {
        return false;
    }

    has_extension_recognition_match(path)
}

fn has_extension_recognition_match(path: &str) -> bool {
    let candidate = path.strip_suffix('~').unwrap_or(path);
    for (start, _) in candidate.char_indices() {
        let tail = &candidate[start..];
        let parts: Vec<&str> = tail.split('.').collect();
        if !(2..=4).contains(&parts.len()) {
            continue;
        }
        if parts[0].is_empty() || !parts[0].chars().all(is_word_character) {
            continue;
        }
        if parts[1..].iter().all(|part| {
            (2..=5).contains(&part.len()) && part.chars().all(|ch| ch.is_ascii_alphanumeric())
        }) {
            return true;
        }
    }

    false
}

fn is_word_character(character: char) -> bool {
    character.is_ascii_alphanumeric() || character == '_'
}

fn add_entry(
    wordlist: &mut IndexSet<String>,
    path: String,
    max_size: Option<usize>,
) -> PyResult<()> {
    wordlist.insert(path);
    if let Some(limit) = max_size {
        if wordlist.len() > limit {
            return Err(PyRuntimeError::new_err(format!(
                "Generated wordlist exceeded --wordlist-max-size ({limit})"
            )));
        }
    }
    Ok(())
}

fn apply_case(path: String, lowercase: bool, uppercase: bool, capitalization: bool) -> String {
    if lowercase {
        path.to_lowercase()
    } else if uppercase {
        path.to_uppercase()
    } else if capitalization {
        let mut chars = path.chars();
        match chars.next() {
            Some(first) => {
                first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase()
            }
            None => path,
        }
    } else {
        path
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn default_filter_config() -> NativeFilterConfig {
        NativeFilterConfig::new(
            Vec::new(),
            Vec::new(),
            0,
            0,
            "or".to_string(),
            "or".to_string(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            None,
            None,
            Vec::new(),
            Vec::new(),
            None,
            None,
            Vec::new(),
            Vec::new(),
        )
        .unwrap()
    }

    fn content_length(value: usize) -> Vec<(String, String)> {
        vec![("Content-Length".to_string(), value.to_string())]
    }

    #[test]
    fn raw_http_path_preservation_detects_targets_reqwest_may_rewrite() {
        assert!(should_use_raw_http(
            "http://example.com/",
            "admin%3d..%1\\*"
        ));
        assert!(should_use_raw_http("http://example.com/", "admin%3d..%1*"));
        assert!(should_use_raw_http(
            "http://example.com/",
            "admin/%83%5c/.."
        ));
        assert!(!should_use_raw_http(
            "http://example.com/",
            "admin%20space/%E6%B5%8B%E8%AF%95"
        ));
        assert!(!should_use_raw_http("http://example.com/", "admin%3d"));
        assert!(!should_use_raw_http(
            "https://example.com/",
            "admin%3d..%1\\*"
        ));
    }

    fn raw_response(headers: &str, body: &[u8]) -> Vec<u8> {
        let mut response = format!("HTTP/1.1 200 OK\r\n{headers}\r\n\r\n").into_bytes();
        response.extend_from_slice(body);
        response
    }

    fn compressed_body(encoding: &str, body: &[u8]) -> Vec<u8> {
        if encoding == "gzip" {
            let mut encoder =
                flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(body).unwrap();
            encoder.finish().unwrap()
        } else if encoding == "deflate" {
            let mut encoder =
                flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(body).unwrap();
            encoder.finish().unwrap()
        } else {
            let mut compressed = Vec::new();
            {
                let mut encoder = brotli::CompressorWriter::new(&mut compressed, 4096, 5, 22);
                encoder.write_all(body).unwrap();
            }
            compressed
        }
    }

    fn reqwest_response(body: Vec<u8>, encoding: &str) -> (reqwest::Response, HeaderPairs) {
        let headers = vec![
            ("Content-Encoding".to_string(), encoding.to_string()),
            ("Content-Length".to_string(), body.len().to_string()),
        ];
        let response = http::Response::builder()
            .header("Content-Encoding", encoding)
            .header("Content-Length", body.len())
            .body(body)
            .unwrap()
            .into();
        (response, headers)
    }

    #[test]
    fn reqwest_response_decoder_streams_supported_content_encodings() {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let plain = b"hello world";
        let gzip = compressed_body("gzip", plain);
        let cases = [
            ("identity", plain.to_vec()),
            ("gzip", gzip.clone()),
            ("deflate", compressed_body("deflate", plain)),
            ("br", compressed_body("br", plain)),
            ("gzip, br", compressed_body("br", &gzip)),
        ];

        for (encoding, compressed) in cases {
            let (response, headers) = reqwest_response(compressed, encoding);
            let (body, length) = runtime
                .block_on(read_response_body(response, &headers, 5))
                .unwrap();

            assert_eq!(body, b"hello");
            assert_eq!(length, plain.len());
        }
    }

    #[test]
    fn reqwest_response_decoder_rejects_unknown_or_invalid_encodings() {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let (unknown, unknown_headers) = reqwest_response(b"hello world".to_vec(), "compress-test");
        let unknown_error = runtime
            .block_on(read_response_body(unknown, &unknown_headers, 80))
            .unwrap_err();
        let (invalid, invalid_headers) = reqwest_response(b"not gzip".to_vec(), "gzip");
        let invalid_error = runtime
            .block_on(read_response_body(invalid, &invalid_headers, 80))
            .unwrap_err();

        assert_eq!(
            unknown_error,
            "Unsupported HTTP Content-Encoding: compress-test"
        );
        assert!(invalid_error.starts_with("Failed to decode gzip response body:"));
    }

    #[test]
    fn raw_http_parser_decodes_chunked_body_and_tracks_decoded_length() {
        let response = raw_response(
            "Transfer-Encoding: chunked",
            b"4\r\nWiki\r\n5; extension=yes\r\npedia\r\n0\r\nX-Trailer: done\r\n\r\n",
        );

        let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(body, b"Wikipedia");
        assert_eq!(length, 9);
    }

    #[test]
    fn raw_http_parser_caps_chunked_body_without_losing_decoded_length() {
        let response = raw_response(
            "Transfer-Encoding: chunked",
            b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n",
        );

        let (_, _, body, length) = parse_raw_http_response(response, 4).unwrap();

        assert_eq!(body, b"Wiki");
        assert_eq!(length, 9);
    }

    #[test]
    fn raw_http_parser_honors_content_length_and_ignores_extra_bytes() {
        let response = raw_response("Content-Length: 4", b"bodyEXTRA");

        let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(body, b"body");
        assert_eq!(length, 4);
    }

    #[test]
    fn raw_http_parser_rejects_truncated_content_length() {
        let response = raw_response("Content-Length: 5", b"four");

        let error = parse_raw_http_response(response, 80).unwrap_err();

        assert!(error.contains("ended before Content-Length"));
    }

    #[test]
    fn raw_http_parser_rejects_truncated_chunked_body() {
        let response = raw_response("Transfer-Encoding: chunked", b"5\r\nfour");

        let error = parse_raw_http_response(response, 80).unwrap_err();

        assert!(error.contains("chunked body"));
    }

    #[test]
    fn raw_http_parser_decodes_gzip_before_body_filters() {
        let gzip_hello_world = [
            31, 139, 8, 0, 0, 0, 0, 0, 2, 3, 203, 72, 205, 201, 201, 87, 40, 207, 47, 202, 73, 1,
            0, 133, 17, 74, 13, 11, 0, 0, 0,
        ];
        let response = raw_response(
            &format!(
                "Content-Encoding: gzip\r\nContent-Length: {}",
                gzip_hello_world.len()
            ),
            &gzip_hello_world,
        );

        let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(body, b"hello world");
        assert_eq!(length, 11);
    }

    #[test]
    fn raw_http_parser_decodes_stacked_content_encodings() {
        let mut gzip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        gzip.write_all(b"hello world").unwrap();
        let gzip = gzip.finish().unwrap();
        let mut compressed = Vec::new();
        {
            let mut brotli = brotli::CompressorWriter::new(&mut compressed, 4096, 5, 22);
            brotli.write_all(&gzip).unwrap();
        }
        let response = raw_response("Content-Encoding: gzip, br", &compressed);

        let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(body, b"hello world");
        assert_eq!(length, 11);
    }

    #[test]
    fn raw_http_parser_decodes_zlib_wrapped_deflate() {
        let mut deflate =
            flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
        deflate.write_all(b"hello world").unwrap();
        let compressed = deflate.finish().unwrap();
        let response = raw_response("Content-Encoding: deflate", &compressed);

        let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(body, b"hello world");
        assert_eq!(length, 11);
    }

    #[test]
    fn raw_http_parser_rejects_ambiguous_message_framing() {
        let response = raw_response(
            "Content-Length: 4\r\nTransfer-Encoding: chunked",
            b"4\r\nbody\r\n0\r\n\r\n",
        );

        let error = parse_raw_http_response(response, 80).unwrap_err();

        assert!(error.contains("both Transfer-Encoding and Content-Length"));
    }

    #[test]
    fn raw_http_parser_bounds_response_headers() {
        let response = raw_response(&format!("X-Large: {}", "a".repeat(70 * 1024)), b"");

        let error = parse_raw_http_response(response, 80).unwrap_err();

        assert!(error.contains("HTTP header line exceeded"));
    }

    #[test]
    fn raw_http_parser_skips_informational_response() {
        let response =
            b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok".to_vec();

        let (status, _, body, length) = parse_raw_http_response(response, 80).unwrap();

        assert_eq!(status, 200);
        assert_eq!(body, b"ok");
        assert_eq!(length, 2);
    }

    #[test]
    fn legacy_status_filter_returns_empty_body_with_metadata() {
        let mut config = default_filter_config();
        config.exclude_status_codes = vec![404];

        let result = native_http_result(
            "missing".to_string(),
            404,
            content_length(64),
            b"not found body".to_vec(),
            25.0,
            &config,
        );

        assert!(result.filtered);
        assert_eq!(result.filter_reason.as_deref(), Some("exclude_status"));
        assert_eq!(result.length, 64);
        assert_eq!(result.elapsed_ms, 25.0);
        assert!(result.body.is_empty());
    }

    #[test]
    fn advanced_matchers_and_filters_respect_modes() {
        let mut config = default_filter_config();
        config.matcher_mode = "and".to_string();
        config.filter_mode = "or".to_string();
        config.match_status_codes = vec![200];
        config.match_words = vec![(2, 2)];
        config.match_lines = vec![(1, 1)];
        config.match_time = vec![(">".to_string(), 10.0)];
        config.filter_regex = Some(Regex::new("not found").unwrap());

        let keep = native_http_result(
            "admin".to_string(),
            200,
            Vec::new(),
            b"admin panel".to_vec(),
            20.0,
            &config,
        );
        assert!(!keep.filtered);
        assert_eq!(keep.body, b"admin panel");

        let filtered = native_http_result(
            "missing".to_string(),
            200,
            Vec::new(),
            b"not found".to_vec(),
            20.0,
            &config,
        );
        assert!(filtered.filtered);
        assert_eq!(filtered.filter_reason.as_deref(), Some("advanced_filter"));
        assert!(filtered.body.is_empty());

        let matcher_miss = native_http_result(
            "short".to_string(),
            200,
            Vec::new(),
            b"admin".to_vec(),
            20.0,
            &config,
        );
        assert!(matcher_miss.filtered);
        assert_eq!(
            matcher_miss.filter_reason.as_deref(),
            Some("advanced_matcher")
        );
    }

    #[test]
    fn advanced_filter_and_mode_requires_all_checks() {
        let mut config = default_filter_config();
        config.filter_mode = "and".to_string();
        config.filter_status_codes = vec![404];
        config.filter_sizes = vec![(10, 20)];

        let filtered = native_http_result(
            "missing".to_string(),
            404,
            content_length(12),
            b"not found".to_vec(),
            1.0,
            &config,
        );
        assert!(filtered.filtered);
        assert_eq!(filtered.filter_reason.as_deref(), Some("advanced_filter"));

        let keep = native_http_result(
            "small".to_string(),
            404,
            content_length(5),
            b"small".to_vec(),
            1.0,
            &config,
        );
        assert!(!keep.filtered);
    }

    #[test]
    fn advanced_header_matchers_and_filters_work() {
        let mut config = default_filter_config();
        config.match_headers = vec!["etag: w/\"123".to_string()];
        config.filter_header_regex = Some(Regex::new("X-Cache: fallback-[0-9]+").unwrap());

        let keep = native_http_result(
            "real".to_string(),
            200,
            vec![
                ("ETag".to_string(), "W/\"123-abc\"".to_string()),
                ("X-Cache".to_string(), "real".to_string()),
            ],
            b"same body".to_vec(),
            1.0,
            &config,
        );
        assert!(!keep.filtered);

        let filtered = native_http_result(
            "fallback".to_string(),
            200,
            vec![
                ("ETag".to_string(), "W/\"123-abc\"".to_string()),
                ("X-Cache".to_string(), "fallback-404".to_string()),
            ],
            b"same body".to_vec(),
            1.0,
            &config,
        );
        assert!(filtered.filtered);
        assert_eq!(filtered.filter_reason.as_deref(), Some("advanced_filter"));

        let matcher_miss = native_http_result(
            "missing-header".to_string(),
            200,
            vec![("X-Cache".to_string(), "real".to_string())],
            b"same body".to_vec(),
            1.0,
            &config,
        );
        assert!(matcher_miss.filtered);
        assert_eq!(
            matcher_miss.filter_reason.as_deref(),
            Some("advanced_matcher")
        );
    }

    #[test]
    fn regex_compile_errors_are_reported() {
        let error = NativeFilterConfig::new(
            Vec::new(),
            Vec::new(),
            0,
            0,
            "or".to_string(),
            "or".to_string(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Some("(".to_string()),
            None,
            Vec::new(),
            Vec::new(),
            None,
            None,
            Vec::new(),
            Vec::new(),
        )
        .err()
        .unwrap();

        assert!(error.contains("Invalid --match-regex regular expression"));
    }

    #[test]
    fn body_chunks_are_capped_without_losing_transferred_length() {
        let chunks: [&[u8]; 3] = [b"abc", b"defg", b"hijkl"];
        let mut body = Vec::new();
        let mut body_length = 0usize;

        for chunk in chunks {
            body_length = body_length.saturating_add(chunk.len());
            append_body_chunk(&mut body, chunk, 6);
        }

        assert_eq!(body, b"abcdef");
        assert_eq!(body_length, 12);
    }

    #[test]
    fn truncated_body_keeps_transferred_response_length() {
        let config = default_filter_config();
        let result = native_http_result_with_length(
            "large".to_string(),
            200,
            Vec::new(),
            b"abcdef".to_vec(),
            1024,
            1.0,
            &config,
        );

        assert_eq!(result.length, 1024);
        assert_eq!(result.body, b"abcdef");
    }

    #[test]
    fn runtime_workers_follow_available_cpu_bounds() {
        assert!((1..=256).contains(&runtime_worker_count()));
    }

    #[test]
    fn http_proxy_client_configuration_builds() {
        let client = build_http_client(
            &HeaderMap::new(),
            25,
            1.0,
            false,
            Some("http://user:password@127.0.0.1:8080"),
        );

        assert!(client.is_ok());
    }

    #[test]
    fn response_length_prefers_content_length_header() {
        assert_eq!(response_length(&content_length(123), 2), 123);
        assert_eq!(response_length(&[], 2), 2);
    }
}

#[pymodule]
fn dirsearch_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(generate_wordlist, module)?)?;
    module.add_function(wrap_pyfunction!(scan_http, module)?)?;
    module.add_class::<NativeHttpEngine>()?;
    module.add_class::<NativeHttpResult>()?;
    Ok(())
}
