"""
Send-Time Optimizer

Optimizes when to send a communication based on the identity's behavioral patterns.

Uses engagement data from the behavioral profile:
- communication.best_hour (hour with most engagement)
- communication.best_day (day with most engagement)
- communication.hourly_engagement (engagement distribution by hour)

Called by the ActionOrchestrator BEFORE dispatching a communication action.
If the current time is not optimal, sets execute_after on the action to delay.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.action.schema import Action
from core.behavior.schema import BehavioralProfile

COMM_ACTION_TYPES = {
    "SEND_EMAIL",
    "SEND_PUSH",
    "SEND_SMS",
    "SEND_WHATSAPP",
    "SEND_IN_APP",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SendTimeOptimizer:

    def optimize(
        self,
        action: Action,
        profile: BehavioralProfile,
        now: Optional[datetime] = None,
    ) -> Action:
        if action.action_type not in COMM_ACTION_TYPES:
            return action

        optimal = self.next_optimal_time(profile, now)
        if optimal is None:
            return action

        current = now or datetime.now(timezone.utc)
        if optimal > current:
            action.execute_after = optimal

        return action

    def next_optimal_time(
        self,
        profile: BehavioralProfile,
        now: Optional[datetime] = None,
    ) -> Optional[datetime]:
        comm = profile.communication
        if comm.best_hour is None:
            return None

        current = now or datetime.now(timezone.utc)
        best_hour = comm.best_hour
        best_day = comm.best_day

        candidate = current.replace(
            hour=best_hour, minute=0, second=0, microsecond=0,
        )

        if best_day:
            target_weekday = self._day_index(best_day)
            if target_weekday is not None:
                current_weekday = current.weekday()
                days_ahead = (target_weekday - current_weekday) % 7
                if days_ahead == 0 and candidate <= current:
                    days_ahead = 7
                candidate = candidate + timedelta(days=days_ahead)
            else:
                if candidate <= current:
                    candidate += timedelta(days=1)
        else:
            if candidate <= current:
                candidate += timedelta(days=1)

        return candidate

    @staticmethod
    def _day_index(day_name: str) -> Optional[int]:
        mapping = {d.lower(): i for i, d in enumerate(DAY_NAMES)}
        return mapping.get(day_name.lower())
