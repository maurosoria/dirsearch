//! Shared request-rate limiting and per-worker delay scheduling.

use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::Duration;
use tokio::time::Instant;

const RATE_WINDOW: Duration = Duration::from_secs(1);
const RATE_WAIT_POLL: Duration = Duration::from_millis(100);

/// Session-wide sliding-window limiter shared by origin and replay engines.
#[derive(Debug, Default)]
pub(crate) struct NativeRequestRateLimiter {
    request_times: Mutex<VecDeque<Instant>>,
}

impl NativeRequestRateLimiter {
    /// Reserve one logical request, waiting until the shared window has room.
    ///
    /// Retries happen inside the transport after this reservation, matching
    /// the Python requesters' one-rate-slot-per-logical-request contract.
    pub(crate) async fn wait(&self, max_rate: usize) {
        while let Some(delay) = self.reserve(max_rate) {
            tokio::time::sleep(delay.min(RATE_WAIT_POLL)).await;
        }
    }

    pub(crate) fn rate(&self) -> usize {
        let mut request_times = self.request_times.lock().unwrap();
        discard_expired(&mut request_times, Instant::now());
        request_times.len()
    }

    fn reserve(&self, max_rate: usize) -> Option<Duration> {
        let mut request_times = self.request_times.lock().unwrap();
        // Read the clock after taking the lock so timestamps stay ordered even
        // when multiple Tokio runtime threads reserve concurrently.
        let now = Instant::now();
        discard_expired(&mut request_times, now);
        if max_rate == 0 || request_times.len() < max_rate {
            request_times.push_back(now);
            return None;
        }

        Some(
            RATE_WINDOW.saturating_sub(
                now.saturating_duration_since(request_times.front().copied().unwrap()),
            ),
        )
    }
}

fn discard_expired(request_times: &mut VecDeque<Instant>, now: Instant) {
    while request_times
        .front()
        .is_some_and(|request_time| now.saturating_duration_since(*request_time) >= RATE_WINDOW)
    {
        request_times.pop_front();
    }
}

/// Engine-wide delay deadlines, one independent lane per request worker.
///
/// A lane records its completion deadline instead of sleeping after a
/// request. That preserves spacing across scan-batch boundaries while letting
/// a one-request calibration call return immediately; the scanner's existing
/// delay satisfies the recorded deadline before its next request.
#[derive(Debug)]
pub(crate) struct NativeDelayPacer {
    delay: Duration,
    next_request_at: Mutex<Vec<Option<Instant>>>,
}

impl NativeDelayPacer {
    pub(crate) fn new(worker_count: usize, delay_secs: f64) -> Self {
        Self {
            delay: Duration::from_secs_f64(delay_secs),
            next_request_at: Mutex::new(vec![None; worker_count.max(1)]),
        }
    }

    pub(crate) async fn wait(&self, worker_index: usize) {
        if self.delay.is_zero() {
            return;
        }
        let deadline = self.next_request_at.lock().unwrap()[worker_index];
        if let Some(deadline) = deadline {
            tokio::time::sleep_until(deadline).await;
        }
    }

    pub(crate) fn mark_completed(&self, worker_index: usize) {
        if self.delay.is_zero() {
            return;
        }
        self.next_request_at.lock().unwrap()[worker_index] = Some(Instant::now() + self.delay);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test(start_paused = true)]
    async fn rate_limiter_enforces_a_shared_sliding_window() {
        let limiter = NativeRequestRateLimiter::default();

        limiter.wait(2).await;
        limiter.wait(2).await;
        let third = tokio::spawn({
            let limiter = std::sync::Arc::new(limiter);
            let task_limiter = limiter.clone();
            async move {
                task_limiter.wait(2).await;
                limiter
            }
        });

        tokio::task::yield_now().await;
        assert!(!third.is_finished());
        tokio::time::advance(RATE_WINDOW).await;
        assert_eq!(third.await.unwrap().rate(), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn unlimited_rate_is_still_reported_and_expires() {
        let limiter = NativeRequestRateLimiter::default();

        limiter.wait(0).await;
        limiter.wait(0).await;
        assert_eq!(limiter.rate(), 2);

        tokio::time::advance(RATE_WINDOW).await;
        assert_eq!(limiter.rate(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn delay_deadlines_are_independent_and_persist_between_batches() {
        let pacer = std::sync::Arc::new(NativeDelayPacer::new(2, 0.25));
        pacer.mark_completed(0);

        pacer.wait(1).await;
        let delayed = tokio::spawn({
            let pacer = pacer.clone();
            async move { pacer.wait(0).await }
        });

        tokio::task::yield_now().await;
        assert!(!delayed.is_finished());
        tokio::time::advance(Duration::from_millis(250)).await;
        delayed.await.unwrap();
    }
}
