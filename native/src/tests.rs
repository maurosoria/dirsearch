//! Cross-module regression tests for the native backend contract.

use super::*;
use crate::raw_client::{raw_http_request, RawHttpRequest};
use crate::transport::request_with_client;
use bytes::Bytes;
use rcgen::{
    date_time_ymd, BasicConstraints, CertificateParams, ExtendedKeyUsagePurpose, IsCa, Issuer,
    KeyPair, KeyUsagePurpose,
};
use reqwest::Method;
use rustls::pki_types::{PrivateKeyDer, PrivatePkcs8KeyDer};
use rustls::server::WebPkiClientVerifier;
use rustls::{RootCertStore, ServerConfig};
use std::io::{ErrorKind, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const INCOMPLETE_BODY_RESPONSE: &[u8] =
    b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nno";
const OK_RESPONSE: &[u8] = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok";
const ZSTD_HELLO_WORLD: &[u8] = &[
    0x28, 0xb5, 0x2f, 0xfd, 0x04, 0x58, 0x59, 0x00, 0x00, 0x68, 0x65, 0x6c, 0x6c, 0x6f, 0x20, 0x77,
    0x6f, 0x72, 0x6c, 0x64, 0x68, 0x69, 0x1e, 0xb2,
];
type CapturedRequests = Arc<Mutex<Vec<Vec<u8>>>>;
type RetryServer = (String, thread::JoinHandle<()>, CapturedRequests);

fn default_filter_config() -> NativeFilterConfig {
    NativeFilterConfig::from_options(
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

fn read_http_request(stream: &mut TcpStream) -> Vec<u8> {
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .unwrap();
    let mut request = Vec::new();
    let mut buffer = [0u8; 1024];
    let header_end = loop {
        let read = stream.read(&mut buffer).unwrap();
        assert!(read > 0, "connection closed before request headers");
        request.extend_from_slice(&buffer[..read]);
        if let Some(index) = request.windows(4).position(|window| window == b"\r\n\r\n") {
            break index + 4;
        }
    };
    let headers = String::from_utf8_lossy(&request[..header_end]);
    let content_length = headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("content-length")
                .then(|| value.trim().parse::<usize>().unwrap())
        })
        .unwrap_or_default();
    let request_length = header_end + content_length;
    while request.len() < request_length {
        let read = stream.read(&mut buffer).unwrap();
        assert!(read > 0, "connection closed before request body");
        request.extend_from_slice(&buffer[..read]);
    }
    request.truncate(request_length);
    request
}

fn spawn_retry_body_server(responses: Vec<&'static [u8]>) -> RetryServer {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let address = listener.local_addr().unwrap();
    let requests = Arc::new(Mutex::new(Vec::new()));
    let server_requests = requests.clone();
    let server = thread::spawn(move || {
        for response in responses {
            let deadline = Instant::now() + Duration::from_secs(2);
            let (mut stream, _) = loop {
                match listener.accept() {
                    Ok(connection) => break connection,
                    Err(error)
                        if error.kind() == ErrorKind::WouldBlock && Instant::now() < deadline =>
                    {
                        thread::sleep(Duration::from_millis(1));
                    }
                    Err(error) => panic!("test server did not receive request: {error}"),
                }
            };
            let request = read_http_request(&mut stream);
            server_requests.lock().unwrap().push(request);
            stream.write_all(response).unwrap();
        }
    });

    (format!("http://{address}"), server, requests)
}

fn run_reqwest_retry(responses: Vec<&'static [u8]>) -> NativeHttpResult {
    run_reqwest_request(Method::GET, Bytes::new(), responses, 1).0
}

fn run_reqwest_request(
    method: Method,
    body: Bytes,
    responses: Vec<&'static [u8]>,
    max_retries: usize,
) -> (NativeHttpResult, Vec<Vec<u8>>) {
    let (base_url, server, requests) = spawn_retry_body_server(responses);
    let client = build_http_client(&HeaderMap::new(), 1, 2.0, false, 30, None, None).unwrap();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let result = runtime.block_on(request_with_client(
        &client,
        &format!("{base_url}/retry"),
        &method,
        body,
        false,
        max_retries,
        80,
        Instant::now() - Duration::from_secs(5),
        &default_filter_config(),
        false,
    ));
    server.join().unwrap();
    let requests = Arc::try_unwrap(requests).unwrap().into_inner().unwrap();
    (result, requests)
}

fn run_raw_retry(responses: Vec<&'static [u8]>) -> NativeHttpResult {
    run_raw_request("GET", b"", responses, 1).0
}

fn run_raw_request(
    method: &str,
    body: &[u8],
    responses: Vec<&'static [u8]>,
    max_retries: usize,
) -> (NativeHttpResult, Vec<Vec<u8>>) {
    let (base_url, server, requests) = spawn_retry_body_server(responses);
    let headers = Vec::new();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let result = runtime.block_on(raw_http_request(
        RawHttpRequest {
            base_url: &base_url,
            path: "retry%1",
            method,
            body,
            headers: &headers,
            timeout_secs: 30.0,
            max_body_size: 80,
            start: Instant::now() - Duration::from_secs(5),
            cancelled: Arc::new(AtomicBool::new(false)),
        },
        max_retries,
        &default_filter_config(),
    ));
    server.join().unwrap();
    let requests = Arc::try_unwrap(requests).unwrap().into_inner().unwrap();
    (result, requests)
}

fn assert_final_attempt_elapsed(result: &NativeHttpResult) {
    assert!(
        result.elapsed_ms < 1_000.0,
        "elapsed included an earlier failed attempt: {} ms",
        result.elapsed_ms
    );
}

#[test]
fn proxy_authentication_failures_are_not_retryable() {
    for error in [
        "tunnel error: unsuccessful",
        "tunnel error: proxy authorization required",
        "SOCKS error: credentials not accepted",
    ] {
        assert!(is_non_retryable_proxy_error(error), "{error}");
    }

    assert!(!is_non_retryable_proxy_error("connection reset by peer"));
}

#[test]
fn reqwest_redirects_preserve_every_requested_url_in_history() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0u8; 1024];
            let read = stream.read(&mut request).unwrap();
            let target = std::str::from_utf8(&request[..read])
                .unwrap()
                .split_whitespace()
                .nth(1)
                .unwrap();
            let response = match target {
                "/start" => {
                    "HTTP/1.1 302 Found\r\nLocation: /middle\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                }
                "/middle" => {
                    "HTTP/1.1 307 Temporary Redirect\r\nLocation: /final?ok=1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                }
                "/final?ok=1" => {
                    "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                }
                _ => panic!("unexpected request target: {target}"),
            };
            stream.write_all(response.as_bytes()).unwrap();
        }
    });
    let base_url = format!("http://{address}");
    let start_url = format!("{base_url}/start");
    let client = build_http_client(&HeaderMap::new(), 1, 2.0, true, 30, None, None).unwrap();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();

    let result = runtime.block_on(request_with_client(
        &client,
        &start_url,
        &Method::GET,
        Bytes::new(),
        true,
        0,
        80,
        std::time::Instant::now(),
        &default_filter_config(),
        false,
    ));
    server.join().unwrap();

    assert_eq!(result.status, 200);
    assert_eq!(result.final_url, format!("{base_url}/final?ok=1"));
    assert_eq!(
        result.history,
        vec![start_url, format!("{base_url}/middle")]
    );
}

