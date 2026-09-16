//! Native response matcher and filter policy.

use regex::{Regex, RegexBuilder};

pub(crate) type NumericRange = (usize, usize);
pub(crate) type TimeFilter = (String, f64);

#[derive(Clone)]
pub(crate) struct NativeFilterConfig {
    pub(crate) include_status_codes: Vec<u16>,
    pub(crate) exclude_status_codes: Vec<u16>,
    pub(crate) minimum_response_size: usize,
    pub(crate) maximum_response_size: usize,
    pub(crate) matcher_mode: String,
    pub(crate) filter_mode: String,
    pub(crate) match_status_codes: Vec<u16>,
    pub(crate) filter_status_codes: Vec<u16>,
    pub(crate) match_sizes: Vec<NumericRange>,
    pub(crate) filter_sizes: Vec<NumericRange>,
    pub(crate) match_words: Vec<NumericRange>,
    pub(crate) filter_words: Vec<NumericRange>,
    pub(crate) match_lines: Vec<NumericRange>,
    pub(crate) filter_lines: Vec<NumericRange>,
    pub(crate) match_regex: Option<Regex>,
    pub(crate) filter_regex: Option<Regex>,
    pub(crate) match_headers: Vec<String>,
    pub(crate) filter_headers: Vec<String>,
    pub(crate) match_header_regex: Option<Regex>,
    pub(crate) filter_header_regex: Option<Regex>,
    pub(crate) match_time: Vec<TimeFilter>,
    pub(crate) filter_time: Vec<TimeFilter>,
}

impl NativeFilterConfig {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        include_status_codes: Vec<u16>,
        exclude_status_codes: Vec<u16>,
        minimum_response_size: usize,
        maximum_response_size: usize,
        matcher_mode: String,
        filter_mode: String,
        match_status_codes: Vec<u16>,
        filter_status_codes: Vec<u16>,
        match_sizes: Vec<NumericRange>,
        filter_sizes: Vec<NumericRange>,
        match_words: Vec<NumericRange>,
        filter_words: Vec<NumericRange>,
        match_lines: Vec<NumericRange>,
        filter_lines: Vec<NumericRange>,
        match_regex: Option<String>,
        filter_regex: Option<String>,
        match_headers: Vec<String>,
        filter_headers: Vec<String>,
        match_header_regex: Option<String>,
        filter_header_regex: Option<String>,
        match_time: Vec<TimeFilter>,
        filter_time: Vec<TimeFilter>,
    ) -> Result<Self, String> {
        Ok(Self {
            include_status_codes,
            exclude_status_codes,
            minimum_response_size,
            maximum_response_size,
            matcher_mode,
            filter_mode,
            match_status_codes,
            filter_status_codes,
            match_sizes,
            filter_sizes,
            match_words,
            filter_words,
            match_lines,
            filter_lines,
            match_regex: compile_regex(match_regex, "--match-regex")?,
            filter_regex: compile_regex(filter_regex, "--filter-regex")?,
            match_headers,
            filter_headers,
            match_header_regex: compile_header_regex(match_header_regex, "--match-header-regex")?,
            filter_header_regex: compile_header_regex(
                filter_header_regex,
                "--filter-header-regex",
            )?,
            match_time,
            filter_time,
        })
    }

    pub(crate) fn filter_reason(
        &self,
        status: u16,
        length: usize,
        headers: &[(String, String)],
        body: &[u8],
        elapsed_ms: f64,
    ) -> Option<&'static str> {
        if self.exclude_status_codes.contains(&status) {
            return Some("exclude_status");
        }

        if !self.include_status_codes.is_empty() && !self.include_status_codes.contains(&status) {
            return Some("include_status");
        }

        if length < self.minimum_response_size {
            return Some("minimum_response_size");
        }

        if self.maximum_response_size > 0 && length > self.maximum_response_size {
            return Some("maximum_response_size");
        }

        if self.needs_text() && has_non_utf8_charset(headers) {
            // Python owns charset-aware decoding. Preserve this response so the
            // common filter stack can evaluate it after NativeResponse decodes it.
            return None;
        }

        let text = self
            .needs_text()
            .then(|| String::from_utf8_lossy(body).into_owned());
        let text = text.as_deref();
        let headers_text = self.needs_headers().then(|| headers_to_text(headers));
        let headers_text = headers_text.as_deref();

        if !self.matches_advanced_matchers(status, length, text, headers_text, elapsed_ms) {
            return Some("advanced_matcher");
        }

        if self.matches_advanced_filters(status, length, text, headers_text, elapsed_ms) {
            return Some("advanced_filter");
        }

        None
    }

    fn needs_text(&self) -> bool {
        !self.match_words.is_empty()
            || !self.filter_words.is_empty()
            || !self.match_lines.is_empty()
            || !self.filter_lines.is_empty()
            || self.match_regex.is_some()
            || self.filter_regex.is_some()
    }

    fn needs_headers(&self) -> bool {
        !self.match_headers.is_empty()
            || !self.filter_headers.is_empty()
            || self.match_header_regex.is_some()
            || self.filter_header_regex.is_some()
    }

    fn matches_advanced_matchers(
        &self,
        status: u16,
        length: usize,
        text: Option<&str>,
        headers_text: Option<&str>,
        elapsed_ms: f64,
    ) -> bool {
        let mut checks = Vec::new();

        if !self.match_status_codes.is_empty() {
            checks.push(self.match_status_codes.contains(&status));
        }
        if !self.match_sizes.is_empty() {
            checks.push(matches_numeric_ranges(length, &self.match_sizes));
        }
        if !self.match_words.is_empty() {
            checks.push(matches_numeric_ranges(word_count(text), &self.match_words));
        }
        if !self.match_lines.is_empty() {
            checks.push(matches_numeric_ranges(line_count(text), &self.match_lines));
        }
        if let Some(regex) = &self.match_regex {
            checks.push(regex.is_match(text.unwrap_or_default()));
        }
        if !self.match_headers.is_empty() {
            checks.push(matches_header_text(headers_text, &self.match_headers));
        }
        if let Some(regex) = &self.match_header_regex {
            checks.push(regex.is_match(headers_text.unwrap_or_default()));
        }
        if !self.match_time.is_empty() {
            checks.push(matches_time_filters(elapsed_ms, &self.match_time));
        }

        combine_advanced_checks(&checks, &self.matcher_mode, true)
    }

    fn matches_advanced_filters(
        &self,
        status: u16,
        length: usize,
        text: Option<&str>,
        headers_text: Option<&str>,
        elapsed_ms: f64,
    ) -> bool {
        let mut checks = Vec::new();

        if !self.filter_status_codes.is_empty() {
            checks.push(self.filter_status_codes.contains(&status));
        }
        if !self.filter_sizes.is_empty() {
            checks.push(matches_numeric_ranges(length, &self.filter_sizes));
        }
        if !self.filter_words.is_empty() {
            checks.push(matches_numeric_ranges(word_count(text), &self.filter_words));
        }
        if !self.filter_lines.is_empty() {
            checks.push(matches_numeric_ranges(line_count(text), &self.filter_lines));
        }
        if let Some(regex) = &self.filter_regex {
            checks.push(regex.is_match(text.unwrap_or_default()));
        }
        if !self.filter_headers.is_empty() {
            checks.push(matches_header_text(headers_text, &self.filter_headers));
        }
        if let Some(regex) = &self.filter_header_regex {
            checks.push(regex.is_match(headers_text.unwrap_or_default()));
        }
        if !self.filter_time.is_empty() {
            checks.push(matches_time_filters(elapsed_ms, &self.filter_time));
        }

        combine_advanced_checks(&checks, &self.filter_mode, false)
    }
}

