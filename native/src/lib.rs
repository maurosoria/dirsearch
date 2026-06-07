use indexmap::IndexSet;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rayon::prelude::*;
use regex::Regex;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::Arc;
use std::time::{Duration, Instant};

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

type NumericRange = (usize, usize);
type TimeFilter = (String, f64);
type HeaderPairs = Vec<(String, String)>;
type RawHttpResponse = (u16, HeaderPairs, Vec<u8>, usize);

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
            match_time,
            filter_time,
        })
    }

    fn filter_reason(
        &self,
        status: u16,
        length: usize,
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

        if !self.matches_advanced_matchers(status, length, text, elapsed_ms) {
            return Some("advanced_matcher");
        }

        if self.matches_advanced_filters(status, length, text, elapsed_ms) {
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

    fn matches_advanced_matchers(
        &self,
        status: u16,
        length: usize,
        text: Option<&str>,
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

#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (
    base_url,
    paths,
    concurrency=25,
    timeout_secs=7.5,
    headers=Vec::new(),
    max_retries=0,
    delay_secs=0.0,
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
    match_time=Vec::new(),
    filter_time=Vec::new(),
))]
fn scan_http(
    py: Python<'_>,
    base_url: String,
    paths: Vec<String>,
    concurrency: usize,
    timeout_secs: f64,
    headers: Vec<(String, String)>,
    max_retries: usize,
    delay_secs: f64,
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
            match_time,
            filter_time,
        )
        .map_err(PyRuntimeError::new_err)?,
    );

    py.allow_threads(move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(concurrency.clamp(1, 256))
            .build()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        runtime.block_on(async move {
            let raw_headers = headers.clone();
            let mut header_map = HeaderMap::new();
            for (name, value) in headers {
                let name = HeaderName::from_bytes(name.as_bytes())
                    .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
                let value = HeaderValue::from_str(&value)
                    .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
                header_map.insert(name, value);
            }

            let client = reqwest::Client::builder()
                .danger_accept_invalid_certs(true)
                .default_headers(header_map)
                .redirect(if follow_redirects {
                    reqwest::redirect::Policy::limited(10)
                } else {
                    reqwest::redirect::Policy::none()
                })
                .timeout(std::time::Duration::from_secs_f64(timeout_secs))
                .pool_max_idle_per_host(concurrency)
                .build()
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

            let semaphore = std::sync::Arc::new(tokio::sync::Semaphore::new(concurrency.max(1)));
            let mut tasks = Vec::with_capacity(paths.len());

            for path in paths {
                let client = client.clone();
                let base_url = base_url.clone();
                let raw_headers = raw_headers.clone();
                let semaphore = semaphore.clone();
                let filter_config = filter_config.clone();
                tasks.push(tokio::spawn(async move {
                    let _permit = match semaphore.acquire_owned().await {
                        Ok(permit) => permit,
                        Err(error) => {
                            return native_error_result(path, 0.0, error.to_string());
                        }
                    };
                    if delay_secs > 0.0 {
                        tokio::time::sleep(Duration::from_secs_f64(delay_secs)).await;
                    }
                    let url = format!("{base_url}{path}");
                    let start = Instant::now();

                    if should_use_raw_http(&base_url, &path) {
                        let raw_base_url = base_url.clone();
                        let raw_path = path.clone();
                        let raw_filter_config = filter_config.clone();
                        let raw_result = tokio::task::spawn_blocking(move || {
                            raw_http_get(
                                &raw_base_url,
                                raw_path,
                                &raw_headers,
                                timeout_secs,
                                max_body_size,
                                start,
                                raw_filter_config.as_ref(),
                            )
                        })
                        .await;

                        return match raw_result {
                            Ok(result) => result,
                            Err(error) => native_error_result(
                                path,
                                start.elapsed().as_secs_f64() * 1000.0,
                                error.to_string(),
                            ),
                        };
                    }

                    let mut response = None;
                    let mut last_error = None;
                    for _ in 0..=max_retries {
                        match client.get(&url).send().await {
                            Ok(value) => {
                                response = Some(value);
                                last_error = None;
                                break;
                            }
                            Err(error) => last_error = Some(error.to_string()),
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
                    let body = match response.bytes().await {
                        Ok(body) => body,
                        Err(error) => {
                            return native_error_result(
                                path,
                                start.elapsed().as_secs_f64() * 1000.0,
                                error.to_string(),
                            );
                        }
                    };
                    let length = body.len();
                    let body = body[..length.min(max_body_size)].to_vec();
                    native_http_result(
                        path,
                        status,
                        headers,
                        body,
                        start.elapsed().as_secs_f64() * 1000.0,
                        filter_config.as_ref(),
                    )
                }));
            }

            let mut results = Vec::with_capacity(tasks.len());
            for task in tasks {
                let result = task
                    .await
                    .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
                results.push(result);
            }
            Ok(results)
        })
    })
}

