use brotli::Decompressor;
use flate2::read::{GzDecoder, ZlibDecoder};
use std::io::{self, BufReader, Read, Write};
use std::net::{Shutdown, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

const MAX_HEADER_SIZE: usize = 64 * 1024;
const MAX_CHUNK_LINE_SIZE: usize = 8 * 1024;
const IO_POLL_INTERVAL: Duration = Duration::from_millis(50);

pub(crate) type HeaderPairs = Vec<(String, String)>;
pub(crate) type Response = (u16, HeaderPairs, Vec<u8>, usize);

pub(crate) struct ShutdownOnDrop {
    stream: Option<TcpStream>,
}

impl ShutdownOnDrop {
    pub(crate) fn new(stream: TcpStream) -> Self {
        Self {
            stream: Some(stream),
        }
    }

    pub(crate) fn disarm(&mut self) {
        self.stream = None;
    }
}

impl Drop for ShutdownOnDrop {
    fn drop(&mut self) {
        if let Some(stream) = self.stream.take() {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

pub(crate) fn exchange(
    mut stream: TcpStream,
    request: &[u8],
    deadline: Instant,
    cancelled: Arc<AtomicBool>,
    max_body_size: usize,
) -> Result<Response, String> {
    write_all(&mut stream, request, deadline, cancelled.as_ref())
        .map_err(|error| format!("Raw HTTP request write failed: {error}"))?;
    let reader = DeadlineReader {
        stream,
        deadline,
        cancelled,
    };
    parse_response(reader, max_body_size)
}

pub(crate) fn parse_response<R: Read + 'static>(
    reader: R,
    max_body_size: usize,
) -> Result<Response, String> {
    let mut reader = BufReader::new(reader);
    let mut informational_responses = 0usize;
    let (status, headers) = loop {
        let response = read_head(&mut reader)?;
        if (100..200).contains(&response.0) && response.0 != 101 {
            informational_responses += 1;
            if informational_responses > 8 {
                return Err("HTTP response contained too many informational responses".to_string());
            }
            continue;
        }
        break response;
    };

    if status == 101 || status == 204 || status == 304 {
        return Ok((status, headers, Vec::new(), 0));
    }

    let content_length = content_length(&headers)?;
    let transfer_codings = comma_separated_header_values(&headers, "transfer-encoding");
    let framing = if transfer_codings.is_empty() {
        match content_length {
            Some(length) => BodyReader::fixed(reader, length),
            None => BodyReader::close_delimited(reader),
        }
    } else {
        if content_length.is_some() {
            return Err(
                "HTTP response contains both Transfer-Encoding and Content-Length".to_string(),
            );
        }
        if transfer_codings.len() != 1 || !transfer_codings[0].eq_ignore_ascii_case("chunked") {
            return Err(format!(
                "Unsupported HTTP Transfer-Encoding: {}",
                transfer_codings.join(", ")
            ));
        }
        BodyReader::chunked(reader)
    };

    let encodings = comma_separated_header_values(&headers, "content-encoding");
    let mut decoded: Box<dyn Read> = Box::new(framing);
    for encoding in encodings.iter().rev() {
        decoded = if encoding.eq_ignore_ascii_case("identity") {
            decoded
        } else if encoding.eq_ignore_ascii_case("gzip") {
            Box::new(GzDecoder::new(decoded))
        } else if encoding.eq_ignore_ascii_case("deflate") {
            Box::new(ZlibDecoder::new(decoded))
        } else if encoding.eq_ignore_ascii_case("br") {
            Box::new(Decompressor::new(decoded, 4096))
        } else {
            return Err(format!("Unsupported HTTP Content-Encoding: {encoding}"));
        };
    }
    let (body, decoded_length) = collect_body(decoded, max_body_size).map_err(|error| {
        if encodings.is_empty() {
            error
        } else {
            format!(
                "Failed to decode {} response body: {error}",
                encodings.join(", ")
            )
        }
    })?;

    Ok((status, headers, body, decoded_length))
}

fn read_head<R: Read>(reader: &mut R) -> Result<(u16, HeaderPairs), String> {
    let status_line = read_crlf_line(reader, MAX_HEADER_SIZE, "HTTP status line")?;
    let status_text = std::str::from_utf8(&status_line)
        .map_err(|_| "HTTP response status line is not valid UTF-8".to_string())?;
    let mut status_parts = status_text.split_whitespace();
    let version = status_parts
        .next()
        .ok_or_else(|| "HTTP response did not contain a status line".to_string())?;
    if !version.starts_with("HTTP/") {
        return Err("HTTP response status line did not start with HTTP/".to_string());
    }
    let status = status_parts
        .next()
        .ok_or_else(|| "HTTP response status line did not contain a status code".to_string())?
        .parse::<u16>()
        .map_err(|error| error.to_string())?;

    let mut total_size = status_line.len() + 2;
    let mut headers = Vec::new();
    loop {
        let remaining = MAX_HEADER_SIZE.saturating_sub(total_size);
        if remaining < 2 {
            return Err(format!(
                "HTTP response headers exceeded {MAX_HEADER_SIZE} bytes"
            ));
        }
        let line = read_crlf_line(reader, remaining, "HTTP header line")?;
        total_size = total_size.saturating_add(line.len() + 2);
        if line.is_empty() {
            break;
        }
        if matches!(line.first(), Some(b' ' | b'\t')) {
            return Err("Obsolete folded HTTP response headers are not supported".to_string());
        }
        let colon = line
            .iter()
            .position(|byte| *byte == b':')
            .ok_or_else(|| "HTTP response header did not contain a colon".to_string())?;
        let name = std::str::from_utf8(&line[..colon])
            .map_err(|_| "HTTP response header name is not valid ASCII".to_string())?;
        if name.is_empty() {
            return Err("HTTP response header name is empty".to_string());
        }
        if !name.is_ascii() {
            return Err("HTTP response header name is not valid ASCII".to_string());
        }
        let value = String::from_utf8_lossy(&line[colon + 1..]);
        headers.push((name.to_string(), value.trim().to_string()));
    }

    Ok((status, headers))
}

fn content_length(headers: &HeaderPairs) -> Result<Option<usize>, String> {
    let values = comma_separated_header_values(headers, "content-length");
    if values.is_empty() {
        return Ok(None);
    }

    let mut parsed = values.iter().map(|value| {
        value
            .parse::<usize>()
            .map_err(|_| format!("Invalid HTTP Content-Length: {value}"))
    });
    let expected = parsed
        .next()
        .expect("content length values are not empty")?;
    for value in parsed {
        if value? != expected {
            return Err("HTTP response contains conflicting Content-Length values".to_string());
        }
    }
    Ok(Some(expected))
}

pub(crate) fn comma_separated_header_values(
    headers: &HeaderPairs,
    wanted_name: &str,
) -> Vec<String> {
    headers
        .iter()
        .filter(|(name, _)| name.eq_ignore_ascii_case(wanted_name))
        .flat_map(|(_, value)| value.split(','))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect()
}

fn collect_body<R: Read>(mut reader: R, max_body_size: usize) -> Result<(Vec<u8>, usize), String> {
    let mut body = Vec::with_capacity(max_body_size.min(8192));
    let mut decoded_length = 0usize;
    let mut buffer = [0u8; 8192];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| error.to_string())?;
        if read == 0 {
            break;
        }
        decoded_length = decoded_length
            .checked_add(read)
            .ok_or_else(|| "HTTP response body length overflowed usize".to_string())?;
        let remaining = max_body_size.saturating_sub(body.len());
        body.extend_from_slice(&buffer[..read.min(remaining)]);
    }
    Ok((body, decoded_length))
}

enum BodyReader<R> {
    Empty,
    Fixed {
        reader: R,
        remaining: usize,
    },
    CloseDelimited(R),
    Chunked {
        reader: R,
        chunk_remaining: usize,
        finished: bool,
    },
}

impl<R> BodyReader<R> {
    fn fixed(reader: R, remaining: usize) -> Self {
        if remaining == 0 {
            Self::Empty
        } else {
            Self::Fixed { reader, remaining }
        }
    }

    fn close_delimited(reader: R) -> Self {
        Self::CloseDelimited(reader)
    }

    fn chunked(reader: R) -> Self {
        Self::Chunked {
            reader,
            chunk_remaining: 0,
            finished: false,
        }
    }
}

impl<R: Read> Read for BodyReader<R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        match self {
            Self::Empty => Ok(0),
            Self::CloseDelimited(reader) => reader.read(output),
            Self::Fixed { reader, remaining } => {
                if *remaining == 0 {
                    return Ok(0);
                }
                let read_size = output.len().min(*remaining);
                let read = reader.read(&mut output[..read_size])?;
                if read == 0 {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "HTTP response ended before Content-Length bytes were received",
                    ));
                }
                *remaining -= read;
                Ok(read)
            }
            Self::Chunked {
                reader,
                chunk_remaining,
                finished,
            } => {
                if *finished {
                    return Ok(0);
                }
                if *chunk_remaining == 0 {
                    let line = read_crlf_line(reader, MAX_CHUNK_LINE_SIZE, "HTTP chunk size")
                        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
                    let size_text = std::str::from_utf8(
                        line.split(|byte| *byte == b';').next().unwrap_or_default(),
                    )
                    .map_err(|_| {
                        io::Error::new(io::ErrorKind::InvalidData, "HTTP chunk size is not UTF-8")
                    })?
                    .trim();
                    if size_text.is_empty() {
                        return Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "HTTP chunked body contains an empty chunk size",
                        ));
                    }
                    *chunk_remaining = usize::from_str_radix(size_text, 16).map_err(|_| {
                        io::Error::new(
                            io::ErrorKind::InvalidData,
                            "HTTP chunked body contains an invalid chunk size",
                        )
                    })?;
                    if *chunk_remaining == 0 {
                        read_trailers(reader)?;
                        *finished = true;
                        return Ok(0);
                    }
                }

                let read_size = output.len().min(*chunk_remaining);
                let read = reader.read(&mut output[..read_size])?;
                if read == 0 {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "HTTP response ended inside a chunked body",
                    ));
                }
                *chunk_remaining -= read;
                if *chunk_remaining == 0 {
                    let mut terminator = [0u8; 2];
                    reader.read_exact(&mut terminator).map_err(|error| {
                        io::Error::new(
                            error.kind(),
                            format!("HTTP response ended inside a chunked body: {error}"),
                        )
                    })?;
                    if terminator != *b"\r\n" {
                        return Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "HTTP chunked body is missing a chunk terminator",
                        ));
                    }
                }
                Ok(read)
            }
        }
    }
}

