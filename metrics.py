"""Observability: track stage resolution rates, success/failure counts, and LLM costs.

Exposes metrics via GET /metrics endpoint and logs periodic summaries.
"""
from __future__ import annotations
import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class AgentMetrics:
    """Singleton metrics collector for the agent pipeline."""

    _instance: AgentMetrics | None = None

    def __new__(cls) -> AgentMetrics:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.start_time = time.time()
        # Stage resolution counters
        self.stage_counts: dict[str, int] = defaultdict(int)
        # Per-website resolution counters
        self.website_counts: dict[str, int] = defaultdict(int)
        # Per-task-type counters
        self.task_type_counts: dict[str, int] = defaultdict(int)
        # Outcome tracking
        self.total_tasks = 0
        self.total_steps = 0
        self.knowledge_base_hits = 0
        self.knowledge_base_size = 0
        # LLM cost tracking
        self.total_llm_cost = 0.0
        self.total_llm_calls = 0
        # Latency tracking (per stage, capped to last N samples)
        self._max_latency_samples = 200
        self.stage_latencies: dict[str, list[float]] = defaultdict(list)
        # Auto-learn tracking
        self.auto_learned_tasks = 0

    def record_resolution(
        self,
        stage: str,
        website: str | None = None,
        task_type: str = "GENERAL",
        latency_ms: float = 0.0,
    ) -> None:
        self.stage_counts[stage] += 1
        self.total_steps += 1
        if website:
            self.website_counts[website] += 1
        self.task_type_counts[task_type] += 1
        if latency_ms > 0:
            lats = self.stage_latencies[stage]
            lats.append(latency_ms)
            if len(lats) > self._max_latency_samples:
                self.stage_latencies[stage] = lats[-self._max_latency_samples:]

    def record_new_task(self) -> None:
        self.total_tasks += 1

    def record_kb_hit(self) -> None:
        self.knowledge_base_hits += 1

    def record_llm_usage(self, cost: float, calls: int) -> None:
        self.total_llm_cost = cost
        self.total_llm_calls = calls

    def record_auto_learn(self) -> None:
        self.auto_learned_tasks += 1

    def set_kb_size(self, size: int) -> None:
        self.knowledge_base_size = size

    def snapshot(self) -> dict:
        uptime = time.time() - self.start_time
        avg_latencies = {}
        for stage, lats in self.stage_latencies.items():
            avg_latencies[stage] = round(sum(lats) / len(lats), 1) if lats else 0

        # Stage percentages
        total = self.total_steps or 1
        stage_pct = {k: round(v / total * 100, 1) for k, v in self.stage_counts.items()}

        return {
            "uptime_seconds": round(uptime, 1),
            "total_tasks": self.total_tasks,
            "total_steps": self.total_steps,
            "knowledge_base": {
                "size": self.knowledge_base_size,
                "hits": self.knowledge_base_hits,
                "auto_learned": self.auto_learned_tasks,
            },
            "stage_resolution": dict(self.stage_counts),
            "stage_percentages": stage_pct,
            "avg_latency_ms": avg_latencies,
            "top_websites": dict(
                sorted(self.website_counts.items(), key=lambda x: -x[1])[:10]
            ),
            "top_task_types": dict(
                sorted(self.task_type_counts.items(), key=lambda x: -x[1])[:10]
            ),
            "llm": {
                "total_calls": self.total_llm_calls,
                "total_cost_usd": round(self.total_llm_cost, 6),
                "avg_cost_per_call": round(
                    self.total_llm_cost / self.total_llm_calls, 6
                )
                if self.total_llm_calls
                else 0,
            },
        }

    def log_summary(self) -> None:
        s = self.snapshot()
        logger.info(
            f"METRICS | tasks={s['total_tasks']} steps={s['total_steps']} "
            f"kb_hits={s['knowledge_base']['hits']} kb_size={s['knowledge_base']['size']} "
            f"auto_learned={s['knowledge_base']['auto_learned']} "
            f"llm_calls={s['llm']['total_calls']} llm_cost=${s['llm']['total_cost_usd']:.4f} "
            f"stages={s['stage_resolution']}"
        )
