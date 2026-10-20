//! Stateless wildcard work runs on HTTP workers; observations commit in input order.
use crate::content::{normalize_ascii, sequence_ratio};
use crate::result::NativeHttpResult;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{Arc, Mutex};

#[derive(Clone, Eq, PartialEq, Hash)]
struct Fingerprint {
    status: u16,
    media_type: String,
    redirect: String,
    length: usize,
    digest: [u8; 32],
}

impl Fingerprint {
    fn new(status: u16, media_type: String, redirect: String, content: &str) -> Self {
        Self {
            status,
            media_type,
            redirect,
            length: content.chars().count(),
            digest: Sha256::digest(content.as_bytes()).into(),
        }
    }
}

#[derive(Default)]
struct Observations {
    counts: HashMap<Fingerprint, usize>,
    learned: HashSet<Fingerprint>,
    learned_statuses: HashSet<u16>,
    pending: BTreeMap<usize, NativeObservation>,
}

#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct NativeCalibrationState {
    inner: Arc<Mutex<Observations>>,
    threshold: usize,
}

impl NativeCalibrationState {
    fn observe_key(&self, key: Fingerprint, record: bool) -> bool {
        let mut state = self.inner.lock().unwrap_or_else(|error| error.into_inner());
        Self::record(&mut state, key, record, self.threshold)
    }

    fn record(state: &mut Observations, key: Fingerprint, record: bool, threshold: usize) -> bool {
        if state.learned.contains(&key) {
            return true;
        }
        if !record {
            return false;
        }
        let count = state.counts.entry(key.clone()).or_default();
        *count += 1;
        if *count < threshold {
            return false;
        }
        state.learned_statuses.insert(key.status);
        state.learned.insert(key);
        true
    }
}

#[pymethods]
impl NativeCalibrationState {
    #[new]
    #[pyo3(signature = (auto_calibration=false))]
    fn new(auto_calibration: bool) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Observations::default())),
            threshold: if auto_calibration { 3 } else { 8 },
        }
    }

    fn observe(
        &self,
        status: u16,
        media_type: String,
        redirect: String,
        content: &str,
        record: bool,
    ) -> bool {
        self.observe_key(
            Fingerprint::new(status, media_type, redirect, content),
            record,
        )
    }

    fn is_learned(&self, status: u16, media_type: String, redirect: String, content: &str) -> bool {
        self.inner
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .learned
            .contains(&Fingerprint::new(status, media_type, redirect, content))
    }

    fn has_learned_status(&self, status: u16) -> bool {
        self.inner
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .learned_statuses
            .contains(&status)
    }

    fn commit_range(&self, start: usize, end: usize) {
        if start >= end {
            return;
        }
        let mut state = self.inner.lock().unwrap_or_else(|error| error.into_inner());
        while let Some((&index, _)) = state.pending.range(start..end).next() {
            let observation = state.pending.remove(&index).expect("observed pending key");
            Self::record(
                &mut state,
                observation.key,
                observation.record,
                self.threshold,
            );
        }
    }
}

#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct NativeWildcardProfile {
    status: u16,
    media_type: String,
    base_content: String,
    samples: Vec<String>,
    patterns: Vec<String>,
    is_static: bool,
    ambiguous: bool,
    base_length: usize,
    base_words: usize,
    selection: String,
    selector: String,
}

#[pymethods]
impl NativeWildcardProfile {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        status: u16,
        media_type: String,
        base_content: String,
        samples: Vec<String>,
        patterns: Vec<String>,
        is_static: bool,
        ambiguous: bool,
        base_length: usize,
        selection: String,
        selector: String,
    ) -> PyResult<Self> {
        if samples.is_empty()
            || !base_content.is_ascii()
            || samples
                .iter()
                .chain(patterns.iter())
                .any(|text| !text.is_ascii())
        {
            return Err(PyValueError::new_err(
                "Wildcard profiles require ASCII samples",
            ));
        }
        let base_words = words(&base_content).count();
        Ok(Self {
            status,
            media_type,
            base_content,
            samples,
            patterns,
            is_static,
            ambiguous,
            base_length,
            base_words,
            selection,
            selector,
        })
    }

    fn compare(&self, content: &str, normalized: &str) -> PyResult<bool> {
        if !content.is_ascii() || !normalized.is_ascii() {
            return Err(PyValueError::new_err("ASCII candidate required"));
        }
        Ok(self.matches_content(content, normalized))
    }
}

