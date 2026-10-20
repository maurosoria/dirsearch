//! Content operations with Python's existing normalization and difflib semantics.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::bytes::{Regex, RegexBuilder};
use std::borrow::Cow;
use std::collections::HashMap;
use std::collections::HashSet;
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

pub(crate) fn normalize_ascii(content: &str) -> String {
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

trait MatchPositions<T> {
    fn indices(&self, element: &T) -> Option<&[usize]>;
}

impl<T: Eq + Hash> MatchPositions<T> for HashMap<T, Vec<usize>> {
    fn indices(&self, element: &T) -> Option<&[usize]> {
        self.get(element).map(Vec::as_slice)
    }
}

impl MatchPositions<u8> for [Vec<usize>; 128] {
    fn indices(&self, element: &u8) -> Option<&[usize]> {
        Some(&self[*element as usize])
    }
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
        positions: &impl MatchPositions<T>,
        bounds: (usize, usize, usize, usize),
    ) -> (usize, usize, usize) {
        let (first_start, first_end, second_start, second_end) = bounds;
        let (mut best_a, mut best_b, mut best_size) = (first_start, second_start, 0);
        // Leave an unused generation between separate subrange searches.
        self.row += 1;
        for (i, element) in a.iter().enumerate().take(first_end).skip(first_start) {
            self.row += 1;
            if let Some(indices) = positions.indices(element) {
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

pub(crate) fn sequence_ratio<T: Copy + Eq + Hash>(a: &[T], b: &[T]) -> f64 {
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
    ratio_with_positions(a, b, &positions)
}

pub(crate) fn sequence_ascii_ratio(a: &[u8], b: &[u8]) -> f64 {
    if a == b {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let mut counts = [0usize; 128];
    for &element in b {
        counts[element as usize] += 1;
    }
    let maximum = if b.len() >= 200 {
        b.len() / 100 + 1
    } else {
        usize::MAX
    };
    let mut positions: [Vec<usize>; 128] = std::array::from_fn(|_| Vec::new());
    for (j, &element) in b.iter().enumerate() {
        if counts[element as usize] <= maximum {
            positions[element as usize].push(j);
        }
    }
    ratio_with_positions(a, b, &positions)
}

fn ratio_with_positions<T: Copy + Eq + Hash>(
    a: &[T],
    b: &[T],
    positions: &impl MatchPositions<T>,
) -> f64 {
    let mut scratch = MatchScratch::new(b.len());
    let mut queue = vec![(0, a.len(), 0, b.len())];
    let mut matches = 0;
    while let Some(bounds @ (first_start, first_end, second_start, second_end)) = queue.pop() {
        let (i, j, size) = scratch.longest(a, b, positions, bounds);
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
            sequence_ascii_ratio(first.as_bytes(), second.as_bytes())
        } else {
            // Python str compares Unicode code points rather than UTF-8 bytes.
            sequence_ratio(
                &first.chars().collect::<Vec<_>>(),
                &second.chars().collect::<Vec<_>>(),
            )
        }
    })
}

fn static_patterns(first: &str, second: &str) -> Option<Vec<String>> {
    let split = |c: char| c.is_ascii_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c);
    let a: Vec<_> = first.split(split).filter(|s| !s.is_empty()).collect();
    let b: Vec<_> = second.split(split).filter(|s| !s.is_empty()).collect();
    let mut positions: HashMap<&str, Vec<usize>> = HashMap::new();
    for (j, &word) in b.iter().enumerate() {
        positions.entry(word).or_default().push(j);
    }
    if b.len() >= 200 {
        let maximum = b.len() / 100 + 1;
        positions.retain(|_, indices| indices.len() <= maximum);
    }
    let mut scratch = MatchScratch::new(b.len());
    let mut queue = vec![(0, a.len(), 0, b.len())];
    let mut blocks = Vec::new();
    while let Some(bounds @ (a_start, a_end, b_start, b_end)) = queue.pop() {
        let (i, j, size) = scratch.longest(&a, &b, &positions, bounds);
        if size == 0 {
            continue;
        }
        blocks.push((i, j, size));
        if a_start < i && b_start < j {
            queue.push((a_start, i, b_start, j));
        }
        if i + size < a_end && j + size < b_end {
            queue.push((i + size, a_end, j + size, b_end));
        }
    }
    blocks.sort_unstable();
    blocks.push((a.len(), b.len(), 0));
    let (mut previous_a, mut previous_b) = (0, 0);
    let mut patterns = Vec::new();
    for (i, j, size) in blocks {
        if previous_a < i && previous_b < j {
            let replaced: HashSet<_> = a[previous_a..i].iter().copied().collect();
            if b[previous_b..j].iter().any(|word| replaced.contains(word)) {
                fancy_patterns(&a, previous_a, i, &b, previous_b, j, &mut patterns);
            }
        }
        patterns.extend(a[i..i + size].iter().map(|word| (*word).to_string()));
        previous_a = i + size;
        previous_b = j + size;
    }
    Some(patterns)
}

// Python 3.14 Differ uses a bounded, non-recursive window for replacement
// synchronization. Split words contain no spaces/tabs, so charjunk is empty.
fn fancy_patterns(
    a: &[&str],
    alo: usize,
    ahi: usize,
    b: &[&str],
    blo: usize,
    bhi: usize,
    patterns: &mut Vec<String>,
) {
    let mut dump_i = alo;
    for (j, second) in b.iter().enumerate().take(bhi).skip(blo) {
        let equivalent = alo + j - blo;
        let start = equivalent.saturating_sub(10).max(dump_i);
        let end = (equivalent + 11).min(ahi);
        if start >= end {
            break;
        }
        let mut best = None;
        let mut best_ratio = 0.74999;
        for (i, first) in a.iter().enumerate().take(end).skip(start) {
            let total = first.len() + second.len();
            if total > 0 && 2.0 * first.len().min(second.len()) as f64 / total as f64 <= best_ratio
            {
                continue;
            }
            let ratio = sequence_ratio(first.as_bytes(), second.as_bytes());
            if ratio > best_ratio {
                best = Some(i);
                best_ratio = ratio;
            }
        }
        if let Some(i) = best {
            if a[i] == *second {
                patterns.push(a[i].to_string());
            }
            dump_i = i + 1;
        }
    }
}

#[pyfunction]
pub(crate) fn static_ascii_patterns(
    py: Python<'_>,
    first: &str,
    second: &str,
) -> PyResult<Option<Vec<String>>> {
    if !first.is_ascii() || !second.is_ascii() {
        return Err(PyValueError::new_err("ASCII content required"));
    }
    Ok(py.detach(|| static_patterns(first, second)))
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
    fn ascii_tables_preserve_generic_matching_at_autojunk_boundaries() {
        for length in [0, 1, 2, 198, 199, 200, 201, 300, 1000] {
            let a: Vec<_> = (0u8..128).cycle().take(length).collect();
            let b: Vec<_> = std::iter::once(b'x')
                .chain(a.iter().copied().rev())
                .collect();
            assert_eq!(sequence_ascii_ratio(&a, &b), sequence_ratio(&a, &b));
            assert_eq!(sequence_ascii_ratio(&b, &a), sequence_ratio(&b, &a));
        }
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