fn read_trailers<R: Read>(reader: &mut R) -> io::Result<()> {
    let mut total_size = 0usize;
    loop {
        let remaining = MAX_HEADER_SIZE.saturating_sub(total_size);
        if remaining < 2 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("HTTP response trailers exceeded {MAX_HEADER_SIZE} bytes"),
            ));
        }
        let line = read_crlf_line(reader, remaining, "HTTP trailer")
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        total_size = total_size.saturating_add(line.len() + 2);
        if line.is_empty() {
            return Ok(());
        }
        if !line.contains(&b':') {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "HTTP trailer did not contain a colon",
            ));
        }
    }
}

fn read_crlf_line<R: Read>(reader: &mut R, limit: usize, context: &str) -> Result<Vec<u8>, String> {
    let mut line = Vec::new();
    let mut byte = [0u8; 1];
    loop {
        let read = reader.read(&mut byte).map_err(|error| error.to_string())?;
        if read == 0 {
            return Err(format!("HTTP response ended before {context} was complete"));
        }
        line.push(byte[0]);
        if line.len() > limit {
            return Err(format!("{context} exceeded {limit} bytes"));
        }
        if byte[0] == b'\n' {
            if line.len() < 2 || line[line.len() - 2] != b'\r' {
                return Err(format!("{context} did not end with CRLF"));
            }
            line.truncate(line.len() - 2);
            return Ok(line);
        }
    }
}

