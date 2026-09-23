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
use filters::NativeFilterConfig;
use pyo3::prelude::*;
use result::NativeHttpResult;
use wordlist::{generate_wordlist, generate_wordlist_owned, NativeWordlist, NativeWordlistBatch};

#[cfg(test)]
use engine::runtime_worker_count;
#[cfg(test)]
use filters::{compile_header_regex, compile_regex};
#[cfg(test)]
use raw_client::{parse_raw_http_response, should_use_raw_http};
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
    module.add_function(wrap_pyfunction!(generate_wordlist_owned, module)?)?;
    module.add_function(wrap_pyfunction!(scan_http, module)?)?;
    module.add_class::<NativeFilterConfig>()?;
    module.add_class::<NativeHttpEngine>()?;
    module.add_class::<NativeHttpResult>()?;
    module.add_class::<NativeWordlist>()?;
    module.add_class::<NativeWordlistBatch>()?;
    Ok(())
}
