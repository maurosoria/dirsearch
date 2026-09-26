//! Adapter for paths that require byte-preserving HTTP/1.1 requests.

use crate::filters::NativeFilterConfig;
use crate::raw_http;
use crate::result::{native_error_result, native_http_result_with_length, NativeHttpResult};
use crate::session::NativeCookieStore;
use crate::transport::HeaderPairs;
use reqwest::cookie::CookieStore;
#[cfg(test)]
use std::io::Cursor;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

type RawHttpResponse = raw_http::Response;

pub(crate) struct RawHttpRequest<'a> {
    pub(crate) base_url: &'a str,
    pub(crate) path: &'a str,
    pub(crate) method: &'a str,
    pub(crate) body: &'a [u8],
    pub(crate) headers: &'a HeaderPairs,
    pub(crate) timeout_secs: f64,
    pub(crate) max_body_size: usize,
    pub(crate) start: Instant,
    pub(crate) cancelled: Arc<AtomicBool>,
    pub(crate) cookie_store: Arc<NativeCookieStore>,
}

pub(crate) fn should_use_raw_http(base_url: &str, path: &str) -> bool {
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

pub(crate) async fn raw_http_request(
    request: RawHttpRequest<'_>,
    max_retries: usize,
    filter_config: &NativeFilterConfig,
) -> NativeHttpResult {
    let mut last_error = None;
    let mut attempt_start = request.start;
    for attempt in 0..=max_retries {
        match raw_http_request_inner(&request, attempt_start).await {
            Ok((status, headers, body, length)) => {
                return native_http_result_with_length(
                    String::new(),
                    status,
                    headers,
                    body,
                    length,
                    attempt_start.elapsed().as_secs_f64() * 1000.0,
                    filter_config,
                );
            }
            Err(error) => {
                last_error = Some(error);
                if request.cancelled.load(Ordering::Acquire) || attempt == max_retries {
                    break;
                }
                // Keep elapsed and the per-attempt timeout aligned with the
                // Python requesters when another attempt starts.
                attempt_start = Instant::now();
            }
        }
    }

    native_error_result(
        String::new(),
        attempt_start.elapsed().as_secs_f64() * 1000.0,
        last_error.unwrap_or_else(|| "request failed".to_string()),
    )
}

async fn raw_http_request_inner(
    request: &RawHttpRequest<'_>,
    attempt_start: Instant,
) -> Result<RawHttpResponse, String> {
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
    let target = raw_request_target(url.path(), request.path);
    let mut cookie_url = url.clone();
    cookie_url.set_path(target.split(['?', '#']).next().unwrap_or("/"));
    let mut wire_request = format!(
        "{} {target} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n",
        request.method
    )
    .into_bytes();
    for (name, value) in request.headers {
        wire_request.extend_from_slice(name.as_bytes());
        wire_request.extend_from_slice(b": ");
        wire_request.extend_from_slice(value.as_bytes());
        wire_request.extend_from_slice(b"\r\n");
    }
    if !request
        .headers
        .iter()
        .any(|(name, _)| name.eq_ignore_ascii_case("cookie"))
    {
        if let Some(cookie) = request.cookie_store.cookies(&cookie_url) {
            wire_request.extend_from_slice(b"Cookie: ");
            wire_request.extend_from_slice(cookie.as_bytes());
            wire_request.extend_from_slice(b"\r\n");
        }
    }
    if !request.body.is_empty()
        && !request
            .headers
            .iter()
            .any(|(name, _)| name.eq_ignore_ascii_case("content-length"))
    {
        wire_request
            .extend_from_slice(format!("Content-Length: {}\r\n", request.body.len()).as_bytes());
    }
    wire_request.extend_from_slice(b"\r\n");
    wire_request.extend_from_slice(request.body);

    let timeout = Duration::from_secs_f64(request.timeout_secs);
    let deadline = attempt_start
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
    let response_cookie_store = request.cookie_store.clone();
    let response_cookie_url = cookie_url.clone();
    let exchange = tokio::task::spawn_blocking(move || {
        raw_http::exchange(
            stream,
            &wire_request,
            deadline,
            cancelled,
            max_body_size,
            move |headers| {
                for (_, value) in headers
                    .iter()
                    .filter(|(name, _)| name.eq_ignore_ascii_case("set-cookie"))
                {
                    response_cookie_store.add_cookie_str(value, &response_cookie_url);
                }
            },
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
pub(crate) fn parse_raw_http_response(
    raw_response: Vec<u8>,
    max_body_size: usize,
) -> Result<RawHttpResponse, String> {
    raw_http::parse_response(Cursor::new(raw_response), max_body_size)
}
