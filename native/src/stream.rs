//! Ordered micro-batch delivery across the Rust/Python boundary.

use crate::result::NativeHttpResult;
use pyo3::prelude::*;
use std::collections::{BTreeMap, VecDeque};

pub(crate) const DEFAULT_STREAM_CHUNK_SIZE: usize = 1024;

pub(crate) struct WorkerCompletion {
    pub(crate) request_index: usize,
    pub(crate) result: Option<NativeHttpResult>,
}

pub(crate) struct NativeStreamChunk {
    pub(crate) start_index: usize,
    pub(crate) processed_count: usize,
    pub(crate) results: Vec<NativeHttpResult>,
}

/// Reorders concurrent completions into releasable input prefixes.
///
/// Python owns dictionary claims and can only release a native-wordlist prefix.
/// Keeping that contract here lets checkpoints remain entirely Python-owned.
pub(crate) struct OrderedChunkBuffer {
    completed: Vec<bool>,
    pending_results: BTreeMap<usize, NativeHttpResult>,
    chunk_start: usize,
    next_index: usize,
    ready_results: VecDeque<NativeHttpResult>,
}

impl OrderedChunkBuffer {
    pub(crate) fn new(result_count: usize) -> Self {
        Self {
            completed: vec![false; result_count],
            pending_results: BTreeMap::new(),
            chunk_start: 0,
            next_index: 0,
            ready_results: VecDeque::new(),
        }
    }

    pub(crate) fn push(&mut self, completion: WorkerCompletion) {
        debug_assert!(completion.request_index < self.completed.len());
        debug_assert!(!self.completed[completion.request_index]);
        self.completed[completion.request_index] = true;
        if let Some(result) = completion.result {
            self.pending_results
                .insert(completion.request_index, result);
        }
        while self.completed.get(self.next_index) == Some(&true) {
            if let Some(result) = self.pending_results.remove(&self.next_index) {
                self.ready_results.push_back(result);
            }
            self.next_index += 1;
        }
    }

    pub(crate) fn take_ready(
        &mut self,
        chunk_size: usize,
        force: bool,
    ) -> Option<NativeStreamChunk> {
        let ready_count = self.next_index - self.chunk_start;
        if ready_count == 0 || (!force && ready_count < chunk_size.max(1)) {
            return None;
        }

        let processed_count = self.chunk_start + ready_count.min(chunk_size.max(1));
        let mut results = Vec::new();
        while self
            .ready_results
            .front()
            .is_some_and(|result| result.request_index < processed_count)
        {
            results.push(self.ready_results.pop_front().unwrap());
        }
        let chunk = NativeStreamChunk {
            start_index: self.chunk_start,
            processed_count,
            results,
        };
        self.chunk_start = processed_count;
        Some(chunk)
    }

    pub(crate) fn delivered_count(&self) -> usize {
        self.chunk_start
    }
}

/// Run Python on the `Runtime::block_on` coordinator thread.
///
/// HTTP workers are separately spawned Tokio tasks, so calling Python here
/// preserves channel backpressure without paying for another blocking-pool hop.
pub(crate) fn deliver_chunk(callback: &Py<PyAny>, chunk: NativeStreamChunk) -> PyResult<()> {
    Python::attach(|py| {
        callback
            .bind(py)
            .call1((chunk.start_index, chunk.processed_count, chunk.results))
            .map(|_| ())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::result::native_error_result;

    fn actionable(index: usize) -> WorkerCompletion {
        let mut result = native_error_result(String::new(), 0.0, "boom".to_string());
        result.request_index = index;
        WorkerCompletion {
            request_index: index,
            result: Some(result),
        }
    }

    fn filtered(index: usize) -> WorkerCompletion {
        WorkerCompletion {
            request_index: index,
            result: None,
        }
    }

    #[test]
    fn out_of_order_completions_wait_for_a_releasable_prefix() {
        let mut buffer = OrderedChunkBuffer::new(2);
        buffer.push(actionable(1));
        assert!(buffer.take_ready(2, false).is_none());

        buffer.push(filtered(0));
        let chunk = buffer.take_ready(2, false).unwrap();

        assert_eq!(chunk.start_index, 0);
        assert_eq!(chunk.processed_count, 2);
        assert_eq!(chunk.results.len(), 1);
        assert_eq!(chunk.results[0].request_index, 1);
    }

    #[test]
    fn filtered_misses_advance_progress_without_result_objects() {
        let mut buffer = OrderedChunkBuffer::new(4);
        for index in 0..4 {
            buffer.push(filtered(index));
        }

        assert!(buffer.take_ready(8, false).is_none());
        let chunk = buffer.take_ready(8, true).unwrap();

        assert_eq!((chunk.start_index, chunk.processed_count), (0, 4));
        assert!(chunk.results.is_empty());
        assert_eq!(buffer.delivered_count(), 4);
    }

    #[test]
    fn actionable_results_wait_for_the_size_or_time_flush_boundary() {
        let mut buffer = OrderedChunkBuffer::new(16);
        for index in 0..16 {
            buffer.push(actionable(index));
        }

        assert!(buffer.take_ready(64, false).is_none());
        let chunk = buffer.take_ready(64, true).unwrap();

        assert_eq!((chunk.start_index, chunk.processed_count), (0, 16));
        assert_eq!(chunk.results.len(), 16);
    }

    #[test]
    fn progress_is_split_into_ordered_micro_batches() {
        let mut buffer = OrderedChunkBuffer::new(6);
        for index in 0..5 {
            buffer.push(filtered(index));
        }

        let first = buffer.take_ready(3, false).unwrap();
        assert_eq!((first.start_index, first.processed_count), (0, 3));

        let second = buffer.take_ready(3, true).unwrap();
        assert_eq!((second.start_index, second.processed_count), (3, 5));

        buffer.push(actionable(5));
        let third = buffer.take_ready(3, true).unwrap();
        assert_eq!((third.start_index, third.processed_count), (5, 6));
        assert_eq!(third.results[0].request_index, 5);
    }
}
