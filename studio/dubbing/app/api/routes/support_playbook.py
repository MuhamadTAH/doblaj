"""
Automated Incident Support Playbook Route for Dubbing Studio.

Implements Part 09 / Video 53 (DamFvyUj3U0.mp4):
- Tier 1 Automated Resolution Playbooks (Token expiry, payment webhooks, GPU worker timeouts)
- Tier 2 Assisted Triage Guidelines
- Tier 3 Incident Containment Protocols
"""
from fastapi import APIRouter, Depends
from app.auth.clerk_auth import require_user, AuthenticatedUser

router = APIRouter()


SUPPORT_PLAYBOOKS = {
    "tier_1_automated": {
        "expired_tokens": {
            "symptom": "HTTP 401 Token Expired",
            "resolution": "Client automatically uses Clerk refresh flow; if unhandled, redirect to /login."
        },
        "failed_checkout_webhook": {
            "symptom": "Payment completed but minutes balance not updated",
            "resolution": "Re-trigger webhook verification at /v1/payments/stripe-webhook using Stripe Event ID."
        },
        "gpu_worker_timeout": {
            "symptom": "Dubbing job stuck in 'processing' over 15 minutes",
            "resolution": "Automated status watcher auto-fails job and triggers RunPod endpoint retry."
        }
    },
    "tier_2_assisted_triage": {
        "audio_synch_drift": "Flag chunk for manual alignment in manual_video router",
        "openrouter_rate_limit": "Fallback chain engages meta-llama / claude-haiku models automatically"
    },
    "tier_3_incident_containment": {
        "unauthorized_cross_tenant_access": [
            "1. Lock down affected workspace API tokens immediately.",
            "2. Rotate INTERNAL_API_KEY on Railway/Convex dashboard.",
            "3. Audit Convex query logs for expectedWorkspaceId violations.",
            "4. Notify system administrator."
        ]
    }
}


@router.get("/support/playbook")
async def get_support_playbook(user: AuthenticatedUser = Depends(require_user)):
    """Return production support playbooks and incident containment protocols."""
    return {
        "platform": "Dubbing Studio",
        "workspace_id": user.workspace_id,
        "playbooks": SUPPORT_PLAYBOOKS
    }