#[test]
fn reqwest_retry_elapsed_reports_only_the_successful_attempt() {
    let result = run_reqwest_retry(vec![INCOMPLETE_BODY_RESPONSE, OK_RESPONSE]);

    assert_eq!(result.status, 200);
    assert_eq!(result.body, b"ok");
    assert_final_attempt_elapsed(&result);
}

#[test]
fn reqwest_exhausted_retry_elapsed_reports_only_the_final_attempt() {
    let result = run_reqwest_retry(vec![INCOMPLETE_BODY_RESPONSE, INCOMPLETE_BODY_RESPONSE]);

    assert!(result.error.is_some());
    assert_final_attempt_elapsed(&result);
}

#[test]
fn raw_retry_elapsed_reports_only_the_successful_attempt() {
    let result = run_raw_retry(vec![INCOMPLETE_BODY_RESPONSE, OK_RESPONSE]);

    assert_eq!(result.status, 200);
    assert_eq!(result.body, b"ok");
    assert_final_attempt_elapsed(&result);
}

#[test]
fn raw_exhausted_retry_elapsed_reports_only_the_final_attempt() {
    let result = run_raw_retry(vec![INCOMPLETE_BODY_RESPONSE, INCOMPLETE_BODY_RESPONSE]);

    assert!(result.error.is_some());
    assert_final_attempt_elapsed(&result);
}

