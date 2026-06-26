"""
Entity State Machine

Every entity type can have a state machine that defines:
- What states are valid
- What transitions are allowed between states
- What events trigger which transitions
- What actions to take on transition

Example for a Seller entity:
    onboarding → profile_complete → kyc_pending → active → suspended

The state machine is policy-driven and defined per entity type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .schema import Entity

logger = logging.getLogger(__name__)


@dataclass
class StateTransition:
    """
    Defines a valid transition between two states.

    Example:
        StateTransition(
            from_state="onboarding",
            to_state="active",
            trigger_events=["KYC_COMPLETED", "PROFILE_COMPLETED"],
            condition=lambda entity: entity.get_attribute("kyc_verified") is True,
        )
    """
    from_state: str
    to_state: str
    trigger_events: List[str] = field(default_factory=list)
    label: str = ""
    condition: Optional[Callable[[Entity], bool]] = None
    on_enter: Optional[Callable[[Entity], None]] = None


@dataclass
class StateMachineDefinition:
    """
    Full state machine definition for one entity type.
    """
    application_id: str
    type_name: str
    initial_state: str
    states: List[str] = field(default_factory=list)
    transitions: List[StateTransition] = field(default_factory=list)

    def key(self) -> str:
        return f"{self.application_id}:{self.type_name}"

    def transitions_from(self, state: str) -> List[StateTransition]:
        return [t for t in self.transitions if t.from_state == state]

    def transitions_for_event(self, state: str, event_type: str) -> List[StateTransition]:
        return [
            t for t in self.transitions_from(state)
            if event_type in t.trigger_events
        ]


class TransitionResult:
    def __init__(
        self,
        success: bool,
        entity: Entity,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        reason: str = "",
    ):
        self.success = success
        self.entity = entity
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason


class EntityStateMachine:
    """
    Manages state transitions for entities.

    Usage:
        sm = EntityStateMachine()

        sm.register(StateMachineDefinition(
            application_id="ucmc",
            type_name="Seller",
            initial_state="onboarding",
            states=["onboarding", "active", "suspended"],
            transitions=[
                StateTransition(
                    from_state="onboarding",
                    to_state="active",
                    trigger_events=["KYC_COMPLETED"],
                ),
            ]
        ))

        result = sm.process_event(entity, "KYC_COMPLETED")
    """

    def __init__(self):
        self._machines: Dict[str, StateMachineDefinition] = {}
        self._seed_builtin_machines()

    def register(self, definition: StateMachineDefinition) -> None:
        self._machines[definition.key()] = definition
        logger.info(
            f"Registered state machine | "
            f"app={definition.application_id} type={definition.type_name} "
            f"states={definition.states}"
        )

    def get(self, application_id: str, type_name: str) -> Optional[StateMachineDefinition]:
        # Try exact match first, then wildcard
        return (
            self._machines.get(f"{application_id}:{type_name}")
            or self._machines.get(f"*:{type_name}")
        )

    def process_event(
        self,
        entity: Entity,
        event_type: str,
        triggered_by: Optional[str] = None,
    ) -> TransitionResult:
        """
        Process an event against the entity's current state.
        If a valid transition exists, apply it and return the result.
        """
        machine = self.get(entity.application_id, entity.type_name)

        if not machine:
            return TransitionResult(
                success=False,
                entity=entity,
                reason=f"No state machine for {entity.application_id}:{entity.type_name}",
            )

        current_state = entity.state or machine.initial_state
        transitions = machine.transitions_for_event(current_state, event_type)

        if not transitions:
            logger.debug(
                f"No transition for event '{event_type}' from state "
                f"'{current_state}' on {entity.type_name}:{entity.id}"
            )
            return TransitionResult(
                success=False,
                entity=entity,
                from_state=current_state,
                reason=f"No transition defined for event '{event_type}' from '{current_state}'",
            )

        # Take the first matching transition whose condition passes
        for transition in transitions:
            if transition.condition and not transition.condition(entity):
                logger.debug(
                    f"Transition condition failed: {current_state} → {transition.to_state}"
                )
                continue

            # Apply the transition
            entity.transition_state(transition.to_state, triggered_by=triggered_by)

            # Run on_enter hook if defined
            if transition.on_enter:
                try:
                    transition.on_enter(entity)
                except Exception as e:
                    logger.error(
                        f"on_enter hook failed for transition "
                        f"{current_state}→{transition.to_state}: {e}"
                    )

            logger.info(
                f"State transition | entity={entity.id} type={entity.type_name} "
                f"{current_state} → {transition.to_state} via '{event_type}'"
            )

            return TransitionResult(
                success=True,
                entity=entity,
                from_state=current_state,
                to_state=transition.to_state,
            )

        return TransitionResult(
            success=False,
            entity=entity,
            from_state=current_state,
            reason="All matching transitions failed their conditions",
        )

    def initialize_state(self, entity: Entity) -> Entity:
        """Set initial state on a newly created entity."""
        machine = self.get(entity.application_id, entity.type_name)
        if machine and not entity.state:
            entity.transition_state(machine.initial_state, triggered_by="system")
        return entity

    # ------------------------------------------------------------------
    # Built-in state machines
    # ------------------------------------------------------------------

    def _seed_builtin_machines(self) -> None:
        """Seed common state machines for built-in entity types."""
        self.register(StateMachineDefinition(
            application_id="*",
            type_name="User",
            initial_state="registered",
            states=["registered", "active", "churned", "suspended", "deleted"],
            transitions=[
                StateTransition(
                    from_state="registered",
                    to_state="active",
                    trigger_events=["SESSION_STARTED", "PAYMENT_COMPLETED",
                                    "ORDER_CREATED", "FEATURE_USED"],
                    label="First meaningful action",
                ),
                StateTransition(
                    from_state="active",
                    to_state="churned",
                    trigger_events=["SUBSCRIPTION_CANCELLED", "ACCOUNT_DEACTIVATED"],
                    label="User churned",
                ),
                StateTransition(
                    from_state="churned",
                    to_state="active",
                    trigger_events=["SESSION_STARTED", "SUBSCRIPTION_STARTED"],
                    label="User reactivated",
                ),
                StateTransition(
                    from_state="active",
                    to_state="suspended",
                    trigger_events=["ACCOUNT_DEACTIVATED"],
                    label="Account suspended",
                ),
            ]
        ))
