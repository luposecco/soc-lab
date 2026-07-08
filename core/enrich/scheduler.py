from __future__ import annotations

import logging
import threading
import time

from core.enrich.runner import load_enrichment_config, run_enrichment
from core.enrich.validation import parse_interval_seconds

log = logging.getLogger(__name__)


class EnrichmentScheduler:
    def __init__(self, poll_seconds: float = 1.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_runs: dict[str, float] = {}
        self._running: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="enrichment-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("Scheduled enrichment tick failed")
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        now = time.time()
        seen = set()
        for enrichment in load_enrichment_config():
            name = enrichment.get("name", "")
            schedule = enrichment.get("schedule", "")
            if not name or not schedule or not enrichment.get("enabled", True):
                continue
            seen.add(name)
            interval = parse_interval_seconds(schedule)
            due_at = self._next_runs.setdefault(name, now + interval)
            if now < due_at or name in self._running:
                continue
            self._running.add(name)
            self._next_runs[name] = now + interval
            threading.Thread(target=self._run_one, args=(name,), name=f"enrichment-run-{name}", daemon=True).start()

        for stale in set(self._next_runs) - seen:
            self._next_runs.pop(stale, None)

    def _run_one(self, name: str) -> None:
        try:
            log.info("Running scheduled enrichment %s", name)
            run_enrichment(name)
        except Exception:
            log.exception("Scheduled enrichment %s failed", name)
        finally:
            self._running.discard(name)


scheduler = EnrichmentScheduler()
