"""
UGIE Core — Decision Engine

Responsibilities:
- Evaluate behavioral profiles + predictions against registered policies
- Select the best next action for each identity
- Enforce constraints (fatigue, blackout windows, channel blocks)
- Prioritize competing actions using a scoring system
- Produce a Decision record that the action orchestrator executes
- Log all decisions for auditability and learning

The decision engine is policy-driven — not hardcoded.
Applications register policies. The engine evaluates them.
"""

from .schema import (
    Decision,
    DecisionStatus,
    ActionType,
    DecisionContext,
    DecisionOutcome,
)
from .policy import Policy, PolicyCondition, PolicyAction, PolicyRegistry
from .evaluator import PolicyEvaluator
from .engine import DecisionEngine

__all__ = [
    "Decision",
    "DecisionStatus",
    "ActionType",
    "DecisionContext",
    "DecisionOutcome",
    "Policy",
    "PolicyCondition",
    "PolicyAction",
    "PolicyRegistry",
    "PolicyEvaluator",
    "DecisionEngine",
]
