# UGIE Cold Start & Acquisition Intelligence
## Build Specification

**Status:** Planned  
**Priority:** Critical  
**Reason:** UGIE currently does nothing for platforms with zero users and nothing for new users arriving on a platform. This spec defines everything that will be built to fix that.

---

## The Problem

UGIE is currently a **reaction engine**.

It waits for users to show up. It builds profiles from their behavior. It makes predictions from those profiles. It fires decisions from those predictions.

This means:

1. A platform with **zero existing users** gets nothing from UGIE
2. A **brand new user** who just registered gets no decisions — every policy requires behavioral history that doesn't exist yet
3. UGIE cannot tell a platform **where to find users** or **who to target** before those users exist
4. UGIE has no **onboarding intelligence** — no policies fire to guide a new user to their first value moment

The vision was always different:

> When I plug in a platform, the engine should think. Not just receive instructions — but actually reason about the platform and figure everything out autonomously.

This spec defines how we build that.

---

## What Will Be Built

### 1. `core/cold_start/` — Cold Start Engine
### 2. `core/acquisition/` — Acquisition Intelligence Engine
### 3. `core/cold_start/activation.py` — New User Activation Layer
### 4. Wiring into `core/platform/`, `core/decision/`, and `api/rest/`

---

## Part 1: `core/cold_start/`

### Purpose

When a platform registers, before a single user exists, the cold start engine:

1. Classifies the platform into a domain category
2. Pulls the growth playbook for that category
3. Generates a cold-start plan (audience archetypes, channels, budget split, activation sequence)
4. Auto-registers activation policies into the decision engine
5. Returns the plan as part of the platform registration response

### Files

```
core/cold_start/
├── __init__.py
├── category.py       — CategoryClassifier + CategoryKnowledgeBase
├── playbook.py       — GrowthPlaybook per category
├── engine.py         — ColdStartEngine (orchestrates everything)
└── activation.py     — ActivationPolicyGenerator
```

---

### `core/cold_start/category.py`

#### `CategoryClassifier`

**Purpose:** Given a platform's config (name, description, entity types, events, objectives), classify it into one of the known domain categories.

**Function:** `classify(platform_config) → CategoryProfile`

**How it works:**

Reads the platform's registered entity types and objectives. Maps them to a category using a keyword and structure matching system. Falls back to `generic` if no confident match.

**Categories supported:**

| Category ID | Description | Example platforms |
|-------------|-------------|-------------------|
| `b2b_marketplace` | Two-sided B2B service marketplace | UCMC, Upwork, Fiverr |
| `b2c_marketplace` | Consumer goods or services marketplace | Airbnb, Etsy |
| `saas` | Software-as-a-service product | Any SaaS |
| `fintech_trading` | Trading, investment, prop trading | APEX TRADER, eToro |
| `fintech_payments` | Payments, wallets, remittance | Paystack, Stripe |
| `edtech` | Education and learning platforms | Coursera, Udemy |
| `healthtech` | Healthcare and wellness | Any health app |
| `ecommerce` | Online retail | Shopify stores |
| `social` | Social networks, communities | Any social app |
| `developer_tools` | APIs, SDKs, dev infrastructure | Any dev tool |
| `generic` | Fallback when category unclear | Any other |

**Output: `CategoryProfile`**

```python
class CategoryProfile:
    category_id: str              # e.g. "b2b_marketplace"
    confidence: float             # 0.0 → 1.0
    matched_signals: List[str]    # what signals led to this classification
    fallback: bool                # True if we fell back to generic
```

---

#### `CategoryKnowledgeBase`

**Purpose:** Stores everything the engine knows about growth patterns per category. This is the category-level intelligence the engine reasons from before any platform data exists.

**Structure per category:**

```python
class CategoryKnowledge:
    category_id: str

    # Who the users are
    audience_archetypes: List[AudienceArchetype]

    # Where to find them
    acquisition_channels: List[ChannelRecommendation]

    # Default budget split across channels
    default_budget_split: Dict[str, float]

    # What the typical activation bottleneck is
    activation_bottleneck: str

    # What "first value moment" looks like
    first_value_moment: str

    # How long cold start typically takes before data is meaningful
    cold_start_window_days: int

    # Typical CAC range for this category
    typical_cac_range: Tuple[float, float]

    # What events signal activation
    activation_events: List[str]

    # What events signal churn risk in early stage
    early_churn_signals: List[str]

    # KPIs that matter for this category
    primary_kpis: List[str]
```

