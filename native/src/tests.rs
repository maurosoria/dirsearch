//! Cross-module regression tests for the native backend contract.

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
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
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
fn non_utf8_text_filters_are_deferred_to_python() {
    let mut config = default_filter_config();
    config.match_regex = Some(Regex::new("£").unwrap());
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
    config.filter_regex = Some(Regex::new("£").unwrap());

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
    assert!(!result.body_complete);
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