#[test]
fn reqwest_retries_preserve_method_and_binary_body() {
    let body = Bytes::from_static(b"value=\xff\r\nnext=line\n");
    let (result, requests) = run_reqwest_request(
        Method::PATCH,
        body.clone(),
        vec![INCOMPLETE_BODY_RESPONSE, OK_RESPONSE],
        1,
    );

    assert_eq!(result.status, 200);
    assert_eq!(requests.len(), 2);
    for request in requests {
        assert!(request.starts_with(b"PATCH /retry HTTP/1.1\r\n"));
        assert!(request.ends_with(body.as_ref()));
    }
}

#[test]
fn raw_retries_preserve_method_and_binary_body() {
    let body = b"value=\xff\r\nnext=line\n";
    let (result, requests) = run_raw_request(
        "PATCH",
        body,
        vec![INCOMPLETE_BODY_RESPONSE, OK_RESPONSE],
        1,
    );

    assert_eq!(result.status, 200);
    assert_eq!(requests.len(), 2);
    let content_length = format!("Content-Length: {}\r\n", body.len());
    for request in requests {
        assert!(request.starts_with(b"PATCH /retry%1 HTTP/1.1\r\n"));
        assert!(request
            .windows(content_length.len())
            .any(|window| window == content_length.as_bytes()));
        assert!(request.ends_with(body));
    }
}

#[test]
fn request_target_quoting_matches_python_ascii_contract() {
    for value in 0u8..=127 {
        let mut path = char::from(value).to_string();
        prepare_request_target(&mut path, "");
        let expected = if (b'!'..=b'~').contains(&value) {
            char::from(value).to_string()
        } else {
            format!("%{value:02X}")
        };

        assert_eq!(path, expected, "ASCII value {value}");
    }
}