**`AudienceArchetype`** — one target persona:

```python
class AudienceArchetype:
    name: str                         # e.g. "SME Founder"
    description: str
    age_range: Tuple[int, int]
    job_titles: List[str]
    interests: List[str]
    pain_points: List[str]
    channels: List[str]               # where this persona lives
    message_tone: str                 # "professional" | "casual" | "urgent"
    primary_motivation: str           # why they would use this platform
```

**`ChannelRecommendation`**:

```python
class ChannelRecommendation:
    channel: str                      # "linkedin" | "google_search" | "meta" | "content" | "referral" | "community"
    priority: int                     # 1 = highest
    rationale: str
    audience_fit: float               # 0.0 → 1.0
    cost_tier: str                    # "low" | "medium" | "high"
    time_to_results: str              # "immediate" | "weeks" | "months"
    recommended_budget_pct: float
```

**Knowledge base is seeded for all 11 categories at engine init.** No external calls. Pure reasoning from category knowledge.

---

### `core/cold_start/playbook.py`

#### `GrowthPlaybook`

**Purpose:** A complete growth playbook for one platform at one stage of maturity. Generated by the cold start engine, consumed by the acquisition engine and the activation layer.

```python
class GrowthPlaybook:
    platform_id: str
    category: CategoryProfile
    generated_at: datetime
    stage: str                        # "pre_launch" | "early" | "growth" | "scale"

    # Audience
    target_archetypes: List[AudienceArchetype]
    primary_archetype: AudienceArchetype

    # Acquisition
    acquisition_channels: List[ChannelRecommendation]
    budget_split: Dict[str, float]
    estimated_cac: float

    # Activation
    activation_bottleneck: str
    first_value_moment: str
    activation_sequence: List[ActivationStep]

    # Messaging
    value_proposition: str
    primary_messages: List[MessageTemplate]

    # Policies
    recommended_policies: List[PolicySpec]

    # KPIs to track
    success_metrics: List[str]
    cold_start_window_days: int
```

**`ActivationStep`:**

```python
class ActivationStep:
    day: int                          # Day 0, 1, 3, 7, 14...
    trigger: str                      # what triggers this step
    condition: str                    # what must be true
    action_type: str                  # SEND_EMAIL | SHOW_ONBOARDING | etc.
    message_template: str
    abort_if: List[str]               # cancel if these events fire first
    goal: str                         # what this step is trying to achieve
```

---

#### `PlaybookGenerator`

**Function:** `generate(platform_config, category_profile) → GrowthPlaybook`

**How it works:**

1. Pulls `CategoryKnowledge` for the classified category
2. Maps platform's declared objectives to the closest category archetypes
3. Selects top 2-3 audience archetypes
4. Builds acquisition channel list weighted by category + declared regions
5. Generates activation sequence from category's `activation_events` + `first_value_moment`
6. Builds `PolicySpec` list for each step in the activation sequence
7. Returns the complete playbook

---

### `core/cold_start/engine.py`

#### `ColdStartEngine`

**Purpose:** Top-level orchestrator. Called once when a platform registers.

**Function:** `run(platform_config) → ColdStartResult`

```python
class ColdStartResult:
    platform_id: str
    category: CategoryProfile
    playbook: GrowthPlaybook
    policies_registered: int          # how many activation policies were auto-registered
    acquisition_plan: AcquisitionPlan # from acquisition engine
    ran_at: datetime
```

**Pipeline:**

```
PlatformConfig
      │
      ▼
CategoryClassifier.classify()
      │
      ▼
CategoryKnowledgeBase.get(category_id)
      │
      ▼
PlaybookGenerator.generate()
      │
      ├──→ ActivationPolicyGenerator.generate_policies()
      │         └──→ PolicyRegistry.register() [auto-registers all activation policies]
      │
      ├──→ AcquisitionEngine.build_plan()
      │
      └──→ ColdStartResult
```

---

### `core/cold_start/activation.py`

#### `ActivationPolicyGenerator`

**Purpose:** Converts an activation sequence from a playbook into real `Policy` objects and registers them into the decision engine.

**Function:** `generate_policies(playbook, policy_registry) → List[Policy]`

**What policies it generates per category (example for `b2b_marketplace`):**

