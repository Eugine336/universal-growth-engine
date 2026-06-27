"""Referral endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline

router = APIRouter(tags=["referrals"])


class ProgramCreate(BaseModel):
    name: str
    referrer_reward_type: str = "credit"
    referrer_reward_value: float = 0.0
    referee_reward_type: str = "credit"
    referee_reward_value: float = 0.0
    reward_currency: Optional[str] = None
    qualification_event: str = "USER_REGISTERED"
    double_sided: bool = True
    max_referrals_per_user: int = 0
    code_expiry_days: int = 90


class CodeGenerate(BaseModel):
    referrer_identity_id: str
    referrer_entity_id: Optional[str] = None


class CodeRedeem(BaseModel):
    code: str
    referee_identity_id: str
    referee_entity_id: Optional[str] = None


@router.post("/referrals/programs")
def create_program(req: ProgramCreate, platform_id: Optional[str] = None):
    from core.referral.schema import RewardType

    pid = platform_id or "default"
    try:
        referrer_rt = RewardType(req.referrer_reward_type)
        referee_rt = RewardType(req.referee_reward_type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    program = pipeline.referral_engine.create_program(
        platform_id=pid,
        name=req.name,
        referrer_reward_type=referrer_rt,
        referrer_reward_value=req.referrer_reward_value,
        referee_reward_type=referee_rt,
        referee_reward_value=req.referee_reward_value,
        reward_currency=req.reward_currency,
        qualification_event=req.qualification_event,
        double_sided=req.double_sided,
        max_referrals_per_user=req.max_referrals_per_user,
        code_expiry_days=req.code_expiry_days,
    )
    return program.model_dump()


@router.get("/referrals/programs")
def get_program(platform_id: Optional[str] = None):
    pid = platform_id or "default"
    program = pipeline.referral_engine.get_program(pid)
    if not program:
        raise HTTPException(404, "No referral program found for this platform")
    return program.model_dump()


@router.post("/referrals/codes")
def generate_code(req: CodeGenerate, platform_id: Optional[str] = None):
    pid = platform_id or "default"
    try:
        code = pipeline.referral_engine.generate_code(
            platform_id=pid,
            referrer_identity_id=req.referrer_identity_id,
            referrer_entity_id=req.referrer_entity_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return code.model_dump()


@router.post("/referrals/redeem")
def redeem_code(req: CodeRedeem, platform_id: Optional[str] = None):
    pid = platform_id or "default"
    try:
        referral = pipeline.referral_engine.redeem_code(
            platform_id=pid,
            code_str=req.code,
            referee_identity_id=req.referee_identity_id,
            referee_entity_id=req.referee_entity_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    _fire_referral_event(
        "REFERRAL_SENT",
        pid,
        referral.referrer_identity_id,
        {
            "referral_id": referral.id,
            "referee_identity_id": referral.referee_identity_id,
            "referral_code": req.code,
        },
    )
    return referral.model_dump()


@router.post("/referrals/{referral_id}/qualify")
def qualify_referral(referral_id: str):
    try:
        referral = pipeline.referral_engine.qualify_referral(referral_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return referral.model_dump()


@router.post("/referrals/{referral_id}/reward")
def grant_rewards(referral_id: str):
    try:
        referral = pipeline.referral_engine.grant_rewards(referral_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    _fire_referral_event(
        "REFERRAL_CONVERTED",
        referral.platform_id,
        referral.referrer_identity_id,
        {
            "referral_id": referral.id,
            "referee_identity_id": referral.referee_identity_id,
        },
    )
    return referral.model_dump()


@router.get("/referrals/stats/{identity_id}")
def get_referrer_stats(identity_id: str, platform_id: Optional[str] = None):
    pid = platform_id or "default"
    return pipeline.referral_engine.get_referrer_stats(pid, identity_id)


@router.get("/referrals/by-referrer/{identity_id}")
def list_by_referrer(identity_id: str, platform_id: Optional[str] = None):
    pid = platform_id or "default"
    referrals = pipeline.referral_engine.get_referrals_by_referrer(pid, identity_id)
    return [r.model_dump() for r in referrals]


def _fire_referral_event(
    event_type: str,
    platform_id: str,
    actor_id: str,
    properties: dict,
) -> None:
    if not pipeline.event_bus:
        return
    try:
        from core.events.schema import Event, EventType

        event = Event(
            application_id=platform_id,
            type=EventType(event_type),
            actor_id=actor_id,
            properties=properties,
        )
        pipeline.event_bus.submit(event)
    except Exception:
        pass
