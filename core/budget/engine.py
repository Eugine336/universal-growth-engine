"""
Budget Allocator Engine

Self-optimizing budget allocation across acquisition channels.

Tracks per-channel spend, conversions, and CAC.
Automatically reallocates budget from underperforming channels
to top performers based on configurable strategies.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .schema import (
    BudgetPlan,
    ChannelBudget,
    ChannelPerformance,
    ReallocationChange,
    ReallocationEvent,
)

logger = logging.getLogger(__name__)

MAX_TREND_SAMPLES = 10


class BudgetAllocator:

    def __init__(self):
        self._plans: Dict[str, BudgetPlan] = {}
        self._performance: Dict[str, Dict[str, ChannelPerformance]] = defaultdict(dict)
        self._history: Dict[str, List[ReallocationEvent]] = defaultdict(list)
        logger.info("BudgetAllocator initialized")

    def create_plan(
        self,
        platform_id: str,
        total_budget: float,
        period: str = "monthly",
        channel_allocations: Optional[Dict[str, float]] = None,
        auto_optimize: bool = True,
        optimization_frequency: str = "daily",
        reallocation_strategy: str = "proportional",
        channel_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> BudgetPlan:
        channel_budgets: Dict[str, ChannelBudget] = {}
        configs = channel_configs or {}

        if channel_allocations:
            for ch, amount in channel_allocations.items():
                cfg = configs.get(ch, {})
                channel_budgets[ch] = ChannelBudget(
                    channel=ch,
                    allocated_budget=amount,
                    auto_pause_threshold=cfg.get("auto_pause_threshold", 0.0),
                    min_budget=cfg.get("min_budget", 0.0),
                    metadata=cfg.get("metadata", {}),
                )

        plan = BudgetPlan(
            platform_id=platform_id,
            total_budget=total_budget,
            period=period,
            channel_budgets=channel_budgets,
            auto_optimize=auto_optimize,
            optimization_frequency=optimization_frequency,
            reallocation_strategy=reallocation_strategy,
        )
        self._plans[platform_id] = plan
        logger.info("Budget plan created for platform=%s budget=%.2f", platform_id, total_budget)
        return plan

    def get_plan(self, platform_id: str) -> Optional[BudgetPlan]:
        return self._plans.get(platform_id)

    def update_plan(
        self,
        platform_id: str,
        total_budget: Optional[float] = None,
        period: Optional[str] = None,
        auto_optimize: Optional[bool] = None,
        optimization_frequency: Optional[str] = None,
        reallocation_strategy: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[BudgetPlan]:
        plan = self._plans.get(platform_id)
        if not plan:
            return None

        if total_budget is not None:
            plan.total_budget = total_budget
        if period is not None:
            plan.period = period
        if auto_optimize is not None:
            plan.auto_optimize = auto_optimize
        if optimization_frequency is not None:
            plan.optimization_frequency = optimization_frequency
        if reallocation_strategy is not None:
            plan.reallocation_strategy = reallocation_strategy
        if status is not None:
            plan.status = status
        plan.updated_at = datetime.now(timezone.utc)
        return plan

    def record_action(
        self,
        platform_id: str,
        channel: str,
        cost: float = 0.0,
        success: bool = True,
    ) -> None:
        perf = self._get_or_create_performance(platform_id, channel)
        perf.total_actions += 1
        perf.total_spend += cost
        if success:
            perf.successful_actions += 1
        if perf.first_action_at is None:
            perf.first_action_at = datetime.now(timezone.utc)

        plan = self._plans.get(platform_id)
        if plan and channel in plan.channel_budgets:
            plan.channel_budgets[channel].spent += cost

    def record_conversion(
        self,
        platform_id: str,
        channel: str,
    ) -> None:
        perf = self._get_or_create_performance(platform_id, channel)
        perf.conversions += 1
        perf.last_conversion_at = datetime.now(timezone.utc)
        self._recompute_metrics(perf)

    def get_performance(
        self,
        platform_id: str,
    ) -> Dict[str, ChannelPerformance]:
        return dict(self._performance.get(platform_id, {}))

    def get_channel_performance(
        self,
        platform_id: str,
        channel: str,
    ) -> Optional[ChannelPerformance]:
        return self._performance.get(platform_id, {}).get(channel)

    def optimize(self, platform_id: str) -> Optional[ReallocationEvent]:
        plan = self._plans.get(platform_id)
        if not plan or plan.status != "active":
            return None

        perf_map = self._performance.get(platform_id, {})
        if not perf_map:
            return None

        changes: List[ReallocationChange] = []
        freed_budget = 0.0

        for ch, cb in list(plan.channel_budgets.items()):
            if cb.status != "active":
                continue
            perf = perf_map.get(ch)
            if not perf:
                continue

            if cb.min_budget > 0 and perf.total_spend < cb.min_budget:
                continue

            if (
                cb.auto_pause_threshold > 0
                and perf.cac is not None
                and perf.cac > cb.auto_pause_threshold
            ):
                old_alloc = cb.allocated_budget
                freed = cb.remaining
                cb.status = "paused"
                freed_budget += freed
                changes.append(
                    ReallocationChange(
                        channel=ch,
                        old_budget=old_alloc,
                        new_budget=old_alloc - freed,
                        reason=f"CAC {perf.cac:.2f} exceeds threshold {cb.auto_pause_threshold:.2f}",
                    )
                )
            elif (
                cb.auto_pause_threshold > 0
                and perf.cac is None
                and perf.total_actions > 0
                and perf.total_spend >= cb.min_budget
                and cb.min_budget > 0
            ):
                old_alloc = cb.allocated_budget
                freed = cb.remaining
                cb.status = "paused"
                freed_budget += freed
                changes.append(
                    ReallocationChange(
                        channel=ch,
                        old_budget=old_alloc,
                        new_budget=old_alloc - freed,
                        reason="No conversions after meeting minimum spend",
                    )
                )

        if freed_budget > 0:
            active_channels = [
                (ch, perf_map.get(ch))
                for ch, cb in plan.channel_budgets.items()
                if cb.status == "active" and ch in perf_map
            ]
            active_channels = [(ch, p) for ch, p in active_channels if p is not None]

            if active_channels:
                alloc = self._allocate_freed_budget(
                    freed_budget,
                    active_channels,
                    plan.reallocation_strategy,
                    plan,
                    changes,
                )

        if not changes:
            return None

        event = ReallocationEvent(
            plan_id=plan.id,
            platform_id=platform_id,
            reason="Automatic optimization based on channel performance",
            changes=changes,
            trigger="auto",
        )
        self._history[platform_id].append(event)
        plan.updated_at = datetime.now(timezone.utc)
        return event

    def get_recommendation(self, platform_id: str) -> Dict[str, Any]:
        plan = self._plans.get(platform_id)
        if not plan:
            return {"recommendation": None, "reason": "No budget plan found"}

        perf_map = self._performance.get(platform_id, {})
        if not perf_map:
            return {"recommendation": None, "reason": "No performance data yet"}

        channels_to_pause: List[Dict[str, Any]] = []
        channels_performing: List[Dict[str, Any]] = []

        for ch, cb in plan.channel_budgets.items():
            if cb.status != "active":
                continue
            perf = perf_map.get(ch)
            if not perf:
                continue

            entry = {
                "channel": ch,
                "cac": perf.cac,
                "conversion_rate": perf.conversion_rate,
                "total_spend": perf.total_spend,
                "conversions": perf.conversions,
                "trend": perf.performance_trend,
            }

            should_pause = False
            if cb.min_budget > 0 and perf.total_spend < cb.min_budget:
                pass
            elif (
                cb.auto_pause_threshold > 0
                and perf.cac is not None
                and perf.cac > cb.auto_pause_threshold
            ):
                should_pause = True
            elif (
                cb.auto_pause_threshold > 0
                and perf.cac is None
                and perf.total_actions > 0
                and perf.total_spend >= cb.min_budget
                and cb.min_budget > 0
            ):
                should_pause = True

            if should_pause:
                entry["action"] = "pause"
                entry["reason"] = f"CAC exceeds threshold of {cb.auto_pause_threshold}"
                channels_to_pause.append(entry)
            else:
                entry["action"] = "keep"
                channels_performing.append(entry)

        return {
            "platform_id": platform_id,
            "strategy": plan.reallocation_strategy,
            "channels_to_pause": channels_to_pause,
            "channels_performing": channels_performing,
            "would_reallocate": len(channels_to_pause) > 0,
        }

    def get_reallocation_history(
        self,
        platform_id: str,
    ) -> List[ReallocationEvent]:
        return list(self._history.get(platform_id, []))

    def pause_channel(
        self,
        platform_id: str,
        channel: str,
    ) -> Optional[BudgetPlan]:
        plan = self._plans.get(platform_id)
        if not plan:
            return None
        cb = plan.channel_budgets.get(channel)
        if not cb:
            return None
        cb.status = "paused"
        plan.updated_at = datetime.now(timezone.utc)
        return plan

    def resume_channel(
        self,
        platform_id: str,
        channel: str,
    ) -> Optional[BudgetPlan]:
        plan = self._plans.get(platform_id)
        if not plan:
            return None
        cb = plan.channel_budgets.get(channel)
        if not cb:
            return None
        cb.status = "active"
        plan.updated_at = datetime.now(timezone.utc)
        return plan

    def stats(self) -> Dict[str, Any]:
        total_plans = len(self._plans)
        active_plans = sum(1 for p in self._plans.values() if p.status == "active")
        total_reallocations = sum(len(events) for events in self._history.values())
        total_channels_tracked = sum(
            len(channels) for channels in self._performance.values()
        )
        total_spend = sum(
            perf.total_spend
            for channels in self._performance.values()
            for perf in channels.values()
        )
        total_conversions = sum(
            perf.conversions
            for channels in self._performance.values()
            for perf in channels.values()
        )
        return {
            "total_plans": total_plans,
            "active_plans": active_plans,
            "total_reallocations": total_reallocations,
            "total_channels_tracked": total_channels_tracked,
            "total_spend": round(total_spend, 2),
            "total_conversions": total_conversions,
        }

    def _get_or_create_performance(
        self,
        platform_id: str,
        channel: str,
    ) -> ChannelPerformance:
        if channel not in self._performance[platform_id]:
            self._performance[platform_id][channel] = ChannelPerformance(
                channel=channel,
            )
        return self._performance[platform_id][channel]

    def _recompute_metrics(self, perf: ChannelPerformance) -> None:
        if perf.successful_actions > 0:
            new_rate = round(perf.conversions / perf.successful_actions, 4)
        else:
            new_rate = 0.0

        perf.conversion_rate = new_rate
        perf.cac = self._compute_cac(perf)

        perf.recent_conversion_rates.append(new_rate)
        if len(perf.recent_conversion_rates) > MAX_TREND_SAMPLES:
            perf.recent_conversion_rates = perf.recent_conversion_rates[-MAX_TREND_SAMPLES:]

        perf.performance_trend = self._detect_trend(perf)

    def _compute_cac(self, perf: ChannelPerformance) -> Optional[float]:
        if perf.conversions == 0:
            return None
        return round(perf.total_spend / perf.conversions, 2)

    def _detect_trend(self, perf: ChannelPerformance) -> str:
        rates = perf.recent_conversion_rates
        if len(rates) < 3:
            return "stable"
        recent = rates[-3:]
        if recent[-1] > recent[0]:
            return "improving"
        elif recent[-1] < recent[0]:
            return "declining"
        return "stable"

    def _allocate_freed_budget(
        self,
        freed_budget: float,
        active_channels: List[tuple],
        strategy: str,
        plan: BudgetPlan,
        changes: List[ReallocationChange],
    ) -> None:
        if strategy == "winner_takes_more":
            self._allocate_winner_takes_more(freed_budget, active_channels, plan, changes)
        elif strategy == "equal_opportunity":
            self._allocate_equal(freed_budget, active_channels, plan, changes)
        else:
            self._allocate_proportional(freed_budget, active_channels, plan, changes)

    def _allocate_proportional(
        self,
        freed_budget: float,
        active_channels: List[tuple],
        plan: BudgetPlan,
        changes: List[ReallocationChange],
    ) -> None:
        weights = []
        for ch, perf in active_channels:
            cac = perf.cac if perf.cac is not None else 0.0
            weight = (1.0 / cac) if cac > 0 else 0.0
            weights.append((ch, weight))

        total_weight = sum(w for _, w in weights)
        if total_weight == 0:
            self._allocate_equal(freed_budget, active_channels, plan, changes)
            return

        for ch, weight in weights:
            share = (weight / total_weight) * freed_budget
            if share > 0:
                cb = plan.channel_budgets[ch]
                old_budget = cb.allocated_budget
                cb.allocated_budget += share
                changes.append(
                    ReallocationChange(
                        channel=ch,
                        old_budget=old_budget,
                        new_budget=cb.allocated_budget,
                        reason=f"Proportional reallocation (+{share:.2f})",
                    )
                )

    def _allocate_winner_takes_more(
        self,
        freed_budget: float,
        active_channels: List[tuple],
        plan: BudgetPlan,
        changes: List[ReallocationChange],
    ) -> None:
        sorted_channels = sorted(
            active_channels,
            key=lambda x: x[1].cac if x[1].cac is not None else float("inf"),
        )

        splits = [0.60, 0.25, 0.15]
        for i, (ch, _perf) in enumerate(sorted_channels):
            if i < len(splits):
                share = freed_budget * splits[i]
            else:
                share = 0.0
            if share > 0:
                cb = plan.channel_budgets[ch]
                old_budget = cb.allocated_budget
                cb.allocated_budget += share
                changes.append(
                    ReallocationChange(
                        channel=ch,
                        old_budget=old_budget,
                        new_budget=cb.allocated_budget,
                        reason=f"Winner-takes-more reallocation (+{share:.2f})",
                    )
                )

    def _allocate_equal(
        self,
        freed_budget: float,
        active_channels: List[tuple],
        plan: BudgetPlan,
        changes: List[ReallocationChange],
    ) -> None:
        if not active_channels:
            return
        share = freed_budget / len(active_channels)
        for ch, _ in active_channels:
            cb = plan.channel_budgets[ch]
            old_budget = cb.allocated_budget
            cb.allocated_budget += share
            changes.append(
                ReallocationChange(
                    channel=ch,
                    old_budget=old_budget,
                    new_budget=cb.allocated_budget,
                    reason=f"Equal reallocation (+{share:.2f})",
                )
            )