#[test]
fn request_target_quotes_utf8_and_appends_query_before_fragment() {
    let mut path = "missing page/测试#part".to_string();
    prepare_request_target(&mut path, "scope=hello world");

    assert_eq!(
        path,
        "missing%20page/%E6%B5%8B%E8%AF%95?scope=hello%20world#part"
    );

    let mut existing_query = "admin?existing=true#part".to_string();
    prepare_request_target(&mut existing_query, "ignored=true");
    assert_eq!(existing_query, "admin?existing=true#part");

    let mut existing_escape = "admin%20panel".to_string();
    prepare_request_target(&mut existing_escape, "");
    assert_eq!(existing_escape, "admin%20panel");
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
    match encoding {
        "gzip" => {
            let mut encoder =
                flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(body).unwrap();
            encoder.finish().unwrap()
        }
        "deflate" => {
            let mut encoder =
                flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(body).unwrap();
            encoder.finish().unwrap()
        }
        "br" => {
            let mut compressed = Vec::new();
            {
                let mut encoder = brotli::CompressorWriter::new(&mut compressed, 4096, 5, 22);
                encoder.write_all(body).unwrap();
            }
            compressed
        }
        "zstd" => zstd::stream::encode_all(body, 0).unwrap(),
        _ => panic!("unsupported test encoding: {encoding}"),
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
        ("zstd", ZSTD_HELLO_WORLD.to_vec()),
        ("gzip, br", compressed_body("br", &gzip)),
        ("gzip, zstd", compressed_body("zstd", &gzip)),
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
    let (invalid_zstd, invalid_zstd_headers) = reqwest_response(b"not zstd".to_vec(), "zstd");
    let invalid_zstd_error = runtime
        .block_on(read_response_body(invalid_zstd, &invalid_zstd_headers, 80))
        .unwrap_err();

    assert_eq!(
        unknown_error,
        "Unsupported HTTP Content-Encoding: compress-test"
    );
    assert!(invalid_error.starts_with("Failed to decode gzip response body:"));
    assert!(invalid_zstd_error.starts_with("Failed to decode zstd response body:"));
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
        31, 139, 8, 0, 0, 0, 0, 0, 2, 3, 203, 72, 205, 201, 201, 87, 40, 207, 47, 202, 73, 1, 0,
        133, 17, 74, 13, 11, 0, 0, 0,
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
fn raw_http_parser_decodes_zstd_before_body_filters() {
    let response = raw_response(
        &format!(
            "Content-Encoding: zstd\r\nContent-Length: {}",
            ZSTD_HELLO_WORLD.len()
        ),
        ZSTD_HELLO_WORLD,
    );

    let (_, _, body, length) = parse_raw_http_response(response, 5).unwrap();

    assert_eq!(body, b"hello");
    assert_eq!(length, 11);
}

#[test]
fn raw_http_parser_decodes_zstd_as_outer_stacked_encoding() {
    let gzip = compressed_body("gzip", b"hello world");
    let zstd = compressed_body("zstd", &gzip);
    let response = raw_response("Content-Encoding: gzip, zstd", &zstd);

    let (_, _, body, length) = parse_raw_http_response(response, 80).unwrap();

    assert_eq!(body, b"hello world");
    assert_eq!(length, 11);
}

#[test]
fn raw_http_parser_rejects_invalid_zstd() {
    let response = raw_response("Content-Encoding: zstd", b"not zstd");

    let error = parse_raw_http_response(response, 80).unwrap_err();

    assert!(error.starts_with("Failed to decode zstd response body:"));
}

#[test]
fn raw_http_parser_decodes_zlib_wrapped_deflate() {
    let mut deflate = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
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
    config.filter_regex = compile_regex(Some("not found".to_string()), "--filter-regex").unwrap();

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
fn non_utf8_text_filters_are_deferred_to_python() {
    let mut config = default_filter_config();
    config.match_regex = compile_regex(Some("£".to_string()), "--match-regex").unwrap();
    let body = b"price \xa3".to_vec();

    let result = native_http_result(
        "price".to_string(),
        200,
        vec![(
            "Content-Type".to_string(),
            "text/plain; Charset=\"windows-1252\"".to_string(),
        )],
        body.clone(),
        1.0,
        &config,
    );

    assert!(!result.filtered);
    assert_eq!(result.filter_reason, None);
    assert_eq!(result.body, body);
}

#[test]
fn utf8_text_filters_keep_the_native_fast_path() {
    let mut config = default_filter_config();
    config.filter_regex = compile_regex(Some("£".to_string()), "--filter-regex").unwrap();

    let result = native_http_result(
        "price".to_string(),
        200,
        vec![(
            "Content-Type".to_string(),
            "text/plain; Charset=UTF_8".to_string(),
        )],
        "price £".as_bytes().to_vec(),
        1.0,
        &config,
    );

    assert!(result.filtered);
    assert_eq!(result.filter_reason.as_deref(), Some("advanced_filter"));
    assert!(result.body.is_empty());
}

#[test]
fn advanced_header_matchers_and_filters_work() {
    let mut config = default_filter_config();
    config.match_headers = vec!["etag: w/\"123".to_string()];
    config.filter_header_regex = compile_header_regex(
        Some("X-Cache: fallback-[0-9]+".to_string()),
        "--filter-header-regex",
    )
    .unwrap();

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
    let error = NativeFilterConfig::from_options(
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
fn python_lookarounds_execute_in_native_filters() {
    for (pattern, body) in [
        (r"(?=admin)admin", b"admin panel".as_slice()),
        (r"(?<=token=)secret", b"token=secret".as_slice()),
        (r"admin(?!istrator)", b"admin panel".as_slice()),
        (r"(?<!super)admin", b"plain admin".as_slice()),
    ] {
        let mut config = default_filter_config();
        config.filter_regex = compile_regex(Some(pattern.to_string()), "--filter-regex").unwrap();

        let result = native_http_result(
            "advanced".to_string(),
            200,
            Vec::new(),
            body.to_vec(),
            1.0,
            &config,
        );

        assert!(result.filtered, "pattern did not match: {pattern}");
    }
}

#[test]
fn python_backreferences_execute_in_native_filters() {
    for (pattern, body) in [
        (r"\b([a-z]+)\s+\1\b", b"the the".as_slice()),
        (
            r"\b(?P<word>[a-z]+)\s+(?P=word)\b",
            b"repeat repeat".as_slice(),
        ),
    ] {
        let mut config = default_filter_config();
        config.filter_regex = compile_regex(Some(pattern.to_string()), "--filter-regex").unwrap();

        let result = native_http_result(
            "advanced".to_string(),
            200,
            Vec::new(),
            body.to_vec(),
            1.0,
            &config,
        );

        assert!(result.filtered, "pattern did not match: {pattern}");
    }
}

#[test]
fn python_header_backreferences_remain_case_insensitive() {
    let mut config = default_filter_config();
    config.filter_header_regex = compile_header_regex(
        Some(r"x-token: (?P<value>[a-z]+)-(?P=value)".to_string()),
        "--filter-header-regex",
    )
    .unwrap();

    let result = native_http_result(
        "advanced".to_string(),
        200,
        vec![("X-Token".to_string(), "Secret-secret".to_string())],
        b"body".to_vec(),
        1.0,
        &config,
    );

    assert!(result.filtered);
}

#[test]
fn advanced_regex_backtracking_limit_becomes_a_scan_error() {
    let mut config = default_filter_config();
    config.filter_regex =
        compile_regex(Some(r"^(a|aa)+\1b$".to_string()), "--filter-regex").unwrap();
    let mut body = vec![b'a'; 128];
    body.push(b'c');

    let result = native_http_result("bounded".to_string(), 200, Vec::new(), body, 1.0, &config);

    assert!(result
        .error
        .as_deref()
        .is_some_and(|error| error.contains("backtracking count exceeded")));
    assert!(!result.filtered);
    assert!(result.body.is_empty());
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
    assert!(!result.body_complete);
}

#[test]
fn runtime_workers_follow_available_cpu_bounds() {
    assert!((1..=256).contains(&runtime_worker_count()));
}

#[test]
fn every_supported_proxy_client_configuration_builds() {
    for proxy in [
        "http://user:password@127.0.0.1:8080",
        "https://user:password@127.0.0.1:8443",
        "socks4://127.0.0.1:1080",
        "socks4a://127.0.0.1:1080",
        "socks5://user:password@127.0.0.1:1080",
        "socks5h://user:password@127.0.0.1:1080",
    ] {
        let client = build_http_client(&HeaderMap::new(), 25, 1.0, false, 30, Some(proxy), None);

        assert!(client.is_ok(), "{proxy}");
    }
}

struct PemIdentity {
    certificate: Vec<u8>,
    key: Vec<u8>,
}

struct MutualTlsFixture {
    server_config: Arc<ServerConfig>,
    trusted_client: PemIdentity,
    untrusted_client: PemIdentity,
    wrong_usage_client: PemIdentity,
    expired_client: PemIdentity,
    unrelated_key: Vec<u8>,
}

fn mutual_tls_fixture() -> MutualTlsFixture {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let mut ca_params = CertificateParams::new(Vec::<String>::new()).unwrap();
    ca_params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    ca_params.key_usages = vec![
        KeyUsagePurpose::DigitalSignature,
        KeyUsagePurpose::KeyCertSign,
        KeyUsagePurpose::CrlSign,
    ];
    let ca_key = KeyPair::generate().unwrap();
    let ca_certificate = ca_params.self_signed(&ca_key).unwrap();
    let issuer = Issuer::new(ca_params, ca_key);

    let server_key = KeyPair::generate().unwrap();
    let mut server_params = CertificateParams::new(vec!["localhost".to_string()]).unwrap();
    server_params.key_usages = vec![KeyUsagePurpose::DigitalSignature];
    server_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth];
    let server_certificate = server_params.signed_by(&server_key, &issuer).unwrap();

    let client_key = KeyPair::generate().unwrap();
    let mut client_params = CertificateParams::new(vec!["dirsearch-client".to_string()]).unwrap();
    client_params.key_usages = vec![KeyUsagePurpose::DigitalSignature];
    client_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ClientAuth];
    let client_certificate = client_params.signed_by(&client_key, &issuer).unwrap();

    let unrelated_key = KeyPair::generate().unwrap().serialize_pem().into_bytes();

    let wrong_usage_key = KeyPair::generate().unwrap();
    let mut wrong_usage_params =
        CertificateParams::new(vec!["wrong-usage-client".to_string()]).unwrap();
    wrong_usage_params.key_usages = vec![KeyUsagePurpose::DigitalSignature];
    wrong_usage_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth];
    let wrong_usage_certificate = wrong_usage_params
        .signed_by(&wrong_usage_key, &issuer)
        .unwrap();

    let expired_key = KeyPair::generate().unwrap();
    let mut expired_params = CertificateParams::new(vec!["expired-client".to_string()]).unwrap();
    expired_params.key_usages = vec![KeyUsagePurpose::DigitalSignature];
    expired_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ClientAuth];
    expired_params.not_before = date_time_ymd(2000, 1, 1);
    expired_params.not_after = date_time_ymd(2001, 1, 1);
    let expired_certificate = expired_params.signed_by(&expired_key, &issuer).unwrap();

    let mut untrusted_ca_params = CertificateParams::new(Vec::<String>::new()).unwrap();
    untrusted_ca_params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    untrusted_ca_params.key_usages = vec![
        KeyUsagePurpose::DigitalSignature,
        KeyUsagePurpose::KeyCertSign,
        KeyUsagePurpose::CrlSign,
    ];
    let untrusted_ca_key = KeyPair::generate().unwrap();
    let untrusted_issuer = Issuer::new(untrusted_ca_params, untrusted_ca_key);
    let untrusted_key = KeyPair::generate().unwrap();
    let mut untrusted_params =
        CertificateParams::new(vec!["untrusted-client".to_string()]).unwrap();
    untrusted_params.key_usages = vec![KeyUsagePurpose::DigitalSignature];
    untrusted_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ClientAuth];
    let untrusted_certificate = untrusted_params
        .signed_by(&untrusted_key, &untrusted_issuer)
        .unwrap();

    let mut client_roots = RootCertStore::empty();
    client_roots.add(ca_certificate.der().clone()).unwrap();
    let verifier = WebPkiClientVerifier::builder(Arc::new(client_roots))
        .build()
        .unwrap();
    let server_key_der = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(server_key.serialize_der()));
    let server_config = ServerConfig::builder()
        .with_client_cert_verifier(verifier)
        .with_single_cert(vec![server_certificate.der().clone()], server_key_der)
        .unwrap();

    MutualTlsFixture {
        server_config: Arc::new(server_config),
        trusted_client: PemIdentity {
            certificate: client_certificate.pem().into_bytes(),
            key: client_key.serialize_pem().into_bytes(),
        },
        untrusted_client: PemIdentity {
            certificate: untrusted_certificate.pem().into_bytes(),
            key: untrusted_key.serialize_pem().into_bytes(),
        },
        wrong_usage_client: PemIdentity {
            certificate: wrong_usage_certificate.pem().into_bytes(),
            key: wrong_usage_key.serialize_pem().into_bytes(),
        },
        expired_client: PemIdentity {
            certificate: expired_certificate.pem().into_bytes(),
            key: expired_key.serialize_pem().into_bytes(),
        },
        unrelated_key,
    }
}