fn has_non_utf8_charset(headers: &[(String, String)]) -> bool {
    response_charset(headers).is_some_and(|charset| {
        charset
            .chars()
            .filter(|character| !matches!(character, '-' | '_' | ' '))
            .flat_map(char::to_lowercase)
            .collect::<String>()
            != "utf8"
    })
}

fn response_charset(headers: &[(String, String)]) -> Option<&str> {
    let content_type = headers
        .iter()
        .find_map(|(name, value)| name.eq_ignore_ascii_case("content-type").then_some(value))?;

    content_type.split(';').skip(1).find_map(|parameter| {
        let (name, value) = parameter.split_once('=')?;
        name.trim().eq_ignore_ascii_case("charset").then(|| {
            value
                .trim()
                .trim_matches(|character| matches!(character, '\'' | '"'))
        })
    })
}

fn compile_regex(pattern: Option<String>, label: &str) -> Result<Option<Regex>, String> {
    match pattern {
        Some(pattern) => Regex::new(&pattern).map(Some).map_err(|error| {
            format!("Invalid {label} regular expression for native backend: {error}")
        }),
        None => Ok(None),
    }
}

fn compile_header_regex(pattern: Option<String>, label: &str) -> Result<Option<Regex>, String> {
    match pattern {
        Some(pattern) => RegexBuilder::new(&pattern)
            .case_insensitive(true)
            .build()
            .map(Some)
            .map_err(|error| {
                format!("Invalid {label} regular expression for native backend: {error}")
            }),
        None => Ok(None),
    }
}

fn matches_numeric_ranges(value: usize, ranges: &[NumericRange]) -> bool {
    ranges
        .iter()
        .any(|(minimum, maximum)| *minimum <= value && value <= *maximum)
}

fn matches_time_filters(elapsed_ms: f64, filters: &[TimeFilter]) -> bool {
    filters.iter().any(|(operator, value)| {
        (operator == ">" && elapsed_ms > *value)
            || (operator == "<" && elapsed_ms < *value)
            || (operator == "=" && elapsed_ms == *value)
    })
}

fn headers_to_text(headers: &[(String, String)]) -> String {
    headers
        .iter()
        .map(|(name, value)| format!("{name}: {value}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn matches_header_text(headers_text: Option<&str>, patterns: &[String]) -> bool {
    let headers_text = headers_text.unwrap_or_default().to_lowercase();
    patterns
        .iter()
        .any(|pattern| headers_text.contains(&pattern.to_lowercase()))
}

fn combine_advanced_checks(checks: &[bool], mode: &str, default: bool) -> bool {
    if checks.is_empty() {
        return default;
    }

    if mode == "and" {
        return checks.iter().all(|check| *check);
    }

    checks.iter().any(|check| *check)
}

fn word_count(text: Option<&str>) -> usize {
    text.unwrap_or_default().split_whitespace().count()
}

fn line_count(text: Option<&str>) -> usize {
    let text = text.unwrap_or_default();
    if text.is_empty() {
        return 0;
    }

    text.matches('\n').count() + 1
}
