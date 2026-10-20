//! Content operations with Python's existing normalization and difflib semantics.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::bytes::{Regex, RegexBuilder};
use std::borrow::Cow;
use std::collections::HashMap;
use std::hash::Hash;
use std::sync::LazyLock;

static NORMALIZERS: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
    [
        (r#"(?i)\b(?:nonce|csrf|token|request[_-]?id|trace[_-]?id|session[_-]?id)=["'][^"']+["']"#, "__DYNAMIC_ATTR__"),
        (r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "__DYNAMIC__"),
        (r"(?i)\b[0-9a-f]{16,}\b", "__DYNAMIC__"),
        (r"\b[A-Za-z0-9+/]{24,}={0,2}\b", "__DYNAMIC__"),
        (r"\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+Z?)?\b", "__DYNAMIC__"),
        (r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b", "__DYNAMIC__"),
        (r"\b\d{6,}\b", "__DYNAMIC__"),
    ]
    .into_iter()
    .map(|(pattern, replacement)| {
        (RegexBuilder::new(pattern).unicode(false).build().expect("static content pattern"), replacement)
    })
    .collect()
});

fn normalize_ascii(content: &str) -> String {
    let mut normalized = Cow::Borrowed(content.as_bytes());
    for (regex, replacement) in NORMALIZERS.iter() {
        // A pass without a match borrows the previous text without copying it.
        if let Cow::Owned(replaced) = regex.replace_all(normalized.as_ref(), replacement.as_bytes())
        {
            normalized = Cow::Owned(replaced);
        }
    }
    let mut result = Vec::with_capacity(normalized.len());
    for word in normalized.split(|c| matches!(c, b'\t'..=b'\r' | b'\x1c'..=b' ')) {
        if !word.is_empty() {
            if !result.is_empty() {
                result.push(b' ');
            }
            result.extend_from_slice(word);
        }
    }
    String::from_utf8(result).expect("ASCII normalization")
}

/// Non-ASCII text keeps Python's Unicode regex and whitespace definitions.
#[pyfunction]
pub(crate) fn normalize_ascii_content(py: Python<'_>, content: &str) -> PyResult<String> {
    if !content.is_ascii() {
        return Err(PyValueError::new_err("ASCII content required"));
    }
    Ok(py.detach(|| normalize_ascii(content)))
}

struct MatchScratch {
    lengths: Vec<usize>,
    rows: Vec<usize>,
    row: usize,
}

impl MatchScratch {
    fn new(size: usize) -> Self {
        Self {
            lengths: vec![0; size],
            rows: vec![0; size],
            row: 0,
        }
    }

    fn longest<T: Copy + Eq + Hash>(
        &mut self,
        a: &[T],
        b: &[T],
        positions: &HashMap<T, Vec<usize>>,
        bounds: (usize, usize, usize, usize),
    ) -> (usize, usize, usize) {
        let (first_start, first_end, second_start, second_end) = bounds;
        let (mut best_a, mut best_b, mut best_size) = (first_start, second_start, 0);
        // Leave an unused generation between separate subrange searches.
        self.row += 1;
        for (i, element) in a.iter().enumerate().take(first_end).skip(first_start) {
            self.row += 1;
            if let Some(indices) = positions.get(element) {
                // Descending positions keep the previous row at j - 1 intact.
                for &j in indices.iter().rev() {
                    if j >= second_end {
                        continue;
                    }
                    if j < second_start {
                        break;
                    }
                    let size = if j > 0 && self.rows[j - 1] == self.row - 1 {
                        self.lengths[j - 1] + 1
                    } else {
                        1
                    };
                    self.lengths[j] = size;
                    self.rows[j] = self.row;
                    let start_a = i + 1 - size;
                    let start_b = j + 1 - size;
                    if size > best_size
                        || (size == best_size && (start_a, start_b) < (best_a, best_b))
                    {
                        (best_a, best_b, best_size) = (start_a, start_b, size);
                    }
                }
            }
        }
        // With isjunk=None, popular elements may extend a discovered block.
        while best_a > first_start && best_b > second_start && a[best_a - 1] == b[best_b - 1] {
            best_a -= 1;
            best_b -= 1;
            best_size += 1;
        }
        while best_a + best_size < first_end
            && best_b + best_size < second_end
            && a[best_a + best_size] == b[best_b + best_size]
        {
            best_size += 1;
        }
        (best_a, best_b, best_size)
    }
}

fn sequence_ratio<T: Copy + Eq + Hash>(a: &[T], b: &[T]) -> f64 {
    if a == b {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let mut positions: HashMap<T, Vec<usize>> = HashMap::new();
    for (j, &element) in b.iter().enumerate() {
        positions.entry(element).or_default().push(j);
    }
    // difflib's default autojunk examines the second sequence only.
    if b.len() >= 200 {
        let maximum = b.len() / 100 + 1;
        positions.retain(|_, indices| indices.len() <= maximum);
    }
    let mut scratch = MatchScratch::new(b.len());
    let mut queue = vec![(0, a.len(), 0, b.len())];
    let mut matches = 0;
    while let Some(bounds @ (first_start, first_end, second_start, second_end)) = queue.pop() {
        let (i, j, size) = scratch.longest(a, b, &positions, bounds);
        if size == 0 {
            continue;
        }
        matches += size;
        if first_start < i && second_start < j {
            queue.push((first_start, i, second_start, j));
        }
        if i + size < first_end && j + size < second_end {
            queue.push((i + size, first_end, j + size, second_end));
        }
    }
    2.0 * matches as f64 / (a.len() + b.len()) as f64
}

#[pyfunction]
pub(crate) fn sequence_matcher_ratio(py: Python<'_>, first: &str, second: &str) -> f64 {
    py.detach(|| {
        if first.is_ascii() && second.is_ascii() {
            sequence_ratio(first.as_bytes(), second.as_bytes())
        } else {
            // Python str compares Unicode code points rather than UTF-8 bytes.
            sequence_ratio(
                &first.chars().collect::<Vec<_>>(),
                &second.chars().collect::<Vec<_>>(),
            )
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ratio_preserves_argument_order() {
        assert_eq!(sequence_ratio(b"tide", b"diet"), 0.25);
        assert_eq!(sequence_ratio(b"diet", b"tide"), 0.5);
        assert_eq!(sequence_ratio(b"", b""), 1.0);
        assert_eq!(sequence_ratio(b"", b"x"), 0.0);
    }

    #[test]
    fn normalization_preserves_python_ascii_whitespace() {
        assert_eq!(normalize_ascii("\x1c alpha\t beta\x1f\n"), "alpha beta");
        assert_eq!(
            normalize_ascii("nonce='abc' 123456 2026-10-20"),
            "__DYNAMIC_ATTR__ __DYNAMIC__ __DYNAMIC__"
        );
    }
}
