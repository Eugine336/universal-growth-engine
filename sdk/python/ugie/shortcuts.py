"""
Friendly event name shortcuts.

Maps common human-readable event names to UGIE EventType enum values
so callers can write ``ugie.track(uid, "signup")`` instead of
``ugie.track(uid, "USER_REGISTERED")``.
"""

EVENT_SHORTCUTS = {
    # Lifecycle
    "signup": "USER_REGISTERED",
    "register": "USER_REGISTERED",
    "verify": "USER_VERIFIED",
    "login": "LOGIN_SUCCESS",
    "login_failed": "LOGIN_FAILED",
    "logout": "SESSION_ENDED",
    "password_reset": "PASSWORD_RESET",
    "deactivate": "ACCOUNT_DEACTIVATED",
    # Session & Engagement
    "session_start": "SESSION_STARTED",
    "session_end": "SESSION_ENDED",
    "page_view": "PAGE_VIEWED",
    "feature_used": "FEATURE_USED",
    "search": "SEARCH_EXECUTED",
    "view_item": "ITEM_VIEWED",
    "save_item": "ITEM_SAVED",
    "share_item": "ITEM_SHARED",
    # Communication
    "message": "MESSAGE_SENT",
    "message_read": "MESSAGE_READ",
    "email_sent": "EMAIL_SENT",
    "email_opened": "EMAIL_OPENED",
    "email_clicked": "EMAIL_CLICKED",
    "unsubscribe": "EMAIL_UNSUBSCRIBED",
    # Transactions
    "offer": "OFFER_MADE",
    "offer_accepted": "OFFER_ACCEPTED",
    "offer_rejected": "OFFER_REJECTED",
    "order": "ORDER_CREATED",
    "order_completed": "ORDER_COMPLETED",
    "order_cancelled": "ORDER_CANCELLED",
    "purchase": "PAYMENT_COMPLETED",
    "payment": "PAYMENT_COMPLETED",
    "payment_failed": "PAYMENT_FAILED",
    "refund": "REFUND_INITIATED",
    "refund_completed": "REFUND_COMPLETED",
    # Subscriptions
    "subscribe": "SUBSCRIPTION_STARTED",
    "renew": "SUBSCRIPTION_RENEWED",
    "cancel": "SUBSCRIPTION_CANCELLED",
    "upgrade": "SUBSCRIPTION_UPGRADED",
    "downgrade": "SUBSCRIPTION_DOWNGRADED",
    # Trust & Quality
    "review": "REVIEW_CREATED",
    "dispute": "DISPUTE_OPENED",
    "dispute_resolved": "DISPUTE_RESOLVED",
    "flag": "FLAG_SUBMITTED",
    "kyc_start": "KYC_STARTED",
    "kyc_complete": "KYC_COMPLETED",
    "kyc_failed": "KYC_FAILED",
    # Referral & Growth
    "referral": "REFERRAL_SENT",
    "referral_converted": "REFERRAL_CONVERTED",
    "invite": "INVITE_SENT",
    "invite_accepted": "INVITE_ACCEPTED",
    # Content
    "content_created": "CONTENT_CREATED",
    "content_published": "CONTENT_PUBLISHED",
    "content_viewed": "CONTENT_VIEWED",
    "content_liked": "CONTENT_LIKED",
}
