//! Ordered result-chunk delivery across the Rust/Python boundary.

use crate::result::NativeHttpResult;
use pyo3::prelude::*;
use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

pub(crate) const DEFAULT_RESULT_CHUNK_SIZE: usize = 2048;

pub(crate) struct WorkerCompletion {
    pub(crate) request_index: usize,
    pub(crate) result: Option<NativeHttpResult>,
}

struct SharedCompletions {
    completed: Box<[AtomicBool]>,
    pending_results: Mutex<BTreeMap<usize, NativeHttpResult>>,
}

/// Worker-facing handle for recording a completed request without a channel hop.
///
/// Filtered misses only set one atomic flag. Actionable results are inserted
/// before publishing that flag, so the coordinator observes both together.
#[derive(Clone)]
pub(crate) struct CompletionWriter {
    shared: Arc<SharedCompletions>,
}

impl CompletionWriter {
    pub(crate) fn push(&self, completion: WorkerCompletion) {
        debug_assert!(completion.request_index < self.shared.completed.len());
        debug_assert!(!self.shared.completed[completion.request_index].load(Ordering::Relaxed));
        if let Some(result) = completion.result {
            self.shared
                .pending_results
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .insert(completion.request_index, result);
        }
        self.shared.completed[completion.request_index].store(true, Ordering::Release);
    }
}

pub(crate) struct NativeScanChunk {
    pub(crate) start_index: usize,
    pub(crate) end_index: usize,
    pub(crate) results: Vec<NativeHttpResult>,
}

/// Reorders concurrent completions into releasable input prefixes.
///
/// Python owns dictionary claims and can only release a native-wordlist prefix.
/// Keeping that contract here lets checkpoints remain entirely Python-owned.
pub(crate) struct OrderedChunkBuffer {
    shared: Arc<SharedCompletions>,
    chunk_start: usize,
    next_index: usize,
    ready_results: VecDeque<NativeHttpResult>,
}

impl OrderedChunkBuffer {
    pub(crate) fn new(result_count: usize) -> Self {
        Self {
            shared: Arc::new(SharedCompletions {
                completed: (0..result_count).map(|_| AtomicBool::new(false)).collect(),
                pending_results: Mutex::new(BTreeMap::new()),
            }),
            chunk_start: 0,
            next_index: 0,
            ready_results: VecDeque::new(),
        }
    }

    pub(crate) fn writer(&self) -> CompletionWriter {
        CompletionWriter {
            shared: self.shared.clone(),
        }
    }

    fn refresh_ready(&mut self) {
        let first_new_index = self.next_index;
        while self
            .shared
            .completed
            .get(self.next_index)
            .is_some_and(|completed| completed.load(Ordering::Acquire))
        {
            self.next_index += 1;
        }
        if self.next_index == first_new_index {
            return;
        }

        let mut pending_results = self
            .shared
            .pending_results
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        for request_index in first_new_index..self.next_index {
            if let Some(result) = pending_results.remove(&request_index) {
                self.ready_results.push_back(result);
            }
        }
    }

    pub(crate) fn take_ready(&mut self, chunk_size: usize, force: bool) -> Option<NativeScanChunk> {
        self.refresh_ready();
        let ready_count = self.next_index - self.chunk_start;
        if ready_count == 0 || (!force && ready_count < chunk_size.max(1)) {
            return None;
        }

        let end_index = self.chunk_start + ready_count.min(chunk_size.max(1));
        let mut results = Vec::new();
        while self
            .ready_results
            .front()
            .is_some_and(|result| result.request_index < end_index)
        {
            results.push(self.ready_results.pop_front().unwrap());
        }
        let chunk = NativeScanChunk {
            start_index: self.chunk_start,
            end_index,
            results,
        };
        self.chunk_start = end_index;
        Some(chunk)
    }

    pub(crate) fn delivered_count(&self) -> usize {
        self.chunk_start
    }
}

/// Run Python on the `Runtime::block_on` coordinator thread.
///
/// HTTP workers are separately spawned Tokio tasks, so calling Python here
/// does not block request progress. Completions remain bounded by the active
/// native-wordlist chunk without paying for a per-request channel hop.
pub(crate) fn deliver_chunk(callback: &Py<PyAny>, chunk: NativeScanChunk) -> PyResult<()> {
    Python::attach(|py| {
        callback
            .bind(py)
            .call1((chunk.start_index, chunk.end_index, chunk.results))
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
        let writer = buffer.writer();
        writer.push(actionable(1));
        assert!(buffer.take_ready(2, false).is_none());

        writer.push(filtered(0));
        let chunk = buffer.take_ready(2, false).unwrap();

        assert_eq!(chunk.start_index, 0);
        assert_eq!(chunk.end_index, 2);
        assert_eq!(chunk.results.len(), 1);
        assert_eq!(chunk.results[0].request_index, 1);
    }

    #[test]
    fn filtered_misses_advance_progress_without_result_objects() {
        let mut buffer = OrderedChunkBuffer::new(4);
        let writer = buffer.writer();
        for index in 0..4 {
            writer.push(filtered(index));
        }

        assert!(buffer.take_ready(8, false).is_none());
        let chunk = buffer.take_ready(8, true).unwrap();

        assert_eq!((chunk.start_index, chunk.end_index), (0, 4));
        assert!(chunk.results.is_empty());
        assert_eq!(buffer.delivered_count(), 4);
    }

    #[test]
    fn actionable_results_wait_for_the_size_or_time_flush_boundary() {
        let mut buffer = OrderedChunkBuffer::new(16);
        let writer = buffer.writer();
        for index in 0..16 {
            writer.push(actionable(index));
        }

        assert!(buffer.take_ready(64, false).is_none());
        let chunk = buffer.take_ready(64, true).unwrap();

        assert_eq!((chunk.start_index, chunk.end_index), (0, 16));
        assert_eq!(chunk.results.len(), 16);
    }

    #[test]
    fn progress_is_split_into_ordered_chunks() {
        let mut buffer = OrderedChunkBuffer::new(6);
        let writer = buffer.writer();
        for index in 0..5 {
            writer.push(filtered(index));
        }

        let first = buffer.take_ready(3, false).unwrap();
        assert_eq!((first.start_index, first.end_index), (0, 3));

        let second = buffer.take_ready(3, true).unwrap();
        assert_eq!((second.start_index, second.end_index), (3, 5));

        writer.push(actionable(5));
        let third = buffer.take_ready(3, true).unwrap();
        assert_eq!((third.start_index, third.end_index), (5, 6));
        assert_eq!(third.results[0].request_index, 5);
    }

    #[test]
    fn concurrent_writers_publish_actionable_results_before_completion() {
        let mut buffer = OrderedChunkBuffer::new(64);
        let writers = [buffer.writer(), buffer.writer()];
        let handles = writers.into_iter().enumerate().map(|(parity, writer)| {
            std::thread::spawn(move || {
                for index in (parity..64).step_by(2).rev() {
                    let completion = if index % 7 == 0 {
                        actionable(index)
                    } else {
                        filtered(index)
                    };
                    writer.push(completion);
                }
            })
        });
        for handle in handles {
            handle.join().unwrap();
        }

        let chunk = buffer.take_ready(64, false).unwrap();
        assert_eq!((chunk.start_index, chunk.end_index), (0, 64));
        assert_eq!(
            chunk
                .results
                .iter()
                .map(|result| result.request_index)
                .collect::<Vec<_>>(),
            (0..64).filter(|index| index % 7 == 0).collect::<Vec<_>>()
        );
    }
}