impl NativeWildcardProfile {
    fn matches_content(&self, content: &str, normalized: &str) -> bool {
        if self.is_static {
            return content == self.base_content
                || self.samples.first().is_some_and(|base| base == normalized);
        }
        if self.patterns.is_empty() {
            return self.samples.iter().any(|sample| sample == normalized);
        }
        let candidate: Vec<_> = words(normalized).collect();
        let mut next = 0;
        let mut misses = 0;
        for pattern in &self.patterns {
            if let Some(offset) = candidate[next..].iter().position(|word| *word == pattern) {
                next += offset + 1;
            } else {
                if misses > 0 || self.patterns.len() < 20 {
                    return false;
                }
                misses += 1;
            }
        }
        if words(content).count() > self.base_words && self.patterns.len() < 20 {
            return sequence_ratio(self.samples[0].as_bytes(), normalized.as_bytes()) > 0.75;
        }
        true
    }
}

impl NativeWildcardProfile {
    fn applies(&self, path: &str) -> bool {
        match self.selection.as_str() {
            "prefixes" => path.starts_with(&self.selector),
            "suffixes" => path.ends_with(&self.selector),
            _ => true,
        }
    }

    fn wildcard(
        &self,
        path: &str,
        media_type: &str,
        length: usize,
        content: &str,
        normalized: &str,
    ) -> bool {
        if self.matches_content(content, normalized) {
            return true;
        }
        if self.media_type != media_type
            || self.patterns.len() >= 20
            || self.base_content.len() > 262144
            || content.len() > 262144
        {
            return false;
        }
        if sequence_ratio(self.samples[0].as_bytes(), normalized.as_bytes()) < 0.9 {
            return false;
        }
        if self.base_length.abs_diff(length) as f64 / self.base_length.max(1) as f64 > 0.35 {
            return false;
        }
        let path = path.trim_matches('/');
        (!path.is_empty() && normalized.contains(path)) || self.ambiguous
    }
}

#[derive(Clone)]
pub(crate) struct NativeObservation {
    key: Fingerprint,
    record: bool,
}

#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone)]
pub(crate) struct NativeWildcardClassifier {
    profiles: Vec<NativeWildcardProfile>,
    state: NativeCalibrationState,
    base_path: String,
    auto_calibration: bool,
    skip_statuses: Vec<u16>,
    blacklists: HashMap<u16, Vec<String>>,
}

#[pymethods]
impl NativeWildcardClassifier {
    #[new]
    fn new(
        profiles: Vec<Py<NativeWildcardProfile>>,
        state: PyRef<'_, NativeCalibrationState>,
        base_path: String,
        auto_calibration: bool,
        skip_statuses: Vec<u16>,
        blacklists: HashMap<u16, Vec<String>>,
        py: Python<'_>,
    ) -> Self {
        Self {
            profiles: profiles
                .iter()
                .map(|profile| profile.borrow(py).clone())
                .collect(),
            state: state.clone(),
            base_path,
            auto_calibration,
            skip_statuses,
            blacklists,
        }
    }
}

