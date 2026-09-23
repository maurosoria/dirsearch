//! Reqwest client construction, request execution, and body decoding.

use crate::filters::NativeFilterConfig;
use crate::raw_http;
use crate::result::{
    native_error_result, native_filtered_marker, native_http_result_with_length, NativeHttpResult,
};
use async_compression::tokio::bufread::{BrotliDecoder, GzipDecoder, ZlibDecoder};
use futures_util::TryStreamExt;
use reqwest::header::{HeaderMap, CONTENT_ENCODING};
use std::cell::RefCell;
use std::io;
use std::pin::Pin;
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, BufReader};
use tokio_util::io::StreamReader;

pub(crate) type HeaderPairs = Vec<(String, String)>;
type AsyncBodyReader = Pin<Box<dyn AsyncRead + Send>>;

tokio::task_local! {
    static REDIRECT_HISTORY: RefCell<Vec<String>>;
}

pub(crate) fn build_http_client(
    headers: &HeaderMap,
    concurrency: usize,
    timeout_secs: f64,
    follow_redirects: bool,
    max_redirects: usize,
    proxy_url: Option<&str>,
) -> Result<reqwest::Client, reqwest::Error> {
    let mut builder = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .default_headers(headers.clone())
        .redirect(if follow_redirects {
            let limited = reqwest::redirect::Policy::limited(max_redirects);
            reqwest::redirect::Policy::custom(move |attempt| {
                // Reqwest clones its redirect state per request. Mirror that
                // isolation here so concurrent scans cannot mix URL chains.
                let _ = REDIRECT_HISTORY.try_with(|history| {
                    // The callback runs once per hop. Only append the URL that
                    // produced this redirect instead of rebuilding the chain.
                    if let Some(previous_url) = attempt.previous().last() {
                        history.borrow_mut().push(previous_url.to_string());
                    }
                });
                limited.redirect(attempt)
            })
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

#[allow(clippy::too_many_arguments)]
pub(crate) async fn request_with_client(
    client: &reqwest::Client,
    url: &str,
    capture_redirect_history: bool,
    max_retries: usize,
    max_body_size: usize,
    start: Instant,
    filter_config: &NativeFilterConfig,
    compact_filtered: bool,
) -> NativeHttpResult {
    let mut last_error = None;
    for _ in 0..=max_retries {
        match request_once(
            client,
            url,
            capture_redirect_history,
            max_body_size,
            start,
            filter_config,
            compact_filtered,
        )
        .await
        {
            Ok(result) => return result,
            Err(error) => {
                let retryable = !error.contains("tunnel error: unsuccessful");
                last_error = Some(error);
                if !retryable {
                    break;
                }
            }
        }
    }

    native_error_result(
        String::new(),
        start.elapsed().as_secs_f64() * 1000.0,
        last_error.unwrap_or_else(|| "request failed".to_string()),
    )
}

#[allow(clippy::too_many_arguments)]
async fn request_once(
    client: &reqwest::Client,
    url: &str,
    capture_redirect_history: bool,
    max_body_size: usize,
    start: Instant,
    filter_config: &NativeFilterConfig,
    compact_filtered: bool,
) -> Result<NativeHttpResult, String> {
    let (response, redirect_history) = if capture_redirect_history {
        REDIRECT_HISTORY
            .scope(RefCell::new(Vec::new()), async {
                let result = client.get(url).send().await;
                let history = REDIRECT_HISTORY.with(|history| history.borrow().clone());
                (result, history)
            })
            .await
    } else {
        (client.get(url).send().await, Vec::new())
    };
    let response = response.map_err(|error| format_error_chain(&error))?;
    let status = response.status().as_u16();
    let final_url = response.url().to_string();
    if compact_filtered && status != 407 && filter_config.status_filter_reason(status).is_some() {
        let encodings = response_encodings(response.headers());
        read_decoded_body(response, encodings, 0, false).await?;
        let mut result = native_filtered_marker(status, start.elapsed().as_secs_f64() * 1000.0);
        result.history = redirect_history;
        result.final_url = final_url;
        return Ok(result);
    }
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
    let (body, body_length) = read_response_body(response, &headers, max_body_size).await?;
    let mut result = native_http_result_with_length(
        String::new(),
        status,
        headers,
        body,
        body_length,
        start.elapsed().as_secs_f64() * 1000.0,
        filter_config,
    );
    result.history = redirect_history;
    result.final_url = final_url;
    Ok(result)
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

pub(crate) async fn read_response_body(
    response: reqwest::Response,
    headers: &HeaderPairs,
    max_body_size: usize,
) -> Result<(Vec<u8>, usize), String> {
    let encodings = raw_http::comma_separated_header_values(headers, "content-encoding");
    read_decoded_body(response, encodings, max_body_size, true).await
}

fn response_encodings(headers: &HeaderMap) -> Vec<String> {
    headers
        .get_all(CONTENT_ENCODING)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(','))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect()
}

async fn read_decoded_body(
    response: reqwest::Response,
    encodings: Vec<String>,
    max_body_size: usize,
    capture_body: bool,
) -> Result<(Vec<u8>, usize), String> {
    let capacity = if capture_body {
        response
            .content_length()
            .and_then(|length| usize::try_from(length).ok())
            .unwrap_or_default()
            .min(max_body_size)
    } else {
        0
    };
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
        if capture_body {
            append_body_chunk(&mut body, &buffer[..read], max_body_size);
        }
    }

    Ok((body, body_length))
}

pub(crate) fn append_body_chunk(body: &mut Vec<u8>, chunk: &[u8], max_body_size: usize) {
    let remaining = max_body_size.saturating_sub(body.len());
    body.extend_from_slice(&chunk[..chunk.len().min(remaining)]);
}
