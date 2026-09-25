//! HTTP content-decoding adapters shared by the async and raw transports.

use async_compression::tokio::bufread::{
    BrotliDecoder as AsyncBrotliDecoder, GzipDecoder as AsyncGzipDecoder,
    ZlibDecoder as AsyncZlibDecoder, ZstdDecoder as AsyncZstdDecoder,
};
use brotli::Decompressor;
use flate2::read::{GzDecoder, ZlibDecoder};
use std::fmt::Display;
use std::io::Read;
use std::pin::Pin;
use tokio::io::{AsyncRead, BufReader as AsyncBufReader};
use zstd::stream::read::Decoder as ZstdDecoder;

pub(crate) type AsyncBodyReader = Pin<Box<dyn AsyncRead + Send>>;

pub(crate) fn decode_sync(
    mut reader: Box<dyn Read>,
    encodings: &[String],
) -> Result<Box<dyn Read>, String> {
    for encoding in encodings.iter().rev() {
        reader = if encoding.eq_ignore_ascii_case("identity") {
            reader
        } else if encoding.eq_ignore_ascii_case("gzip") {
            Box::new(GzDecoder::new(reader))
        } else if encoding.eq_ignore_ascii_case("deflate") {
            Box::new(ZlibDecoder::new(reader))
        } else if encoding.eq_ignore_ascii_case("br") {
            Box::new(Decompressor::new(reader, 4096))
        } else if encoding.eq_ignore_ascii_case("zstd") {
            Box::new(
                ZstdDecoder::new(reader)
                    .map_err(|error| decode_error(std::slice::from_ref(encoding), error))?,
            )
        } else {
            return Err(format!("Unsupported HTTP Content-Encoding: {encoding}"));
        };
    }
    Ok(reader)
}

pub(crate) fn decode_async(
    mut reader: AsyncBodyReader,
    encodings: &[String],
) -> Result<AsyncBodyReader, String> {
    for encoding in encodings.iter().rev() {
        if encoding.eq_ignore_ascii_case("identity") {
            continue;
        }

        let buffered = AsyncBufReader::new(reader);
        reader = if encoding.eq_ignore_ascii_case("gzip") {
            Box::pin(AsyncGzipDecoder::new(buffered))
        } else if encoding.eq_ignore_ascii_case("deflate") {
            Box::pin(AsyncZlibDecoder::new(buffered))
        } else if encoding.eq_ignore_ascii_case("br") {
            Box::pin(AsyncBrotliDecoder::new(buffered))
        } else if encoding.eq_ignore_ascii_case("zstd") {
            Box::pin(AsyncZstdDecoder::new(buffered))
        } else {
            return Err(format!("Unsupported HTTP Content-Encoding: {encoding}"));
        };
    }
    Ok(reader)
}

pub(crate) fn decode_error(encodings: &[String], error: impl Display) -> String {
    if encodings.is_empty() {
        error.to_string()
    } else {
        format!(
            "Failed to decode {} response body: {error}",
            encodings.join(", ")
        )
    }
}