| Policy Name | Trigger | Condition | Action |
|-------------|---------|-----------|--------|
| `Welcome & Profile Completion` | `USER_REGISTERED` | `total_sessions == 0` | `SHOW_ONBOARDING` |
| `First Listing Nudge` | `SESSION_STARTED` | `total_sessions == 1`, `entity_type == Seller` | `SEND_EMAIL` template=`first_listing` |
| `Buyer First Search Nudge` | `SESSION_STARTED` | `total_sessions == 1`, `entity_type == Buyer` | `SHOW_RECOMMENDATION` |
| `48h No Return` | scheduled | `days_inactive >= 2`, `total_sessions == 1` | `SEND_EMAIL` template=`come_back` |
| `7 Day Cold Reactivation` | scheduled | `days_inactive >= 7`, `total_sessions < 3` | `SEND_EMAIL` template=`social_proof` |
| `First Transaction Celebration` | `PAYMENT_COMPLETED` | `total_conversions == 1` | `SEND_EMAIL` template=`first_win` |
| `Post-First-Win Referral` | `PAYMENT_COMPLETED` | `total_conversions == 1` | `SEND_EMAIL` template=`refer_a_friend` delay=48h |
| `Review Request` | `ORDER_COMPLETED` | `total_conversions >= 1`, `fraud_score < 0.3` | `REQUEST_REVIEW` delay=24h |

**Key design principle:** All activation policies have `abort_if` conditions — if the user completes the target action before the delayed message fires, the message is cancelled.

**Policy priority ladder:**

```
100  Fraud flag (always highest)
 90  Onboarding (new user — most urgent)
 80  48h re-engagement (before they forget)
 70  7-day reactivation
 60  Upsell (existing active users)
 50  Referral ask
 40  Review request
```

---

## Part 2: `core/acquisition/`

### Purpose

The acquisition engine answers: *Where do we find users and what do we say to them?*

It operates in two modes:

**Cold mode (no users yet):** Generates targeting specs from category knowledge alone.

**Warm mode (users exist):** Augments category specs with real behavioral data — top-performing segments, lookalike seeds, message optimizations.

### Files

```
core/acquisition/
├── __init__.py
├── schema.py         — AcquisitionPlan, AudienceSpec, AdCreativeSpec, ChannelPlan
├── engine.py         — AcquisitionEngine
├── targeting.py      — TargetingSpecBuilder
└── messaging.py      — MessageTemplateEngine
```

---

### `core/acquisition/schema.py`

```python
class AcquisitionPlan:
    platform_id: str
    stage: str                          # "cold" | "warm"
    generated_at: datetime
    channel_plans: List[ChannelPlan]
    total_recommended_budget: Optional[float]
    estimated_cac: Optional[float]
    seed_audiences: List[AudienceSpec]
    creative_specs: List[AdCreativeSpec]
    lookalike_seeds: List[LookalikeSpec]  # empty in cold mode

class ChannelPlan:
    channel: str
    priority: int
    recommended_budget_pct: float
    targeting: AudienceSpec
    creative: AdCreativeSpec
    expected_cac_range: Tuple[float, float]
    rationale: str

class AudienceSpec:
    name: str
    description: str
    age_min: int
    age_max: int
    interests: List[str]
    job_titles: List[str]
    locations: List[str]
    platforms: List[str]
    estimated_size: Optional[int]
    source: str                         # "category_knowledge" | "behavioral_data"

class AdCreativeSpec:
    channel: str
    format: str                         # "single_image" | "carousel" | "video" | "search_text"
    headline: str
    body: str
    cta: str
    tone: str
    value_prop: str

class LookalikeSpec:
    source_audience: str                # e.g. "top_10pct_buyers_by_ltv"
    seed_identity_ids: List[str]        # from behavioral profiles
    platform: str                       # "meta" | "google" | "tiktok"
    similarity_pct: int                 # 1-10
```

---

### `core/acquisition/engine.py`

#### `AcquisitionEngine`

**Function:** `build_plan(platform_id, playbook, behavior_repo) → AcquisitionPlan`

**Cold mode logic:**

1. Pull audience archetypes from playbook
2. For each top-priority channel, build `AudienceSpec` from archetype data
3. Generate `AdCreativeSpec` per channel using `MessageTemplateEngine`
4. Return `AcquisitionPlan` with `stage="cold"`, `lookalike_seeds=[]`

