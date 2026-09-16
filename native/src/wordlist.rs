//! Parallel wordlist loading and deterministic entry expansion.

use indexmap::IndexSet;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use rayon::prelude::*;
use std::fs;

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
pub(crate) fn generate_wordlist(
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