async fn run_mutual_tls_request(
    fixture: &MutualTlsFixture,
    client_certificate: &[u8],
    client_key: &[u8],
) -> (NativeHttpResult, Result<(), String>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio_rustls::TlsAcceptor;

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let acceptor = TlsAcceptor::from(fixture.server_config.clone());
    let server = tokio::spawn(async move {
        tokio::time::timeout(Duration::from_secs(3), async move {
            let (stream, _) = listener.accept().await.map_err(|error| error.to_string())?;
            let mut stream = acceptor
                .accept(stream)
                .await
                .map_err(|error| error.to_string())?;
            let mut request = Vec::new();
            loop {
                let mut buffer = [0u8; 1024];
                let read = stream
                    .read(&mut buffer)
                    .await
                    .map_err(|error| error.to_string())?;
                if read == 0 {
                    return Err("client closed before sending a request".to_string());
                }
                request.extend_from_slice(&buffer[..read]);
                if request.windows(4).any(|window| window == b"\r\n\r\n") {
                    break;
                }
            }
            if !request.starts_with(b"GET /mtls HTTP/1.1\r\n") {
                return Err("unexpected mutual TLS request target".to_string());
            }
            stream
                .write_all(OK_RESPONSE)
                .await
                .map_err(|error| error.to_string())?;
            Ok(())
        })
        .await
        .map_err(|_| "mutual TLS fixture timed out".to_string())?
    });

    let client = build_http_client(
        &HeaderMap::new(),
        1,
        2.0,
        false,
        30,
        None,
        (!client_certificate.is_empty() || !client_key.is_empty())
            .then_some((client_certificate, client_key)),
    )
    .unwrap();
    let result = request_with_client(
        &client,
        &format!("https://{address}/mtls"),
        &Method::GET,
        Bytes::new(),
        false,
        0,
        80,
        Instant::now(),
        &default_filter_config(),
        false,
    )
    .await;
    (result, server.await.unwrap())
}

