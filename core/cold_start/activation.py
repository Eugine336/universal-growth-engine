"""
Activation Policy Generator

Converts policy specs from a growth playbook into real Policy objects
and registers them into the decision engine's PolicyRegistry.
"""

from __future__ import annotations

import logging
from typing import List

from core.decision.policy import Policy, PolicyAction, PolicyCondition, PolicyRegistry
from core.decision.schema import ActionType

from .playbook import GrowthPlaybook, PolicySpec

logger = logging.getLogger(__name__)


class ActivationPolicyGenerator:

    def generate_policies(
        self,
        playbook: GrowthPlaybook,
        policy_registry: PolicyRegistry,
    ) -> List[Policy]:
        registered: List[Policy] = []

        for spec in playbook.recommended_policies:
            policy = self._spec_to_policy(spec, playbook.platform_id)
            policy_registry.register(policy)
            registered.append(policy)
            logger.info(
                "Registered activation policy '%s' for platform=%s (priority=%d)",
                policy.name,
                playbook.platform_id,
                policy.action.priority,
            )

        return registered

    def _spec_to_policy(self, spec: PolicySpec, platform_id: str) -> Policy:
        conditions = [
            PolicyCondition(
                field=c["field"],
                operator=c["operator"],
                value=c["value"],
            )
            for c in spec.conditions
        ]

        action_type = self._resolve_action_type(spec.action_type)

        action = PolicyAction(
            action_type=action_type,
            channel=spec.channel,
            payload_template=spec.payload_template,
            priority=spec.priority,
            delay_hours=spec.delay_hours,
            valid_hours=spec.valid_hours,
        )

        return Policy(
            application_id=platform_id,
            name=spec.name,
            description=spec.description,
            trigger_events=spec.trigger_events,
            conditions=conditions,
            condition_logic=spec.condition_logic,
            action=action,
            cooldown_hours=spec.cooldown_hours,
            max_executions_per_identity=spec.max_executions_per_identity,
            abort_if_events=spec.abort_if_events,
        )

    def _resolve_action_type(self, type_str: str) -> ActionType:
        try:
            return ActionType(type_str)
        except ValueError:
            logger.warning("Unknown action type '%s', falling back to NO_ACTION", type_str)
            return ActionType.NO_ACTION
