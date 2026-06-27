"""
UCMC Webhook Receiver — Reference Implementation

Shows how UCMC's backend receives UGIE action webhooks and translates
them into platform-native notifications, admin actions, and workflows.

In production, these handlers are Express.js routes in UCMC's backend:
  POST /internal/ugie/email
  POST /internal/ugie/notification
  POST /internal/ugie/workflow

This Python reference documents the expected payload format and
handler patterns for each action type.

UGIE webhook payload format:
{
    "action_id": "uuid",
    "action_type": "SEND_EMAIL",
    "identity_id": "uuid",
    "application_id": "ucmc_marketplace",
    "payload": {
        "template": "seller_profile_nudge",
        "subject": "Complete your profile",
        ...policy-defined payload_template fields
    },
    "channel": "email",
    "priority": 55,
    "decision_id": "uuid",
    "created_at": "2024-01-01T00:00:00Z"
}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WebhookResult:
    success: bool
    message: str = ""
    external_ref: Optional[str] = None


EMAIL_TEMPLATES = {
    "ucmc_welcome": {
        "subject": "Welcome to UCMC — the AI services marketplace",
        "sendgrid_template_id": "d-welcome-001",
    },
    "kyc_nudge": {
        "subject": "Verify your identity to unlock full marketplace access",
        "sendgrid_template_id": "d-kyc-nudge-001",
    },
    "buyer_reengagement": {
        "subject": "New AI services matching your interests",
        "sendgrid_template_id": "d-reengagement-001",
    },
    "review_request": {
        "subject": "How was your experience? Leave a review",
        "sendgrid_template_id": "d-review-001",
    },
    "seller_referral_ask": {
        "subject": "Know great AI service providers? Refer them to UCMC",
        "sendgrid_template_id": "d-referral-001",
    },
}


def handle_email_webhook(payload: Dict[str, Any]) -> WebhookResult:
    """
    Handle SEND_EMAIL actions from UGIE.

    Resolves the identity's email from the identity graph,
    looks up the SendGrid template, and queues the email.
    """
    template_name = payload.get("payload", {}).get("template", "default")
    identity_id = payload.get("identity_id")
    action_id = payload.get("action_id")

    template_config = EMAIL_TEMPLATES.get(template_name)
    if not template_config:
        return WebhookResult(
            success=False,
            message=f"Unknown email template: {template_name}",
        )

    logger.info(
        "Sending email | template=%s identity=%s action=%s",
        template_name, identity_id, action_id,
    )

    return WebhookResult(
        success=True,
        message=f"Email queued: {template_name}",
        external_ref=f"sendgrid_{action_id}",
    )


NOTIFICATION_TEMPLATES = {
    "seller_profile_nudge": {
        "title": "Complete Your Profile",
        "body": "Add your bio and portfolio to start receiving orders",
        "action_url": "/dashboard/profile",
    },
    "create_first_listing": {
        "title": "Create Your First Listing",
        "body": "Buyers are searching for services like yours",
        "action_url": "/dashboard/listings/new",
    },
    "delivery_reminder": {
        "title": "Pending Deliveries",
        "body": "You have orders waiting for delivery",
        "action_url": "/dashboard/orders",
    },
    "service_recommendations": {
        "title": "Services You Might Like",
        "body": "Based on your recent browsing",
        "action_url": "/marketplace",
    },
    "buyer_retention_discount": {
        "title": "Special Offer",
        "body": "10% off your next AI service purchase",
        "action_url": "/marketplace?promo=retention10",
    },
}


def handle_notification_webhook(payload: Dict[str, Any]) -> WebhookResult:
    """
    Handle SEND_IN_APP / SHOW_RECOMMENDATION / SHOW_DISCOUNT actions.

    Pushes a notification to the user via SSE or stores it for
    retrieval on next page load.
    """
    template_name = payload.get("payload", {}).get("template", "default")
    identity_id = payload.get("identity_id")
    action_type = payload.get("action_type")

    template_config = NOTIFICATION_TEMPLATES.get(template_name)
    if not template_config:
        return WebhookResult(
            success=False,
            message=f"Unknown notification template: {template_name}",
        )

    logger.info(
        "Sending notification | type=%s template=%s identity=%s",
        action_type, template_name, identity_id,
    )

    return WebhookResult(
        success=True,
        message=f"Notification sent: {template_name}",
        external_ref=f"notif_{payload.get('action_id')}",
    )


WORKFLOW_HANDLERS: Dict[str, str] = {
    "FLAG_FOR_REVIEW": "admin.flagUser",
    "ESCALATE_SUPPORT": "admin.escalateToCompliance",
    "TRIGGER_REENGAGEMENT": "marketing.reengagementCampaign",
    "TRIGGER_RETENTION": "marketing.retentionCampaign",
    "REQUEST_REVIEW": "notifications.requestReview",
}


def handle_workflow_webhook(payload: Dict[str, Any]) -> WebhookResult:
    """
    Handle FLAG_FOR_REVIEW / ESCALATE_SUPPORT / internal workflow actions.

    Routes to the appropriate internal UCMC service handler.
    """
    action_type = payload.get("action_type")
    identity_id = payload.get("identity_id")
    reason = payload.get("payload", {}).get("reason", "unspecified")

    handler = WORKFLOW_HANDLERS.get(action_type)
    if not handler:
        return WebhookResult(
            success=False,
            message=f"No workflow handler for action type: {action_type}",
        )

    logger.info(
        "Workflow action | type=%s handler=%s identity=%s reason=%s",
        action_type, handler, identity_id, reason,
    )

    return WebhookResult(
        success=True,
        message=f"Workflow dispatched: {handler}",
        external_ref=f"workflow_{payload.get('action_id')}",
    )


ROUTE_MAP: Dict[str, Callable[[Dict[str, Any]], WebhookResult]] = {
    "SEND_EMAIL": handle_email_webhook,
    "SEND_IN_APP": handle_notification_webhook,
    "SHOW_RECOMMENDATION": handle_notification_webhook,
    "SHOW_DISCOUNT": handle_notification_webhook,
    "SHOW_UPSELL": handle_notification_webhook,
    "SHOW_ONBOARDING": handle_notification_webhook,
    "FLAG_FOR_REVIEW": handle_workflow_webhook,
    "ESCALATE_SUPPORT": handle_workflow_webhook,
    "TRIGGER_REENGAGEMENT": handle_workflow_webhook,
    "TRIGGER_RETENTION": handle_workflow_webhook,
    "REQUEST_REVIEW": handle_workflow_webhook,
}


def route_webhook(payload: Dict[str, Any]) -> WebhookResult:
    """
    Top-level router — dispatches a UGIE webhook payload to the
    correct handler based on action_type.
    """
    action_type = payload.get("action_type")
    handler = ROUTE_MAP.get(action_type)
    if not handler:
        return WebhookResult(
            success=False,
            message=f"Unsupported action type: {action_type}",
        )
    return handler(payload)