**Warm mode logic (called after users exist):**

1. Same as cold, plus:
2. Pull behavioral profiles from `BehaviorRepository`
3. Find top 10% by LTV → build `LookalikeSpec` for Meta/Google
4. Find `rfm_segment == "champions"` → seed for lookalike
5. Pull `top_interests` from profiles → augment interest targeting
6. Compare actual CAC from `BudgetAllocator` → update `expected_cac_range`

**Function:** `refresh_plan(platform_id) → AcquisitionPlan`

Called periodically (weekly) or when enough new users have arrived. Updates the plan from warm mode data.

---

### `core/acquisition/targeting.py`

#### `TargetingSpecBuilder`

**Function:** `build(archetype, channel, regions) → AudienceSpec`

Translates a category-level `AudienceArchetype` into a channel-specific targeting spec.

Channel-specific transformations:

| Channel | What it produces |
|---------|-----------------|
| `linkedin` | Job titles, seniority levels, company size, industries |
| `meta` | Interest categories, behavior signals, age/gender |
| `google_search` | Keyword themes, match types, negative keywords |
| `tiktok` | Interest categories, hashtag themes, creator niches |

---

### `core/acquisition/messaging.py`

#### `MessageTemplateEngine`

**Function:** `generate(archetype, channel, stage, value_prop) → AdCreativeSpec`

Generates ad creative specs from archetype + channel + stage.

**Stage-based messaging:**

| Stage | Message focus |
|-------|--------------|
| `awareness` | Pain point + category credibility |
| `consideration` | Differentiation + social proof |
| `conversion` | Offer + urgency + risk reduction |
| `retention` | Value reinforcement + upsell |

**Tone matched to archetype:**

- B2B decision makers → professional, ROI-focused
- Consumers → emotional, benefit-focused
- Developers → direct, technical, no fluff

---

## Part 3: Wiring

### `core/platform/registry.py`

**Change:** `register()` now calls `ColdStartEngine.run()` after platform creation.

```python
def register(self, name, slug, owner_email, config) -> tuple[Platform, str, ColdStartResult]:
    # ... existing registration logic ...
    cold_start_result = self._cold_start_engine.run(config)
    return platform, api_key, cold_start_result
```

### `core/decision/engine.py`

**Change:** `DecisionEngine` receives activation policies from `ColdStartEngine` automatically. No manual policy registration needed for standard activation flows.

### `api/rest/routes/platforms.py`

**Change:** Platform registration endpoint returns `cold_start_result` in the response body.

```json
POST /api/v1/platforms/register
→ 201 Created
{
  "platform": { ... },
  "api_key": "ugie_...",
  "cold_start": {
    "category": "b2b_marketplace",
    "confidence": 0.91,
    "playbook": { ... },
    "policies_registered": 8,
    "acquisition_plan": { ... }
  }
}
```

### `api/rest/routes/` — New endpoints

```
GET  /api/v1/platforms/{id}/cold-start        — fetch current cold start plan
GET  /api/v1/platforms/{id}/acquisition-plan  — fetch current acquisition plan
POST /api/v1/platforms/{id}/acquisition-plan/refresh  — force warm-mode refresh
GET  /api/v1/platforms/{id}/playbook          — fetch growth playbook
```

---

## Part 4: Tests

### Unit tests

```
tests/unit/test_cold_start_category.py
  - CategoryClassifier correctly classifies all 11 category types
  - Falls back to generic when signals are ambiguous
  - Confidence score reflects match quality

tests/unit/test_cold_start_playbook.py
  - PlaybookGenerator produces valid playbook for each category
  - Activation sequence has correct ordering and abort conditions
  - Budget split sums to 1.0

tests/unit/test_cold_start_engine.py
  - ColdStartEngine.run() returns complete ColdStartResult
  - Policies are registered into decision engine after run
  - Cold start result includes acquisition plan

tests/unit/test_activation_policies.py
  - Activation policies fire on USER_REGISTERED for new users
  - Policies have correct abort_if conditions
  - Priority ladder is correct
  - 48h re-engagement fires when user doesn't return
  - First transaction celebration fires on first conversion

tests/unit/test_acquisition_engine.py
  - Cold mode plan generated without any behavioral data
  - Warm mode augments with lookalike seeds when users exist
  - TargetingSpecBuilder produces channel-specific targeting
  - MessageTemplateEngine produces stage-appropriate creative

tests/unit/test_acquisition_targeting.py
  - LinkedIn targeting includes job titles and seniority
  - Meta targeting includes interests and age range
  - Google targeting includes keyword themes
```

