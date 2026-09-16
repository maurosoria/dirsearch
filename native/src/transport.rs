//! Reqwest client construction, request execution, and body decoding.

use crate::filters::NativeFilterConfig;
use crate::raw_http;
use crate::result::{native_error_result, native_http_result_with_length, NativeHttpResult};
use async_compression::tokio::bufread::{BrotliDecoder, GzipDecoder, ZlibDecoder};
use futures_util::TryStreamExt;
use reqwest::header::HeaderMap;
use std::io;
use std::pin::Pin;
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, BufReader};
use tokio_util::io::StreamReader;

pub(crate) type HeaderPairs = Vec<(String, String)>;
type AsyncBodyReader = Pin<Box<dyn AsyncRead + Send>>;

pub(crate) fn build_http_client(
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

pub(crate) async fn request_with_client(
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

pub(crate) async fn read_response_body(
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

pub(crate) fn append_body_chunk(body: &mut Vec<u8>, chunk: &[u8], max_body_size: usize) {
    let remaining = max_body_size.saturating_sub(body.len());
    body.extend_from_slice(&chunk[..chunk.len().min(remaining)]);
}