fn native_http_result(
    path: String,
    status: u16,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    elapsed_ms: f64,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    let length = response_length(&headers, body.len());
    let filter_reason = filter_config
        .filter_reason(status, length, &body, elapsed_ms)
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

fn raw_http_get(
    base_url: &str,
    path: String,
    headers: &[(String, String)],
    timeout_secs: f64,
    max_body_size: usize,
    start: Instant,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    match raw_http_get_inner(base_url, &path, headers, timeout_secs, max_body_size) {
        Ok((status, headers, body, _length)) => native_http_result(
            path,
            status,
            headers,
            body,
            start.elapsed().as_secs_f64() * 1000.0,
            filter_config,
        ),
        Err(error) => native_error_result(path, start.elapsed().as_secs_f64() * 1000.0, error),
    }
}

fn raw_http_get_inner(
    base_url: &str,
    path: &str,
    headers: &[(String, String)],
    timeout_secs: f64,
    max_body_size: usize,
) -> Result<RawHttpResponse, String> {
    let url = reqwest::Url::parse(base_url).map_err(|error| error.to_string())?;
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
    let timeout = Duration::from_secs_f64(timeout_secs);
    let mut stream =
        TcpStream::connect((host.as_str(), port)).map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(timeout))
        .map_err(|error| error.to_string())?;
    stream
        .set_write_timeout(Some(timeout))
        .map_err(|error| error.to_string())?;

    let target = raw_request_target(url.path(), path);
    let mut request =
        format!("GET {target} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n");
    for (name, value) in headers {
        request.push_str(name);
        request.push_str(": ");
        request.push_str(value);
        request.push_str("\r\n");
    }
    request.push_str("\r\n");
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;

    let mut raw_response = Vec::new();
    stream
        .read_to_end(&mut raw_response)
        .map_err(|error| error.to_string())?;
    parse_raw_http_response(raw_response, max_body_size)
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

fn parse_raw_http_response(
    raw_response: Vec<u8>,
    max_body_size: usize,
) -> Result<RawHttpResponse, String> {
    let header_end = raw_response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "HTTP response did not contain a header terminator".to_string())?;
    let header_bytes = &raw_response[..header_end];
    let body_start = header_end + 4;
    let body_bytes = &raw_response[body_start..];
    let header_text = String::from_utf8_lossy(header_bytes);
    let mut lines = header_text.split("\r\n");
    let status_line = lines
        .next()
        .ok_or_else(|| "HTTP response did not contain a status line".to_string())?;
    let status = status_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| "HTTP response status line did not contain a status code".to_string())?
        .parse::<u16>()
        .map_err(|error| error.to_string())?;
    let headers = lines
        .filter_map(|line| {
            line.split_once(':')
                .map(|(name, value)| (name.to_string(), value.trim_start().to_string()))
        })
        .collect::<Vec<_>>();
    let length = body_bytes.len();
    let body = body_bytes[..length.min(max_body_size)].to_vec();
    Ok((status, headers, body, length))
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
        )
        .err()
        .unwrap();

        assert!(error.contains("Invalid --match-regex regular expression"));
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
    module.add_class::<NativeHttpResult>()?;
    Ok(())
}
