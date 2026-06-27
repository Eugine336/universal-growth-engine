# UCMC AI Marketplace — UGIE Domain Integration

Production domain configuration for the [UCMC AI Marketplace](https://ucmccore.tech),
a ZK-proof-based AI services marketplace with escrow payments via Paystack.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  UCMC Backend (Node.js / TypeScript)                    │
│                                                         │
│  signalRegistry ──► eventIngestor ──► event_bridge.py   │
│                                           │             │
│                                    POST /api/v1/events  │
└───────────────────────────────────────────┼─────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────┐
│  UGIE Engine                                            │
│                                                         │
│  EventBus → Identity → Behavior → Predict → Decide     │
│                                                  │      │
│                                         Webhook POST    │
└──────────────────────────────────────────────┼──────────┘
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────┐
│  UCMC Internal Endpoints (webhook_receiver.py)          │
│                                                         │
│  /internal/ugie/email         → send via SMTP/SendGrid  │
│  /internal/ugie/notification  → push via SSE/WebSocket  │
│  /internal/ugie/workflow      → admin actions           │
└─────────────────────────────────────────────────────────┘
```

## Setup

### 1. Environment Variables

```bash
# UGIE config directory — point to this domain folder
export UGIE_CONFIG_DIR=domain/ucmc

# UCMC backend URL for action webhooks
export UCMC_API_URL=https://api.ucmccore.tech
export UCMC_INTERNAL_KEY=<your-internal-api-key>
```

### 2. Start UGIE

```bash
docker compose up
# or
uvicorn api.rest.app:app --host 0.0.0.0 --port 8000
```

### 3. Wire UCMC Signals to UGIE Events

In your UCMC backend, add an HTTP call in the `eventIngestor` (or a queue consumer)
that translates each signal into a UGIE event. See `event_bridge.py` for the
complete signal-to-event mapping.

Example (TypeScript):
```typescript
import { SIGNAL_TO_UGIE_EVENT } from './ugie-bridge';

eventEmitter.on('signal', async (signal) => {
  const mapping = SIGNAL_TO_UGIE_EVENT[signal.type];
  if (!mapping) return;

  await fetch(`${UGIE_URL}/api/v1/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      application_id: 'ucmc_marketplace',
      type: mapping.type,
      custom_type: mapping.custom_type,
      actor_id: signal.actorId,
      actor_type: signal.actorType || 'Buyer',
      target_id: signal.targetId,
      target_type: mapping.target_type,
      properties: signal.payload,
    }),
  });
});
```

### 4. Receive UGIE Action Webhooks

Add internal endpoints in your UCMC backend to handle UGIE action dispatches.
See `webhook_receiver.py` for the expected payload format and handler patterns.

## Signal Mapping

| UCMC Signal | UGIE EventType | Notes |
|---|---|---|
| INIT | USER_REGISTERED | New buyer or seller |
| PROFILE_UPDATE | ENTITY_UPDATED | Profile completion |
| LISTING_CREATE | CONTENT_CREATED | New AI service listing |
| LISTING_UPDATE | ENTITY_UPDATED | Listing modification |
| MESSAGE_SEND | MESSAGE_SENT | Buyer-seller messaging |
| DELIVERY_CONFIRM | ORDER_COMPLETED | Seller confirms delivery |
| REVIEW_SUBMIT | REVIEW_CREATED | Post-transaction review |
| KYC_START | KYC_STARTED | KYC verification initiated |
| KYC_VERIFIED | KYC_COMPLETED | KYC passed |
| KYC_REJECTED | CUSTOM:KYC_REJECTED | KYC failed |
| PAYMENT_INITIATE | PAYMENT_INITIATED | Paystack payment started |
| LOCK | PAYMENT_INITIATED | Escrow funds locked |
| RELEASE | PAYMENT_COMPLETED | Escrow released to seller |
| REVERT | REFUND_COMPLETED | Escrow refunded to buyer |
| FINALIZE | ORDER_COMPLETED | Transaction finalized |
| DISPUTE_OPEN | DISPUTE_OPENED | Dispute filed |
| DISPUTE_RESOLVE | DISPUTE_RESOLVED | Dispute resolved |
| EMAIL_VERIFIED | USER_VERIFIED | Email verification |
| ONBOARDING_COMPLETE | CUSTOM:ONBOARDING_COMPLETE | Full onboarding done |
| DEPOSIT_CONFIRMED | CUSTOM:DEPOSIT_CONFIRMED | Wallet deposit |
| WITHDRAWAL_REQUEST | CUSTOM:WITHDRAWAL_REQUEST | Wallet withdrawal |
| REPORT_ACTOR | FLAG_SUBMITTED | User reported |
| ACTOR_BANNED | ACCOUNT_DEACTIVATED | User banned |
| SANCTIONS_HIT | CUSTOM:SANCTIONS_HIT | OFAC/SDN match |

## Policies

| Policy | Trigger | Action | Cooldown |
|---|---|---|---|
| Welcome Email | USER_REGISTERED | SEND_EMAIL | once |
| Seller Profile Nudge | SESSION_STARTED | SEND_IN_APP | 72h |
| KYC Nudge | SESSION_STARTED | SEND_EMAIL | 120h |
| First Listing Nudge | SESSION_STARTED | SEND_IN_APP | 168h |
| Buyer Re-engagement | always | SEND_EMAIL | 168h |
| Browse Recommendation | SEARCH/ITEM_VIEWED | SHOW_RECOMMENDATION | 24h |
| Post-Transaction Review | PAYMENT_COMPLETED | SEND_EMAIL (24h delay) | 168h |
| Delivery Reminder | always | SEND_IN_APP | 48h |
| Power Seller Referral | always | SEND_EMAIL | 336h |
| Buyer Retention Offer | always | SHOW_DISCOUNT | 336h |
| Fraud Flag | always | FLAG_FOR_REVIEW | 48h |
| Sanctions Flag | CUSTOM | ESCALATE_SUPPORT | 24h |
