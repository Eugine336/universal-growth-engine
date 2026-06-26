# UGIE Architecture

## Philosophy

The engine should never know what business it is operating.

It only understands:
- Entities
- Events
- Relationships
- Behaviors
- Objectives
- Constraints

Everything else is configuration.

---

## Two Operating Modes

### Cold Start Mode
Before any data exists for a new application, the engine reasons from:
- Domain category (marketplace, SaaS, fintech, healthcare, etc.)
- Entity types registered
- Declared objectives
- Historical cross-platform behavioral patterns

It produces an initial growth hypothesis: likely audience archetypes, acquisition channels, activation bottlenecks, and retention levers.

### Live Mode
As events flow in, the engine:
- Validates or invalidates cold-start hypotheses
- Builds real behavioral profiles
- Trains and refines prediction models
- Continuously improves decision quality

---

## Core Pipeline

```
New Event Arrives
      │
      ▼
Identity Resolution
(Who is this person across all touchpoints?)
      │
      ▼
Entity Graph Update
(Update relationships, states, attributes)
      │
      ▼
Behavioral Profile Update
(Interests, intent, engagement, trust)
      │
      ▼
Prediction Refresh
(Churn probability, LTV, conversion, fraud)
      │
      ▼
Decision Engine
(Given context + predictions + policies → best next action)
      │
      ▼
Action Orchestrator
(Publish action to appropriate connector)
      │
      ▼
Connector Executes
(Email sent, ad adjusted, notification pushed)
      │
      ▼
Result Measured
(Open, click, conversion, bounce)
      │
      ▼
Loop Feeds Back Into Behavioral Profile
```

---

## Identity Layer

One person may arrive via:
- Google OAuth
- Email signup
- Mobile app
- API key
- Browser (anonymous)
- Multiple devices

All resolve to one persistent identity node in the graph.

Identity resolution uses:
- Deterministic matching (same email, same phone)
- Probabilistic matching (same device fingerprint, same IP + behavior pattern)

---

## Entity Model

Generic entity types. Applications register their own.

```
Entity
├── id
├── type (User | Organization | Product | Asset | Listing | ...)
├── attributes (key-value, domain-defined)
├── state (domain-defined state machine)
├── relationships []
└── created_at / updated_at
```

---

## Event Model

```
Event
├── id
├── type (ENTITY_CREATED | USER_REGISTERED | PAYMENT_COMPLETED | ...)
├── actor_entity_id
├── target_entity_id (optional)
├── properties (key-value)
├── application_id
├── session_id
├── timestamp
└── metadata
```

---

## Decision Engine

The decision engine is **policy-driven**, not hardcoded.

Policies are defined per application and override global defaults.

```
Decision = f(
  current_context,
  behavioral_profile,
  predictions,
  active_policies,
  objectives,
  constraints
)
```

Policy example:
```yaml
policy:
  name: seller_activation_nudge
  trigger:
    event: USER_REGISTERED
    entity_type: Seller
    condition: profile_completion < 50%
  wait: 24h
  action: SEND_EMAIL
  template: seller_activation_reminder
  abort_if:
    - listing_created
    - session_started
```

---

## Prediction Engine

Predictions are reusable services available to all applications.

| Prediction | Description |
|------------|-------------|
| `churn_probability` | Likelihood of disengagement in next 30 days |
| `conversion_probability` | Likelihood of completing target action |
| `ltv_forecast` | Predicted lifetime value |
| `fraud_probability` | Likelihood of fraudulent behavior |
| `upsell_probability` | Likelihood of upgrading or expanding |
| `referral_probability` | Likelihood of referring another user |
| `dispute_probability` | Likelihood of raising a dispute (marketplace) |
| `demand_forecast` | Predicted demand by category / region |

---

## Action Orchestrator

The engine publishes actions. Connectors execute them.

```
Action
├── type (SEND_EMAIL | RUN_META_CAMPAIGN | SEND_PUSH | ...)
├── target_entity_id
├── connector_id
├── payload (connector-specific)
├── scheduled_at
├── experiment_id (optional)
└── policy_id (optional)
```

The engine never directly calls external APIs.

---

## Experimentation Engine

Every action can be part of an experiment.

```
Experiment
├── id
├── name
├── type (ab_test | multiarm_bandit | audience_split)
├── variants []
├── metric (primary optimization target)
├── traffic_split
├── start_date / end_date
└── status
```

Results feed back into the decision engine to update policy weights.
