//! PyO3 module registration for the native dirsearch backend.

mod engine;
mod filters;
mod raw_client;
mod raw_http;
mod request_target;
mod result;
mod transport;
mod wordlist;

use engine::{scan_http, NativeHttpEngine};
use pyo3::prelude::*;
use result::NativeHttpResult;
use wordlist::generate_wordlist;

#[cfg(test)]
use engine::runtime_worker_count;
#[cfg(test)]
use filters::NativeFilterConfig;
#[cfg(test)]
use raw_client::{parse_raw_http_response, should_use_raw_http};
#[cfg(test)]
use regex::Regex;
#[cfg(test)]
use request_target::prepare_request_target;
#[cfg(test)]
use reqwest::header::HeaderMap;
#[cfg(test)]
use result::{native_http_result, native_http_result_with_length, response_length};
#[cfg(test)]
use transport::{append_body_chunk, build_http_client, read_response_body, HeaderPairs};

#[cfg(test)]
mod tests;

#[pymodule]
fn dirsearch_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    // Python checks this value before using the tightly coupled native API.
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add_function(wrap_pyfunction!(generate_wordlist, module)?)?;
    module.add_function(wrap_pyfunction!(scan_http, module)?)?;
    module.add_class::<NativeHttpEngine>()?;
    module.add_class::<NativeHttpResult>()?;
    Ok(())
}