impl NativeWildcardClassifier {
    pub(crate) fn prepare(
        &self,
        result: &NativeHttpResult,
        request_path: &str,
    ) -> Option<NativeObservation> {
        if result.filtered
            || result.error.is_some()
            || !result.body_complete
            || !result.history.is_empty()
            || self.skip_statuses.contains(&result.status)
            || result.body.is_empty()
            || !result.body.is_ascii()
            || result.body.iter().any(|byte| !text_byte(*byte))
            || request_path.contains('%')
        {
            return None;
        }
        if !self
            .profiles
            .iter()
            .any(|profile| profile.status == result.status)
        {
            return None;
        }
        let mut media_type = None;
        for (name, value) in &result.headers {
            if name.eq_ignore_ascii_case("location") && !value.is_empty() {
                return None;
            }
            if name.eq_ignore_ascii_case("content-type") {
                if media_type.is_some() {
                    return None;
                }
                media_type = Some(value.as_str());
            }
        }
        if crate::filters::has_non_utf8_charset(&result.headers) {
            return None;
        }
        let media_type = media_type.unwrap_or("").split(';').next().unwrap_or("");
        let response_path = format!("{}{}", self.base_path, request_path);
        let path = clean_path(&response_path);
        let candidate_path = clean_path(request_path);
        // Python applies blacklist exclusions before recording auto calibration.
        if self.blacklists.get(&result.status).is_some_and(|suffixes| {
            suffixes
                .iter()
                .any(|suffix| path.ends_with(suffix.strip_prefix('/').unwrap_or(suffix)))
        }) {
            return None;
        }
        let content = std::str::from_utf8(&result.body).expect("ASCII body");
        let normalized = normalize_ascii(content);
        if !self.profiles.iter().any(|profile| {
            profile.status == result.status
                && profile.applies(candidate_path)
                && profile.wildcard(
                    candidate_path,
                    media_type,
                    result.length,
                    content,
                    &normalized,
                )
        }) {
            return None;
        }
        let path = path.trim_matches('/');
        let fingerprint_content = if path.is_empty() {
            normalized
        } else {
            normalized.replace(path, "__PATH__")
        };
        let record = result.length >= 32
            && (self.auto_calibration
                || (400..=599).contains(&result.status)
                || (!path.is_empty() && content.contains(path)));
        Some(NativeObservation {
            key: Fingerprint::new(
                result.status,
                media_type.to_string(),
                String::new(),
                &fingerprint_content,
            ),
            record,
        })
    }

    pub(crate) fn reset_pending(&self) {
        self.state
            .inner
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .pending
            .clear();
    }

    pub(crate) fn register(&self, index: usize, observation: NativeObservation) {
        self.state
            .inner
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .pending
            .insert(index, observation);
    }
}

fn clean_path(path: &str) -> &str {
    path.split(['?', '#']).next().unwrap_or("")
}
fn words(content: &str) -> impl Iterator<Item = &str> {
    content
        .split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
        .filter(|s| !s.is_empty())
}
fn text_byte(byte: u8) -> bool {
    matches!(byte, 7..=10 | 12..=13 | 27 | 32..=126)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn calibration_thresholds_and_recording_match_python() {
        for forced in [false, true] {
            let state = NativeCalibrationState::new(forced);
            let threshold = if forced { 3 } else { 8 };
            for i in 1..=threshold {
                assert_eq!(
                    state.observe(404, "text/plain".into(), "".into(), "missing", true),
                    i >= threshold
                );
            }
            assert!(state.observe(404, "text/plain".into(), "".into(), "missing", false));
            assert!(!state.observe(200, "text/plain".into(), "".into(), "distinct", false));
        }
    }

    #[test]
    fn only_processed_ranges_commit_pending_observations() {
        let state = NativeCalibrationState::new(true);
        let key = Fingerprint::new(404, "text/plain".into(), "".into(), "missing");
        {
            let mut data = state.inner.lock().unwrap();
            data.pending.insert(
                0,
                NativeObservation {
                    key: key.clone(),
                    record: true,
                },
            );
            data.pending.insert(
                2,
                NativeObservation {
                    key: key.clone(),
                    record: true,
                },
            );
        }
        state.commit_range(0, 1);
        assert!(!state.observe_key(key.clone(), true)); // Python fallback at index 1.
        assert!(!state.inner.lock().unwrap().learned.contains(&key));
        state.commit_range(2, 3);
        assert!(state.inner.lock().unwrap().learned.contains(&key));
        assert!(state.inner.lock().unwrap().pending.is_empty());
    }
}