### Integration tests

```
tests/integration/test_cold_start_flow.py
  - Register a b2b_marketplace platform with zero users
  - Verify ColdStartResult returned
  - Verify 8+ activation policies auto-registered
  - Submit USER_REGISTERED event for first user
  - Verify decision fires (SHOW_ONBOARDING)
  - Submit SESSION_STARTED
  - Verify onboarding nudge decision fires
  - Submit PAYMENT_COMPLETED
  - Verify first transaction celebration fires
  - Verify review request fires after 24h delay
  - Verify referral ask fires after 48h delay

tests/integration/test_acquisition_plan_refresh.py
  - Register platform, get cold plan
  - Add 20 users with behavioral data
  - Refresh acquisition plan
  - Verify warm mode activated
  - Verify lookalike seeds populated from top LTV users
  - Verify channel targeting updated with real interest data
```

---

## Data Flow Summary

```
Platform Registration
        │
        ▼
ColdStartEngine.run(platform_config)
        │
        ├──→ CategoryClassifier.classify()
        │           └── CategoryProfile (category_id, confidence)
        │
        ├──→ CategoryKnowledgeBase.get(category_id)
        │           └── CategoryKnowledge (archetypes, channels, activation events)
        │
        ├──→ PlaybookGenerator.generate()
        │           └── GrowthPlaybook (full activation sequence + messaging)
        │
        ├──→ ActivationPolicyGenerator.generate_policies()
        │           └── List[Policy] → auto-registered in PolicyRegistry
        │
        ├──→ AcquisitionEngine.build_plan() [cold mode]
        │           └── AcquisitionPlan (channel plans, audience specs, creatives)
        │
        └──→ ColdStartResult returned to API caller


First User Registers
        │
        ▼
USER_REGISTERED event hits EventBus
        │
        ▼
DecisionEngine.decide()
        │
        ▼
ActivationPolicy "Welcome & Profile Completion" fires
        │
        ▼
ActionOrchestrator dispatches SHOW_ONBOARDING
        │
        ▼
Feedback event published → BehaviorBuilder updates profile
        │
        ▼
Next event → next decision → loop continues


Users Accumulate (>50 profiles)
        │
        ▼
AcquisitionEngine.refresh_plan() [warm mode]
        │
        ├── Pull top 10% LTV users → LookalikeSpec for Meta/Google
        ├── Pull top interests from profiles → augment targeting
        ├── Pull actual CAC from BudgetAllocator → update estimates
        └── Return updated AcquisitionPlan
```

---

## File Creation Order

```
1. core/cold_start/__init__.py
2. core/cold_start/category.py          — CategoryClassifier + CategoryKnowledgeBase
3. core/cold_start/playbook.py          — GrowthPlaybook + PlaybookGenerator
4. core/cold_start/activation.py        — ActivationPolicyGenerator
5. core/cold_start/engine.py            — ColdStartEngine
6. core/acquisition/__init__.py
7. core/acquisition/schema.py           — AcquisitionPlan + all sub-schemas
8. core/acquisition/targeting.py        — TargetingSpecBuilder
9. core/acquisition/messaging.py        — MessageTemplateEngine
10. core/acquisition/engine.py          — AcquisitionEngine
11. Wire core/platform/registry.py
12. Wire core/decision/engine.py
13. Wire api/rest/routes/platforms.py
14. Add new API routes
15. tests/unit/ (6 test files)
16. tests/integration/ (2 test files)
```

---

## What Changes After This Is Built

**Before:**
- Platform registers → gets nothing useful → waits for users → still does nothing for new users

**After:**
- Platform registers → instantly gets category classification, growth playbook, acquisition plan with audience specs and ad creatives, and 8+ activation policies auto-wired into the decision engine
- First user registers → engine immediately fires onboarding decision
- First session → activation nudge
- No return after 48h → re-engagement fires
- First conversion → celebration + referral ask + review request (all timed, all auto-cancelled if the user acts first)
- 50+ users exist → acquisition plan upgrades to warm mode with real lookalike seeds

UGIE becomes a genuine intelligence engine — not just a reaction system.
