//! Python-visible result data and response-to-result conversion.

use crate::filters::NativeFilterConfig;
use pyo3::prelude::*;

#[pyclass]
pub(crate) struct NativeHttpResult {
    /// Position in the input batch; Python uses gaps to reconstruct filtered runs.
    #[pyo3(get)]
    pub(crate) request_index: usize,
    #[pyo3(get)]
    pub(crate) path: String,
    #[pyo3(get)]
    pub(crate) status: u16,
    #[pyo3(get)]
    pub(crate) length: usize,
    #[pyo3(get)]
    pub(crate) elapsed_ms: f64,
    #[pyo3(get)]
    pub(crate) error: Option<String>,
    #[pyo3(get)]
    pub(crate) filtered: bool,
    #[pyo3(get)]
    pub(crate) filter_reason: Option<String>,
    #[pyo3(get)]
    pub(crate) headers: Vec<(String, String)>,
    #[pyo3(get)]
    pub(crate) body: Vec<u8>,
    #[pyo3(get)]
    pub(crate) body_complete: bool,
}

#[cfg(test)]
pub(crate) fn native_http_result(
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

pub(crate) fn native_http_result_with_length(
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
    let body_complete = !filtered && body.len() == body_length;

    NativeHttpResult {
        request_index: usize::MAX,
        path,
        status,
        length,
        elapsed_ms,
        error: None,
        filtered,
        filter_reason,
        headers,
        body: if filtered { Vec::new() } else { body },
        body_complete,
    }
}

pub(crate) fn native_error_result(
    path: String,
    elapsed_ms: f64,
    error: String,
) -> NativeHttpResult {
    NativeHttpResult {
        request_index: usize::MAX,
        path,
        status: 0,
        length: 0,
        elapsed_ms,
        error: Some(error),
        filtered: false,
        filter_reason: None,
        headers: Vec::new(),
        body: Vec::new(),
        body_complete: false,
    }
}

pub(crate) fn native_filtered_marker(status: u16, elapsed_ms: f64) -> NativeHttpResult {
    NativeHttpResult {
        request_index: usize::MAX,
        path: String::new(),
        status,
        length: 0,
        elapsed_ms,
        error: None,
        filtered: true,
        filter_reason: None,
        headers: Vec::new(),
        body: Vec::new(),
        body_complete: false,
    }
}

pub(crate) fn native_completion_marker(request_index: usize) -> NativeHttpResult {
    NativeHttpResult {
        request_index,
        path: String::new(),
        status: 0,
        length: 0,
        elapsed_ms: 0.0,
        error: None,
        filtered: true,
        filter_reason: None,
        headers: Vec::new(),
        body: Vec::new(),
        body_complete: false,
    }
}

pub(crate) fn response_length(headers: &[(String, String)], body_length: usize) -> usize {
    headers
        .iter()
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        .and_then(|(_, value)| value.parse::<usize>().ok())
        .unwrap_or(body_length)
}
