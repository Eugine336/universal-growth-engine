"""
Category Classifier & Knowledge Base

Classifies platforms into domain categories and stores
growth-pattern intelligence per category.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class AudienceArchetype:
    name: str
    description: str
    age_range: Tuple[int, int]
    job_titles: List[str]
    interests: List[str]
    pain_points: List[str]
    channels: List[str]
    message_tone: str
    primary_motivation: str


@dataclass
class ChannelRecommendation:
    channel: str
    priority: int
    rationale: str
    audience_fit: float
    cost_tier: str
    time_to_results: str
    recommended_budget_pct: float


@dataclass
class CategoryKnowledge:
    category_id: str
    audience_archetypes: List[AudienceArchetype]
    acquisition_channels: List[ChannelRecommendation]
    default_budget_split: Dict[str, float]
    activation_bottleneck: str
    first_value_moment: str
    cold_start_window_days: int
    typical_cac_range: Tuple[float, float]
    activation_events: List[str]
    early_churn_signals: List[str]
    primary_kpis: List[str]


@dataclass
class CategoryProfile:
    category_id: str
    confidence: float
    matched_signals: List[str]
    fallback: bool


_CATEGORY_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "b2b_marketplace": {
        "entities": ["seller", "buyer", "listing", "order", "escrow", "dispute", "vendor", "merchant", "provider", "freelancer"],
        "objectives": ["gmv", "liquidity", "match", "marketplace", "two-sided", "commission", "transaction"],
    },
    "b2c_marketplace": {
        "entities": ["seller", "buyer", "listing", "product", "review", "wishlist", "cart"],
        "objectives": ["consumer", "retail", "shopping", "b2c", "consumer marketplace"],
    },
    "saas": {
        "entities": ["user", "workspace", "team", "subscription", "plan", "feature", "tenant", "organization"],
        "objectives": ["activation", "retention", "mrr", "arr", "churn", "usage", "trial", "conversion", "saas"],
    },
    "fintech_trading": {
        "entities": ["trader", "account", "position", "portfolio", "trade", "order", "instrument", "fund"],
        "objectives": ["trading", "investment", "portfolio", "prop", "aum", "returns", "profit"],
    },
    "fintech_payments": {
        "entities": ["wallet", "payment", "transfer", "remittance", "payout", "merchant", "settlement"],
        "objectives": ["payments", "tpv", "remittance", "wallet", "settlement", "disbursement"],
    },
    "edtech": {
        "entities": ["student", "course", "lesson", "instructor", "enrollment", "certificate", "quiz", "module"],
        "objectives": ["learning", "completion", "enrollment", "education", "curriculum", "certification"],
    },
    "healthtech": {
        "entities": ["patient", "appointment", "provider", "prescription", "record", "consultation", "workout", "member"],
        "objectives": ["health", "wellness", "fitness", "appointment", "care", "treatment", "medical"],
    },
    "ecommerce": {
        "entities": ["product", "cart", "order", "customer", "category", "inventory", "shipping", "return"],
        "objectives": ["revenue", "aov", "conversion", "cart", "purchase", "ecommerce", "retail"],
    },
    "social": {
        "entities": ["user", "post", "comment", "follow", "group", "community", "message", "feed", "story"],
        "objectives": ["engagement", "dau", "mau", "content", "community", "social", "virality"],
    },
    "developer_tools": {
        "entities": ["developer", "api", "project", "key", "endpoint", "webhook", "integration", "repository"],
        "objectives": ["api", "sdk", "integration", "developer", "adoption", "calls", "requests"],
    },
}


class CategoryClassifier:

    def classify(
        self,
        name: str = "",
        description: str = "",
        entity_types: Optional[List[str]] = None,
        objectives: Optional[List[str]] = None,
        category_hint: str = "",
    ) -> CategoryProfile:
        if category_hint and category_hint in _CATEGORY_KEYWORDS:
            return CategoryProfile(
                category_id=category_hint,
                confidence=1.0,
                matched_signals=[f"explicit_hint:{category_hint}"],
                fallback=False,
            )

        all_text = " ".join([
            name.lower(),
            description.lower(),
            " ".join(e.lower() for e in (entity_types or [])),
            " ".join(o.lower() for o in (objectives or [])),
        ])

        scores: Dict[str, Tuple[float, List[str]]] = {}
        for cat_id, keywords in _CATEGORY_KEYWORDS.items():
            matched: List[str] = []
            for kw in keywords.get("entities", []):
                if kw in all_text:
                    matched.append(f"entity:{kw}")
            for kw in keywords.get("objectives", []):
                if kw in all_text:
                    matched.append(f"objective:{kw}")
            if matched:
                total_kw = len(keywords.get("entities", [])) + len(keywords.get("objectives", []))
                scores[cat_id] = (len(matched) / total_kw, matched)

        if not scores:
            return CategoryProfile(
                category_id="generic",
                confidence=0.0,
                matched_signals=[],
                fallback=True,
            )

        best = max(scores, key=lambda k: scores[k][0])
        conf, signals = scores[best]

        if best == "b2c_marketplace" and "b2b_marketplace" in scores:
            b2b_conf = scores["b2b_marketplace"][0]
            if b2b_conf > conf:
                best = "b2b_marketplace"
                conf, signals = scores[best]

        return CategoryProfile(
            category_id=best,
            confidence=min(conf * 2.0, 1.0),
            matched_signals=signals,
            fallback=False,
        )


class CategoryKnowledgeBase:

    def __init__(self):
        self._knowledge: Dict[str, CategoryKnowledge] = {}
        self._seed()

    def get(self, category_id: str) -> Optional[CategoryKnowledge]:
        return self._knowledge.get(category_id) or self._knowledge.get("generic")

    def list_categories(self) -> List[str]:
        return list(self._knowledge.keys())

    def _seed(self) -> None:
        self._knowledge["b2b_marketplace"] = CategoryKnowledge(
            category_id="b2b_marketplace",
            audience_archetypes=[
                AudienceArchetype(
                    name="SME Founder",
                    description="Small-medium business owner looking for professional services",
                    age_range=(28, 50),
                    job_titles=["CEO", "Founder", "Managing Director", "Business Owner"],
                    interests=["entrepreneurship", "business growth", "outsourcing", "technology"],
                    pain_points=["finding reliable service providers", "vetting quality", "managing contracts"],
                    channels=["linkedin", "google_search", "whatsapp"],
                    message_tone="professional",
                    primary_motivation="Find vetted service providers to grow their business",
                ),
                AudienceArchetype(
                    name="Professional Freelancer",
                    description="Skilled service provider seeking clients and projects",
                    age_range=(22, 40),
                    job_titles=["Freelancer", "Consultant", "Developer", "Designer", "Specialist"],
                    interests=["freelancing", "remote work", "professional development", "networking"],
                    pain_points=["finding clients", "payment security", "building reputation"],
                    channels=["linkedin", "twitter", "community"],
                    message_tone="professional",
                    primary_motivation="Access a steady pipeline of quality clients",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="linkedin", priority=1, rationale="Decision-makers and professionals live here", audience_fit=0.9, cost_tier="medium", time_to_results="weeks", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="google_search", priority=2, rationale="High-intent searches for services", audience_fit=0.85, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="content", priority=3, rationale="Build authority with case studies and guides", audience_fit=0.7, cost_tier="low", time_to_results="months", recommended_budget_pct=0.15),
                ChannelRecommendation(channel="referral", priority=4, rationale="Trust-based marketplace, referrals convert highest", audience_fit=0.95, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.20),
            ],
            default_budget_split={"linkedin": 0.35, "google_search": 0.30, "content": 0.15, "referral": 0.20},
            activation_bottleneck="Profile completion and first listing/search",
            first_value_moment="First successful transaction between buyer and seller",
            cold_start_window_days=30,
            typical_cac_range=(15.0, 80.0),
            activation_events=["USER_REGISTERED", "PROFILE_COMPLETED", "LISTING_CREATED", "SEARCH_PERFORMED", "PAYMENT_COMPLETED"],
            early_churn_signals=["no_profile_completion_48h", "no_listing_7d", "no_search_3d", "single_session_bounce"],
            primary_kpis=["gmv", "take_rate", "buyer_seller_ratio", "repeat_transaction_rate"],
        )

        self._knowledge["b2c_marketplace"] = CategoryKnowledge(
            category_id="b2c_marketplace",
            audience_archetypes=[
                AudienceArchetype(
                    name="Savvy Shopper",
                    description="Consumer looking for unique or affordable products",
                    age_range=(18, 45),
                    job_titles=[],
                    interests=["shopping", "deals", "unique products", "handmade"],
                    pain_points=["finding unique items", "trusting online sellers", "getting fair prices"],
                    channels=["meta", "tiktok", "google_search"],
                    message_tone="casual",
                    primary_motivation="Discover unique products at great prices",
                ),
                AudienceArchetype(
                    name="Side Hustle Seller",
                    description="Individual or small creator selling goods online",
                    age_range=(20, 40),
                    job_titles=["Creator", "Artisan", "Small Business Owner"],
                    interests=["crafts", "small business", "ecommerce", "side income"],
                    pain_points=["reaching customers", "handling logistics", "low margins"],
                    channels=["meta", "tiktok", "community"],
                    message_tone="casual",
                    primary_motivation="Reach more customers and grow sales",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="meta", priority=1, rationale="Visual discovery and consumer targeting", audience_fit=0.9, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.40),
                ChannelRecommendation(channel="tiktok", priority=2, rationale="Viral product discovery", audience_fit=0.85, cost_tier="low", time_to_results="immediate", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="google_search", priority=3, rationale="Product search intent", audience_fit=0.75, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.20),
                ChannelRecommendation(channel="referral", priority=4, rationale="Word of mouth drives marketplace trust", audience_fit=0.8, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"meta": 0.40, "tiktok": 0.25, "google_search": 0.20, "referral": 0.15},
            activation_bottleneck="First browse and add-to-cart",
            first_value_moment="First purchase completed",
            cold_start_window_days=21,
            typical_cac_range=(5.0, 35.0),
            activation_events=["USER_REGISTERED", "PRODUCT_VIEWED", "ITEM_ADDED_TO_CART", "PAYMENT_COMPLETED"],
            early_churn_signals=["no_browse_24h", "cart_abandoned", "single_session_bounce"],
            primary_kpis=["gmv", "conversion_rate", "aov", "repeat_purchase_rate"],
        )

        self._knowledge["saas"] = CategoryKnowledge(
            category_id="saas",
            audience_archetypes=[
                AudienceArchetype(
                    name="Tech Decision Maker",
                    description="VP/Director evaluating software solutions",
                    age_range=(30, 55),
                    job_titles=["VP Engineering", "CTO", "Director of Product", "Head of Operations"],
                    interests=["productivity", "automation", "digital transformation", "saas tools"],
                    pain_points=["manual processes", "scaling operations", "tool consolidation"],
                    channels=["linkedin", "google_search", "content"],
                    message_tone="professional",
                    primary_motivation="Find tools that save time and reduce operational costs",
                ),
                AudienceArchetype(
                    name="Individual Contributor",
                    description="End-user who benefits from the tool daily",
                    age_range=(22, 40),
                    job_titles=["Developer", "Designer", "Analyst", "Marketer", "PM"],
                    interests=["productivity", "workflow optimization", "new tools"],
                    pain_points=["repetitive tasks", "poor existing tools", "collaboration friction"],
                    channels=["content", "community", "google_search"],
                    message_tone="casual",
                    primary_motivation="Work faster and more effectively",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="High-intent solution searches", audience_fit=0.9, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="content", priority=2, rationale="SEO + thought leadership drives SaaS adoption", audience_fit=0.85, cost_tier="low", time_to_results="months", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="linkedin", priority=3, rationale="B2B decision-maker targeting", audience_fit=0.8, cost_tier="medium", time_to_results="weeks", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="referral", priority=4, rationale="Product-led growth via user referrals", audience_fit=0.75, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"google_search": 0.35, "content": 0.25, "linkedin": 0.25, "referral": 0.15},
            activation_bottleneck="First meaningful use of core feature",
            first_value_moment="User completes their first workflow or achieves aha-moment",
            cold_start_window_days=14,
            typical_cac_range=(30.0, 200.0),
            activation_events=["USER_REGISTERED", "FEATURE_USED", "WORKSPACE_CREATED", "INVITE_SENT"],
            early_churn_signals=["no_feature_use_3d", "no_return_7d", "trial_expiring_no_activity"],
            primary_kpis=["mrr", "trial_to_paid_rate", "dau_mau_ratio", "net_revenue_retention"],
        )

        self._knowledge["fintech_trading"] = CategoryKnowledge(
            category_id="fintech_trading",
            audience_archetypes=[
                AudienceArchetype(
                    name="Retail Trader",
                    description="Individual investor or active trader",
                    age_range=(22, 45),
                    job_titles=["Trader", "Investor", "Analyst"],
                    interests=["trading", "stocks", "crypto", "forex", "investing", "markets"],
                    pain_points=["high fees", "poor execution", "limited instruments", "complex platforms"],
                    channels=["google_search", "meta", "community"],
                    message_tone="professional",
                    primary_motivation="Access better trading tools and lower fees",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="'Best trading platform' searches", audience_fit=0.9, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.40),
                ChannelRecommendation(channel="community", priority=2, rationale="Trading communities and forums", audience_fit=0.85, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="meta", priority=3, rationale="Retargeting and lookalikes", audience_fit=0.7, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.20),
                ChannelRecommendation(channel="referral", priority=4, rationale="Trader referral programs", audience_fit=0.8, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"google_search": 0.40, "community": 0.25, "meta": 0.20, "referral": 0.15},
            activation_bottleneck="KYC completion and first deposit",
            first_value_moment="First trade executed",
            cold_start_window_days=14,
            typical_cac_range=(50.0, 300.0),
            activation_events=["USER_REGISTERED", "KYC_COMPLETED", "DEPOSIT_MADE", "TRADE_EXECUTED"],
            early_churn_signals=["kyc_not_completed_48h", "no_deposit_7d", "no_trade_14d"],
            primary_kpis=["aum", "trade_volume", "deposit_rate", "active_traders"],
        )

        self._knowledge["fintech_payments"] = CategoryKnowledge(
            category_id="fintech_payments",
            audience_archetypes=[
                AudienceArchetype(
                    name="SME Merchant",
                    description="Business accepting digital payments",
                    age_range=(25, 50),
                    job_titles=["Business Owner", "Finance Manager", "CFO"],
                    interests=["digital payments", "financial technology", "business efficiency"],
                    pain_points=["payment collection", "reconciliation", "cash flow management"],
                    channels=["google_search", "linkedin", "whatsapp"],
                    message_tone="professional",
                    primary_motivation="Collect payments faster and manage cash flow",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="Payment solution searches", audience_fit=0.9, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="linkedin", priority=2, rationale="B2B finance decision-makers", audience_fit=0.8, cost_tier="medium", time_to_results="weeks", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="referral", priority=3, rationale="Merchant-to-merchant referrals", audience_fit=0.85, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.20),
                ChannelRecommendation(channel="content", priority=4, rationale="Integration guides and docs", audience_fit=0.7, cost_tier="low", time_to_results="months", recommended_budget_pct=0.15),
            ],
            default_budget_split={"google_search": 0.35, "linkedin": 0.30, "referral": 0.20, "content": 0.15},
            activation_bottleneck="API integration or first payment link creation",
            first_value_moment="First payment processed",
            cold_start_window_days=21,
            typical_cac_range=(20.0, 150.0),
            activation_events=["USER_REGISTERED", "API_KEY_CREATED", "PAYMENT_LINK_CREATED", "FIRST_PAYMENT_RECEIVED"],
            early_churn_signals=["no_integration_7d", "no_payment_14d", "api_key_unused_7d"],
            primary_kpis=["tpv", "active_merchants", "payment_success_rate", "net_revenue"],
        )

        self._knowledge["edtech"] = CategoryKnowledge(
            category_id="edtech",
            audience_archetypes=[
                AudienceArchetype(
                    name="Career Changer",
                    description="Professional looking to upskill or switch careers",
                    age_range=(24, 40),
                    job_titles=["Professional", "Analyst", "Manager"],
                    interests=["career development", "online learning", "new skills", "certifications"],
                    pain_points=["outdated skills", "career stagnation", "expensive education"],
                    channels=["google_search", "meta", "linkedin"],
                    message_tone="casual",
                    primary_motivation="Gain new skills to advance or change career",
                ),
                AudienceArchetype(
                    name="Student",
                    description="Student supplementing formal education",
                    age_range=(16, 28),
                    job_titles=["Student"],
                    interests=["learning", "certifications", "online courses", "technology"],
                    pain_points=["expensive textbooks", "poor lectures", "lack of practical skills"],
                    channels=["tiktok", "meta", "community"],
                    message_tone="casual",
                    primary_motivation="Learn practical skills and get certified",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="Course and skill searches", audience_fit=0.9, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="meta", priority=2, rationale="Interest-based targeting for learners", audience_fit=0.85, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="content", priority=3, rationale="Free content as lead magnet", audience_fit=0.8, cost_tier="low", time_to_results="months", recommended_budget_pct=0.20),
                ChannelRecommendation(channel="referral", priority=4, rationale="Student-to-student referrals", audience_fit=0.75, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.20),
            ],
            default_budget_split={"google_search": 0.30, "meta": 0.30, "content": 0.20, "referral": 0.20},
            activation_bottleneck="Starting first lesson or module",
            first_value_moment="Completing first lesson or quiz",
            cold_start_window_days=14,
            typical_cac_range=(8.0, 60.0),
            activation_events=["USER_REGISTERED", "COURSE_ENROLLED", "LESSON_STARTED", "LESSON_COMPLETED", "QUIZ_COMPLETED"],
            early_churn_signals=["no_enrollment_3d", "lesson_not_started_7d", "course_abandoned_14d"],
            primary_kpis=["enrollments", "completion_rate", "revenue_per_student", "nps"],
        )

        self._knowledge["healthtech"] = CategoryKnowledge(
            category_id="healthtech",
            audience_archetypes=[
                AudienceArchetype(
                    name="Health Seeker",
                    description="Individual seeking wellness or fitness solutions",
                    age_range=(20, 50),
                    job_titles=[],
                    interests=["fitness", "wellness", "health", "nutrition", "mental health"],
                    pain_points=["lack of motivation", "no personalized plan", "expensive gym memberships"],
                    channels=["meta", "tiktok", "google_search"],
                    message_tone="casual",
                    primary_motivation="Improve health and wellness with guidance",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="meta", priority=1, rationale="Visual health and fitness content", audience_fit=0.9, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="tiktok", priority=2, rationale="Fitness and wellness trending content", audience_fit=0.85, cost_tier="low", time_to_results="immediate", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="google_search", priority=3, rationale="Health solution searches", audience_fit=0.8, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="referral", priority=4, rationale="Friend recommendations for health apps", audience_fit=0.75, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"meta": 0.35, "tiktok": 0.25, "google_search": 0.25, "referral": 0.15},
            activation_bottleneck="Completing first session or appointment",
            first_value_moment="Completing first workout, session, or consultation",
            cold_start_window_days=14,
            typical_cac_range=(5.0, 40.0),
            activation_events=["USER_REGISTERED", "SESSION_STARTED", "SESSION_ENDED", "APPOINTMENT_BOOKED"],
            early_churn_signals=["no_session_3d", "no_return_7d", "subscription_not_started"],
            primary_kpis=["dau", "session_frequency", "subscription_rate", "retention_d7"],
        )

        self._knowledge["ecommerce"] = CategoryKnowledge(
            category_id="ecommerce",
            audience_archetypes=[
                AudienceArchetype(
                    name="Online Shopper",
                    description="Consumer buying products online",
                    age_range=(18, 55),
                    job_titles=[],
                    interests=["shopping", "deals", "new products", "convenience"],
                    pain_points=["product discovery", "shipping costs", "return hassle"],
                    channels=["google_search", "meta", "tiktok"],
                    message_tone="casual",
                    primary_motivation="Find and buy products conveniently online",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="Product search intent", audience_fit=0.9, cost_tier="high", time_to_results="immediate", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="meta", priority=2, rationale="Product discovery and retargeting", audience_fit=0.85, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="tiktok", priority=3, rationale="Product virality", audience_fit=0.7, cost_tier="low", time_to_results="immediate", recommended_budget_pct=0.20),
                ChannelRecommendation(channel="referral", priority=4, rationale="Customer referral discounts", audience_fit=0.7, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"google_search": 0.35, "meta": 0.30, "tiktok": 0.20, "referral": 0.15},
            activation_bottleneck="Add to cart",
            first_value_moment="First purchase completed",
            cold_start_window_days=14,
            typical_cac_range=(8.0, 50.0),
            activation_events=["USER_REGISTERED", "PRODUCT_VIEWED", "ITEM_ADDED_TO_CART", "PAYMENT_COMPLETED"],
            early_churn_signals=["no_browse_24h", "cart_abandoned", "no_purchase_7d"],
            primary_kpis=["revenue", "aov", "conversion_rate", "repeat_purchase_rate"],
        )

        self._knowledge["social"] = CategoryKnowledge(
            category_id="social",
            audience_archetypes=[
                AudienceArchetype(
                    name="Content Creator",
                    description="User who creates and shares content",
                    age_range=(16, 35),
                    job_titles=["Creator", "Influencer"],
                    interests=["content creation", "social media", "community", "networking"],
                    pain_points=["audience growth", "engagement", "monetization"],
                    channels=["tiktok", "meta", "community"],
                    message_tone="casual",
                    primary_motivation="Build an audience and engage with community",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="tiktok", priority=1, rationale="Social virality", audience_fit=0.9, cost_tier="low", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="meta", priority=2, rationale="Social targeting", audience_fit=0.85, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="community", priority=3, rationale="Organic community building", audience_fit=0.8, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="referral", priority=4, rationale="Invite friends mechanics", audience_fit=0.9, cost_tier="low", time_to_results="immediate", recommended_budget_pct=0.15),
            ],
            default_budget_split={"tiktok": 0.30, "meta": 0.30, "community": 0.25, "referral": 0.15},
            activation_bottleneck="First post or interaction",
            first_value_moment="First engagement (like, comment, or follow received)",
            cold_start_window_days=7,
            typical_cac_range=(1.0, 15.0),
            activation_events=["USER_REGISTERED", "POST_CREATED", "COMMENT_POSTED", "USER_FOLLOWED"],
            early_churn_signals=["no_post_3d", "no_interaction_7d", "zero_followers_7d"],
            primary_kpis=["dau", "mau", "posts_per_user", "engagement_rate"],
        )

        self._knowledge["developer_tools"] = CategoryKnowledge(
            category_id="developer_tools",
            audience_archetypes=[
                AudienceArchetype(
                    name="Developer",
                    description="Software engineer evaluating tools",
                    age_range=(22, 45),
                    job_titles=["Software Engineer", "Developer", "SRE", "DevOps Engineer"],
                    interests=["programming", "open source", "developer tools", "automation"],
                    pain_points=["complex setup", "poor docs", "vendor lock-in"],
                    channels=["content", "community", "google_search"],
                    message_tone="professional",
                    primary_motivation="Ship faster with better tools",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="content", priority=1, rationale="Docs, tutorials, and blog posts", audience_fit=0.9, cost_tier="low", time_to_results="months", recommended_budget_pct=0.35),
                ChannelRecommendation(channel="community", priority=2, rationale="GitHub, Stack Overflow, Discord", audience_fit=0.85, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="google_search", priority=3, rationale="Tool comparison searches", audience_fit=0.8, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.25),
                ChannelRecommendation(channel="referral", priority=4, rationale="Developer recommendations", audience_fit=0.75, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"content": 0.35, "community": 0.25, "google_search": 0.25, "referral": 0.15},
            activation_bottleneck="First API call or integration",
            first_value_moment="First successful API call returning real data",
            cold_start_window_days=14,
            typical_cac_range=(20.0, 150.0),
            activation_events=["USER_REGISTERED", "API_KEY_CREATED", "FIRST_API_CALL", "INTEGRATION_COMPLETED"],
            early_churn_signals=["no_api_call_3d", "error_rate_high_24h", "no_integration_7d"],
            primary_kpis=["api_calls", "active_developers", "integration_count", "mrr"],
        )

        self._knowledge["generic"] = CategoryKnowledge(
            category_id="generic",
            audience_archetypes=[
                AudienceArchetype(
                    name="Target User",
                    description="Primary user of the platform",
                    age_range=(18, 55),
                    job_titles=[],
                    interests=["technology", "productivity"],
                    pain_points=["finding the right solution"],
                    channels=["google_search", "meta"],
                    message_tone="casual",
                    primary_motivation="Solve a specific problem",
                ),
            ],
            acquisition_channels=[
                ChannelRecommendation(channel="google_search", priority=1, rationale="General high-intent search", audience_fit=0.7, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.40),
                ChannelRecommendation(channel="meta", priority=2, rationale="Broad interest targeting", audience_fit=0.6, cost_tier="medium", time_to_results="immediate", recommended_budget_pct=0.30),
                ChannelRecommendation(channel="content", priority=3, rationale="Organic discovery", audience_fit=0.5, cost_tier="low", time_to_results="months", recommended_budget_pct=0.15),
                ChannelRecommendation(channel="referral", priority=4, rationale="Word of mouth", audience_fit=0.6, cost_tier="low", time_to_results="weeks", recommended_budget_pct=0.15),
            ],
            default_budget_split={"google_search": 0.40, "meta": 0.30, "content": 0.15, "referral": 0.15},
            activation_bottleneck="First meaningful interaction",
            first_value_moment="First completed core action",
            cold_start_window_days=21,
            typical_cac_range=(10.0, 100.0),
            activation_events=["USER_REGISTERED", "SESSION_STARTED", "FEATURE_USED"],
            early_churn_signals=["no_return_3d", "single_session_bounce"],
            primary_kpis=["active_users", "retention_d7", "conversion_rate"],
        )
