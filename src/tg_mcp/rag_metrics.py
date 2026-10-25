"""Bounded process-local sampling of archive throughput and net queue drain."""

from collections import deque
from dataclasses import dataclass

SAMPLE_INTERVAL = 10
MIN_WINDOW = 30
RATE_WINDOW = 60
HISTORY_WINDOW = 300
STALE_AFTER = 30


@dataclass(frozen=True)
class Sample:
    at: float
    eligible: int
    indexed: int
    processed: int

    @property
    def pending(self):
        return self.eligible - self.indexed


class RAGMetrics:
    def __init__(self):
        self.samples = deque(maxlen=32)
        self.scope = None

    def observe(self, at, scope, eligible, indexed, processed):
        previous = self.samples[-1] if self.samples else None
        if scope != self.scope or (
            previous
            and (
                at <= previous.at
                or at - previous.at > STALE_AFTER
                or eligible < previous.eligible
                or processed < previous.processed
            )
        ):
            self.samples.clear()
        self.scope = scope
        self.samples.append(Sample(at, eligible, indexed, processed))
        while len(self.samples) > 1 and self.samples[0].at < at - HISTORY_WINDOW:
            self.samples.popleft()

    def snapshot(self, at, scope, pending, *, paused=False, blocked=False):
        result = {
            "state": "warming",
            "window_seconds": 0,
            "index_per_second": None,
            "incoming_per_second": None,
            "queue_per_second": None,
            "eta_seconds": None,
            "queue_change": None,
            "history": [],
        }
        if scope != self.scope or not self.samples:
            return {**result, "state": "complete" if pending == 0 else "warming"}
        latest = self.samples[-1]
        if at - latest.at > STALE_AFTER:
            return {**result, "state": "stale"}
        result["history"] = [
            {"age_seconds": at - s.at, "pending": s.pending}
            for s in self.samples
            if 0 <= at - s.at <= HISTORY_WINDOW
        ]
        if paused:
            return {**result, "state": "paused"}
        start = next((s for s in self.samples if s.at >= latest.at - RATE_WINDOW), latest)
        elapsed = latest.at - start.at
        if elapsed < MIN_WINDOW:
            return {**result, "state": "complete" if pending == 0 else "warming"}
        queue_rate = (latest.pending - start.pending) / elapsed
        result.update(
            window_seconds=elapsed,
            index_per_second=(latest.processed - start.processed) / elapsed,
            incoming_per_second=(latest.eligible - start.eligible) / elapsed,
            queue_per_second=queue_rate,
            queue_change=latest.pending - start.pending,
        )
        if pending == 0:
            return {**result, "state": "complete", "eta_seconds": 0}
        if blocked:
            return {**result, "state": "blocked"}
        if queue_rate >= 0:
            return {**result, "state": "growing" if queue_rate > 0 else "stalled"}
        return {**result, "state": "draining", "eta_seconds": pending / -queue_rate}