#[test]
fn client_identity_is_required_and_sent_during_tls_handshake() {
    let fixture = mutual_tls_fixture();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();

    let (anonymous_result, anonymous_server) =
        runtime.block_on(run_mutual_tls_request(&fixture, b"", b""));
    assert!(anonymous_result.error.is_some());
    assert!(anonymous_server.is_err());

    let (authenticated_result, authenticated_server) = runtime.block_on(run_mutual_tls_request(
        &fixture,
        &fixture.trusted_client.certificate,
        &fixture.trusted_client.key,
    ));
    authenticated_server.unwrap();
    assert_eq!(authenticated_result.status, 200);
    assert_eq!(authenticated_result.body, b"ok");
}

#[test]
fn malformed_or_incomplete_client_identity_fails_during_client_construction() {
    let fixture = mutual_tls_fixture();
    let encrypted_key =
        b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nYWJj\n-----END ENCRYPTED PRIVATE KEY-----\n";
    let invalid_cases: [(&str, &[u8], &[u8]); 7] = [
        (
            "malformed certificate",
            b"not a certificate",
            &fixture.trusted_client.key,
        ),
        (
            "malformed private key",
            &fixture.trusted_client.certificate,
            b"not a private key",
        ),
        ("missing certificate", b"", &fixture.trusted_client.key),
        (
            "missing private key",
            &fixture.trusted_client.certificate,
            b"",
        ),
        (
            "certificate provided as private key",
            &fixture.trusted_client.certificate,
            &fixture.trusted_client.certificate,
        ),
        (
            "private key provided as certificate",
            &fixture.trusted_client.key,
            &fixture.trusted_client.key,
        ),
        (
            "encrypted private key",
            &fixture.trusted_client.certificate,
            encrypted_key,
        ),
    ];

    for (case, certificate, key) in invalid_cases {
        let error = build_http_client(
            &HeaderMap::new(),
            1,
            2.0,
            false,
            30,
            None,
            Some((certificate, key)),
        )
        .expect_err(case);

        assert!(
            error.contains("Invalid client certificate or private key"),
            "{case}: {error}"
        );
        assert!(!error.contains("not a private key"), "{case}: {error}");
        assert!(!error.contains("YWJj"), "{case}: {error}");
    }
}

