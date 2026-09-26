//! Native HTTP session state shared by engines with different transports.

use cookie::Cookie as ParsedCookie;
use pyo3::prelude::*;
use reqwest::cookie::CookieStore;
use reqwest::header::HeaderValue;
use std::cell::RefCell;
use std::cmp::Reverse;
use std::future::Future;
use std::sync::{Arc, RwLock};

tokio::task_local! {
    static INITIAL_COOKIE_OVERRIDE: RefCell<Option<HeaderValue>>;
}

/// Opaque state that can outlive an engine rebuild or be shared by a replay engine.
#[pyclass(skip_from_py_object)]
#[derive(Clone, Debug, Default)]
pub(crate) struct NativeHttpSession {
    pub(crate) cookie_store: Arc<NativeCookieStore>,
}

#[pymethods]
impl NativeHttpSession {
    #[new]
    fn new() -> Self {
        Self::default()
    }
}

#[derive(Debug, Default)]
pub(crate) struct NativeCookieStore {
    store: RwLock<cookie_store::CookieStore>,
}

impl NativeCookieStore {
    pub(crate) fn add_cookie_str(&self, cookie: &str, url: &reqwest::Url) {
        if let Ok(cookie) = ParsedCookie::parse(cookie).map(ParsedCookie::into_owned) {
            if allows_cookie_domain_attribute(&cookie) {
                self.store
                    .write()
                    .unwrap()
                    .store_response_cookies(std::iter::once(cookie), url);
            }
        }
    }
}

impl CookieStore for NativeCookieStore {
    fn set_cookies(
        &self,
        cookie_headers: &mut dyn Iterator<Item = &HeaderValue>,
        url: &reqwest::Url,
    ) {
        let cookies = cookie_headers.filter_map(|value| {
            value
                .to_str()
                .ok()
                .and_then(|cookie| ParsedCookie::parse(cookie).ok())
                .map(ParsedCookie::into_owned)
                .filter(allows_cookie_domain_attribute)
        });
        self.store
            .write()
            .unwrap()
            .store_response_cookies(cookies, url);
    }

    fn cookies(&self, url: &reqwest::Url) -> Option<HeaderValue> {
        // A configured Cookie header applies to the initial request only. On a
        // redirect reqwest asks the provider again, so subsequent lookups must
        // use the scoped session jar just like the Python request backends.
        if let Ok(Some(cookie)) =
            INITIAL_COOKIE_OVERRIDE.try_with(|cookie| cookie.borrow_mut().take())
        {
            return Some(cookie);
        }
        let store = self.store.read().unwrap();
        let mut cookies = store
            .matches(url)
            .into_iter()
            .filter(|cookie| url.scheme() == "https" || !cookie.secure().unwrap_or(false))
            .collect::<Vec<_>>();
        cookies.sort_by_key(|cookie| Reverse(cookie.path.len()));
        let values = cookies
            .into_iter()
            .map(|cookie| {
                let (name, value) = cookie.name_value();
                format!("{name}={value}")
            })
            .collect::<Vec<_>>()
            .join("; ");
        if values.is_empty() {
            None
        } else {
            HeaderValue::from_str(&values).ok()
        }
    }
}

fn allows_cookie_domain_attribute(cookie: &ParsedCookie<'_>) -> bool {
    cookie.domain().is_none_or(|domain| {
        let domain = domain.trim_start_matches('.');
        domain.contains('.') || domain.eq_ignore_ascii_case("local")
    })
}

pub(crate) async fn with_initial_cookie_override<F, T>(cookie: Option<HeaderValue>, future: F) -> T
where
    F: Future<Output = T>,
{
    INITIAL_COOKIE_OVERRIDE
        .scope(RefCell::new(cookie), future)
        .await
}
