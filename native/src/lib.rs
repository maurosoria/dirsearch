use indexmap::IndexSet;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rayon::prelude::*;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use std::fs;
use std::time::Instant;

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
    headers: Vec<(String, String)>,
    #[pyo3(get)]
    body: Vec<u8>,
}

#[pyfunction]
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
#[pyo3(signature = (
    base_url,
    paths,
    concurrency=25,
    timeout_secs=7.5,
    headers=Vec::new(),
    max_retries=0,
    follow_redirects=false,
    max_body_size=83886080,
))]
fn scan_http(
    py: Python<'_>,
    base_url: String,
    paths: Vec<String>,
    concurrency: usize,
    timeout_secs: f64,
    headers: Vec<(String, String)>,
    max_retries: usize,
    follow_redirects: bool,
    max_body_size: usize,
) -> PyResult<Vec<NativeHttpResult>> {
    py.allow_threads(move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(concurrency.clamp(1, 256))
            .build()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        runtime.block_on(async move {
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
                let semaphore = semaphore.clone();
                tasks.push(tokio::spawn(async move {
                    let _permit = match semaphore.acquire_owned().await {
                        Ok(permit) => permit,
                        Err(error) => {
                            return NativeHttpResult {
                                path,
                                status: 0,
                                length: 0,
                                elapsed_ms: 0.0,
                                error: Some(error.to_string()),
                                headers: Vec::new(),
                                body: Vec::new(),
                            };
                        }
                    };
                    let url = format!("{base_url}{path}");
                    let start = Instant::now();
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
                            return NativeHttpResult {
                                path,
                                status: 0,
                                length: 0,
                                elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                                error: last_error,
                                headers: Vec::new(),
                                body: Vec::new(),
                            };
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
                            return NativeHttpResult {
                                path,
                                status,
                                length: 0,
                                elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                                error: Some(error.to_string()),
                                headers,
                                body: Vec::new(),
                            };
                        }
                    };
                    let length = body.len();
                    let body = body[..length.min(max_body_size)].to_vec();
                    NativeHttpResult {
                        path,
                        status,
                        length,
                        elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                        error: None,
                        headers,
                        body,
                    }
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

#[pymodule]
fn dirsearch_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(generate_wordlist, module)?)?;
    module.add_function(wrap_pyfunction!(scan_http, module)?)?;
    module.add_class::<NativeHttpResult>()?;
    Ok(())
}