#[test]
fn client_certificate_and_unrelated_valid_key_are_rejected() {
    let fixture = mutual_tls_fixture();
    let error = build_http_client(
        &HeaderMap::new(),
        1,
        2.0,
        false,
        30,
        None,
        Some((&fixture.trusted_client.certificate, &fixture.unrelated_key)),
    )
    .expect_err("a certificate paired with another valid key was accepted");

    assert!(
        error.contains("Invalid client certificate or private key"),
        "{error}"
    );
}

#[test]
fn valid_but_unauthorized_client_certificates_fail_the_tls_handshake() {
    let fixture = mutual_tls_fixture();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();

    for (case, identity) in [
        ("untrusted issuer", &fixture.untrusted_client),
        (
            "server-only extended key usage",
            &fixture.wrong_usage_client,
        ),
        ("expired certificate", &fixture.expired_client),
    ] {
        let (result, server) = runtime.block_on(run_mutual_tls_request(
            &fixture,
            &identity.certificate,
            &identity.key,
        ));

        assert!(result.error.is_some(), "{case} was accepted by the client");
        assert!(server.is_err(), "{case} was accepted by the server");
    }
}

#[test]
fn response_length_prefers_content_length_header() {
    assert_eq!(response_length(&content_length(123), 2), 123);
    assert_eq!(response_length(&[], 2), 2);
}