struct DeadlineReader {
    stream: TcpStream,
    deadline: Instant,
    cancelled: Arc<AtomicBool>,
}

impl Read for DeadlineReader {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        loop {
            let timeout = remaining_poll_timeout(self.deadline, self.cancelled.as_ref())?;
            self.stream.set_read_timeout(Some(timeout))?;
            match self.stream.read(output) {
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
                    ) =>
                {
                    continue;
                }
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                result => return result,
            }
        }
    }
}

fn write_all(
    stream: &mut TcpStream,
    mut data: &[u8],
    deadline: Instant,
    cancelled: &AtomicBool,
) -> io::Result<()> {
    while !data.is_empty() {
        let timeout = remaining_poll_timeout(deadline, cancelled)?;
        stream.set_write_timeout(Some(timeout))?;
        match stream.write(data) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "failed to write the raw HTTP request",
                ));
            }
            Ok(written) => data = &data[written..],
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
                ) => {}
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn remaining_poll_timeout(deadline: Instant, cancelled: &AtomicBool) -> io::Result<Duration> {
    if cancelled.load(Ordering::Acquire) {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "raw HTTP request was cancelled",
        ));
    }
    let remaining = deadline
        .checked_duration_since(Instant::now())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "raw HTTP request timed out"))?;
    if remaining.is_zero() {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "raw HTTP request timed out",
        ));
    }
    Ok(remaining.min(IO_POLL_INTERVAL))
}
