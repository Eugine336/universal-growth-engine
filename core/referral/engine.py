"""
Referral Engine

Manages the full referral lifecycle:
- Program creation and configuration
- Code generation and validation
- Redemption and attribution
- Qualification and reward granting
- Stats and history queries
"""

from __future__ import annotations

import logging
import random
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .schema import (
    Referral,
    ReferralCode,
    ReferralCodeStatus,
    ReferralProgram,
    ReferralReward,
    ReferralStatus,
    RewardType,
)

logger = logging.getLogger(__name__)


def _generate_human_code(prefix: str = "") -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    if prefix:
        clean = "".join(c for c in prefix.upper() if c.isalnum())[:4]
        return f"{clean}-{suffix}"
    return suffix


class ReferralEngine:

    def __init__(self):
        self._programs: Dict[str, ReferralProgram] = {}
        self._platform_programs: Dict[str, str] = {}
        self._codes: Dict[str, ReferralCode] = {}
        self._code_lookup: Dict[str, str] = {}
        self._referrals: Dict[str, Referral] = {}
        self._referrals_by_referrer: Dict[str, List[str]] = defaultdict(list)
        self._referrals_by_referee: Dict[str, List[str]] = defaultdict(list)
        self._referrals_by_code: Dict[str, List[str]] = defaultdict(list)

        logger.info("ReferralEngine initialized")

    def create_program(
        self,
        platform_id: str,
        name: str,
        referrer_reward_type: RewardType = RewardType.CREDIT,
        referrer_reward_value: float = 0.0,
        referee_reward_type: RewardType = RewardType.CREDIT,
        referee_reward_value: float = 0.0,
        reward_currency: Optional[str] = None,
        qualification_event: str = "USER_REGISTERED",
        double_sided: bool = True,
        max_referrals_per_user: int = 0,
        code_expiry_days: int = 90,
    ) -> ReferralProgram:
        program = ReferralProgram(
            platform_id=platform_id,
            name=name,
            referrer_reward_type=referrer_reward_type,
            referrer_reward_value=referrer_reward_value,
            referee_reward_type=referee_reward_type,
            referee_reward_value=referee_reward_value,
            reward_currency=reward_currency,
            qualification_event=qualification_event,
            double_sided=double_sided,
            max_referrals_per_user=max_referrals_per_user,
            code_expiry_days=code_expiry_days,
        )
        self._programs[program.id] = program
        self._platform_programs[platform_id] = program.id
        logger.info(
            f"Created referral program '{name}' for platform {platform_id}"
        )
        return program

    def get_program(self, platform_id: str) -> Optional[ReferralProgram]:
        pid = self._platform_programs.get(platform_id)
        return self._programs.get(pid) if pid else None

    def get_program_by_id(self, program_id: str) -> Optional[ReferralProgram]:
        return self._programs.get(program_id)

    def generate_code(
        self,
        platform_id: str,
        referrer_identity_id: str,
        referrer_entity_id: Optional[str] = None,
        program_id: Optional[str] = None,
    ) -> ReferralCode:
        program = None
        if program_id:
            program = self._programs.get(program_id)
        if not program:
            program = self.get_program(platform_id)

        if (
            program
            and program.max_referrals_per_user > 0
        ):
            referrer_key = f"{platform_id}:{referrer_identity_id}"
            existing = self._referrals_by_referrer.get(referrer_key, [])
            if len(existing) >= program.max_referrals_per_user:
                raise ValueError(
                    f"Referrer has reached max referrals "
                    f"({program.max_referrals_per_user})"
                )

        prefix = (referrer_entity_id or referrer_identity_id)[:4]
        code_str = _generate_human_code(prefix)
        lookup_key = f"{platform_id}:{code_str.upper()}"
        attempts = 0
        while lookup_key in self._code_lookup and attempts < 10:
            code_str = _generate_human_code(prefix)
            lookup_key = f"{platform_id}:{code_str.upper()}"
            attempts += 1

        expires_at = None
        reward_type = RewardType.CREDIT
        reward_value = 0.0
        reward_currency = None
        max_uses = 0

        if program:
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=program.code_expiry_days
            )
            reward_type = program.referrer_reward_type
            reward_value = program.referrer_reward_value
            reward_currency = program.reward_currency
            if program.max_referrals_per_user > 0:
                max_uses = program.max_referrals_per_user

        code = ReferralCode(
            platform_id=platform_id,
            referrer_identity_id=referrer_identity_id,
            referrer_entity_id=referrer_entity_id,
            code=code_str,
            reward_type=reward_type,
            reward_value=reward_value,
            reward_currency=reward_currency,
            max_uses=max_uses,
            expires_at=expires_at,
        )

        self._codes[code.id] = code
        self._code_lookup[lookup_key] = code.id

        logger.info(
            f"Generated referral code '{code_str}' "
            f"for referrer {referrer_identity_id} on platform {platform_id}"
        )
        return code

    def get_code(
        self, platform_id: str, code_str: str
    ) -> Optional[ReferralCode]:
        lookup_key = f"{platform_id}:{code_str.upper()}"
        code_id = self._code_lookup.get(lookup_key)
        return self._codes.get(code_id) if code_id else None

    def get_code_by_id(self, code_id: str) -> Optional[ReferralCode]:
        return self._codes.get(code_id)

    def redeem_code(
        self,
        platform_id: str,
        code_str: str,
        referee_identity_id: str,
        referee_entity_id: Optional[str] = None,
    ) -> Referral:
        code = self.get_code(platform_id, code_str)
        if not code:
            raise ValueError(f"Referral code '{code_str}' not found")

        if not code.is_usable():
            if code.status == ReferralCodeStatus.REVOKED:
                raise ValueError("Referral code has been revoked")
            if code.expires_at and datetime.now(timezone.utc) > code.expires_at:
                raise ValueError("Referral code has expired")
            if code.max_uses > 0 and code.current_uses >= code.max_uses:
                raise ValueError("Referral code has reached maximum uses")
            raise ValueError("Referral code is not usable")

        if code.referrer_identity_id == referee_identity_id:
            raise ValueError("Cannot redeem your own referral code")

        referee_key = f"{platform_id}:{referee_identity_id}"
        existing_refs = self._referrals_by_referee.get(referee_key, [])
        for ref_id in existing_refs:
            ref = self._referrals.get(ref_id)
            if ref and ref.status != ReferralStatus.REJECTED:
                raise ValueError(
                    "This user has already been referred on this platform"
                )

        program = self.get_program(platform_id)
        qualification_event = None
        referrer_reward = None
        referee_reward = None

        if program:
            qualification_event = program.qualification_event
            referrer_reward = ReferralReward(
                reward_type=program.referrer_reward_type,
                reward_value=program.referrer_reward_value,
                reward_currency=program.reward_currency,
            )
            if program.double_sided:
                referee_reward = ReferralReward(
                    reward_type=program.referee_reward_type,
                    reward_value=program.referee_reward_value,
                    reward_currency=program.reward_currency,
                )

        referral = Referral(
            platform_id=platform_id,
            referral_code_id=code.id,
            referrer_identity_id=code.referrer_identity_id,
            referee_identity_id=referee_identity_id,
            referee_entity_id=referee_entity_id,
            qualification_event=qualification_event,
            referrer_reward=referrer_reward,
            referee_reward=referee_reward,
            attributed_at=datetime.now(timezone.utc),
        )

        code.current_uses += 1
        code.updated_at = datetime.now(timezone.utc)

        self._referrals[referral.id] = referral
        referrer_key = f"{platform_id}:{code.referrer_identity_id}"
        self._referrals_by_referrer[referrer_key].append(referral.id)
        self._referrals_by_referee[referee_key].append(referral.id)
        self._referrals_by_code[code.id].append(referral.id)

        logger.info(
            f"Code '{code_str}' redeemed: "
            f"referrer={code.referrer_identity_id} → referee={referee_identity_id}"
        )
        return referral

    def qualify_referral(self, referral_id: str) -> Referral:
        referral = self._referrals.get(referral_id)
        if not referral:
            raise ValueError(f"Referral '{referral_id}' not found")
        if referral.status != ReferralStatus.PENDING:
            raise ValueError(
                f"Cannot qualify referral in status '{referral.status.value}'"
            )
        referral.status = ReferralStatus.QUALIFIED
        referral.qualified_at = datetime.now(timezone.utc)
        logger.info(f"Referral {referral_id} qualified")
        return referral

    def grant_rewards(self, referral_id: str) -> Referral:
        referral = self._referrals.get(referral_id)
        if not referral:
            raise ValueError(f"Referral '{referral_id}' not found")
        if referral.status != ReferralStatus.QUALIFIED:
            raise ValueError(
                f"Cannot reward referral in status '{referral.status.value}'"
            )
        now = datetime.now(timezone.utc)
        if referral.referrer_reward:
            referral.referrer_reward.status = "granted"
            referral.referrer_reward.granted_at = now
        if referral.referee_reward:
            referral.referee_reward.status = "granted"
            referral.referee_reward.granted_at = now
        referral.status = ReferralStatus.REWARDED
        referral.rewarded_at = now
        logger.info(f"Referral {referral_id} rewarded")
        return referral

    def reject_referral(self, referral_id: str, reason: str = "") -> Referral:
        referral = self._referrals.get(referral_id)
        if not referral:
            raise ValueError(f"Referral '{referral_id}' not found")
        referral.status = ReferralStatus.REJECTED
        if reason:
            referral.metadata["rejection_reason"] = reason
        logger.info(f"Referral {referral_id} rejected: {reason}")
        return referral

    def get_referral(self, referral_id: str) -> Optional[Referral]:
        return self._referrals.get(referral_id)

    def get_referrals_by_referrer(
        self, platform_id: str, referrer_identity_id: str
    ) -> List[Referral]:
        key = f"{platform_id}:{referrer_identity_id}"
        ref_ids = self._referrals_by_referrer.get(key, [])
        return [self._referrals[rid] for rid in ref_ids if rid in self._referrals]

    def get_referrals_by_referee(
        self, platform_id: str, referee_identity_id: str
    ) -> List[Referral]:
        key = f"{platform_id}:{referee_identity_id}"
        ref_ids = self._referrals_by_referee.get(key, [])
        return [self._referrals[rid] for rid in ref_ids if rid in self._referrals]

    def get_referrer_stats(
        self, platform_id: str, referrer_identity_id: str
    ) -> dict:
        referrals = self.get_referrals_by_referrer(platform_id, referrer_identity_id)
        total = len(referrals)
        qualified = sum(
            1
            for r in referrals
            if r.status in (ReferralStatus.QUALIFIED, ReferralStatus.REWARDED)
        )
        rewarded = sum(1 for r in referrals if r.status == ReferralStatus.REWARDED)
        total_reward = sum(
            r.referrer_reward.reward_value
            for r in referrals
            if r.status == ReferralStatus.REWARDED and r.referrer_reward
        )
        return {
            "total_referrals": total,
            "qualified_count": qualified,
            "rewarded_count": rewarded,
            "total_reward_value": total_reward,
        }

    def revoke_code(self, code_id: str) -> ReferralCode:
        code = self._codes.get(code_id)
        if not code:
            raise ValueError(f"Referral code '{code_id}' not found")
        code.status = ReferralCodeStatus.REVOKED
        code.updated_at = datetime.now(timezone.utc)
        logger.info(f"Referral code {code_id} revoked")
        return code

    def stats(self) -> dict:
        total_referrals = len(self._referrals)
        by_status: Dict[str, int] = {}
        for r in self._referrals.values():
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        return {
            "total_programs": len(self._programs),
            "total_codes": len(self._codes),
            "total_referrals": total_referrals,
            "referrals_by_status": by_status,
        }
