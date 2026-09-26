//! Native HTTP session state shared by engines with different transports.

use crate::transport::NativeCookieStore;
use pyo3::prelude::*;
use std::sync::Arc;

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
