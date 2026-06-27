"""Unit tests for the Referral Engine."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from core.referral.engine import ReferralEngine
from core.referral.schema import (
    ReferralCodeStatus,
    ReferralProgram,
    ReferralStatus,
    RewardType,
)


@pytest.fixture
def engine():
    return ReferralEngine()


@pytest.fixture
def engine_with_program(engine):
    engine.create_program(
        platform_id="test_platform",
        name="Test Referral Program",
        referrer_reward_type=RewardType.CREDIT,
        referrer_reward_value=500.0,
        referee_reward_type=RewardType.CREDIT,
        referee_reward_value=250.0,
        reward_currency="KES",
        qualification_event="PAYMENT_COMPLETED",
        double_sided=True,
        max_referrals_per_user=50,
        code_expiry_days=90,
    )
    return engine


class TestReferralProgramCreation:
    def test_create_program(self, engine):
        program = engine.create_program(
            platform_id="plat_1",
            name="Growth Program",
            referrer_reward_type=RewardType.CREDIT,
            referrer_reward_value=100.0,
        )
        assert program.platform_id == "plat_1"
        assert program.name == "Growth Program"
        assert program.referrer_reward_type == RewardType.CREDIT
        assert program.referrer_reward_value == 100.0
        assert program.status == "active"

    def test_get_program(self, engine):
        engine.create_program(platform_id="plat_a", name="Program A")
        result = engine.get_program("plat_a")
        assert result is not None
        assert result.name == "Program A"

    def test_get_program_nonexistent(self, engine):
        assert engine.get_program("nonexistent") is None

    def test_program_with_all_reward_types(self, engine):
        for rt in RewardType:
            program = engine.create_program(
                platform_id=f"plat_{rt.value}",
                name=f"Program {rt.value}",
                referrer_reward_type=rt,
                referrer_reward_value=10.0,
            )
            assert program.referrer_reward_type == rt


class TestCodeGeneration:
    def test_generate_code(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
        )
        assert code.platform_id == "test_platform"
        assert code.referrer_identity_id == "identity_001"
        assert code.status == ReferralCodeStatus.ACTIVE
        assert len(code.code) > 0

    def test_code_format_with_entity_id(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
            referrer_entity_id="JANE",
        )
        assert "-" in code.code
        parts = code.code.split("-")
        assert len(parts) == 2
        assert len(parts[1]) == 4

    def test_code_inherits_program_config(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
        )
        assert code.reward_type == RewardType.CREDIT
        assert code.reward_value == 500.0
        assert code.reward_currency == "KES"
        assert code.expires_at is not None

    def test_code_without_program(self, engine):
        code = engine.generate_code(
            platform_id="no_program_platform",
            referrer_identity_id="identity_001",
        )
        assert code.status == ReferralCodeStatus.ACTIVE
        assert code.expires_at is None
        assert code.reward_value == 0.0

    def test_code_lookup(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
        )
        found = engine_with_program.get_code("test_platform", code.code)
        assert found is not None
        assert found.id == code.id

    def test_code_lookup_case_insensitive(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
        )
        found = engine_with_program.get_code("test_platform", code.code.lower())
        assert found is not None
        assert found.id == code.id

    def test_code_lookup_wrong_platform(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="identity_001",
        )
        found = engine_with_program.get_code("other_platform", code.code)
        assert found is None

    def test_unique_codes(self, engine_with_program):
        codes = set()
        for i in range(20):
            code = engine_with_program.generate_code(
                platform_id="test_platform",
                referrer_identity_id=f"identity_{i}",
            )
            codes.add(code.code)
        assert len(codes) == 20


class TestCodeRedemption:
    def test_redeem_code(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        referral = engine_with_program.redeem_code(
            platform_id="test_platform",
            code_str=code.code,
            referee_identity_id="referee_001",
        )
        assert referral.status == ReferralStatus.PENDING
        assert referral.referrer_identity_id == "referrer_001"
        assert referral.referee_identity_id == "referee_001"
        assert referral.referral_code_id == code.id
        assert referral.attributed_at is not None

    def test_redeem_creates_rewards(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        referral = engine_with_program.redeem_code(
            platform_id="test_platform",
            code_str=code.code,
            referee_identity_id="referee_001",
        )
        assert referral.referrer_reward is not None
        assert referral.referrer_reward.reward_value == 500.0
        assert referral.referrer_reward.reward_currency == "KES"
        assert referral.referee_reward is not None
        assert referral.referee_reward.reward_value == 250.0

    def test_redeem_increments_uses(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        assert code.current_uses == 0
        engine_with_program.redeem_code(
            platform_id="test_platform",
            code_str=code.code,
            referee_identity_id="referee_001",
        )
        assert code.current_uses == 1

    def test_redeem_nonexistent_code(self, engine_with_program):
        with pytest.raises(ValueError, match="not found"):
            engine_with_program.redeem_code(
                platform_id="test_platform",
                code_str="FAKE-CODE",
                referee_identity_id="referee_001",
            )

    def test_self_referral_rejected(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="same_user",
        )
        with pytest.raises(ValueError, match="own referral"):
            engine_with_program.redeem_code(
                platform_id="test_platform",
                code_str=code.code,
                referee_identity_id="same_user",
            )

    def test_duplicate_referee_rejected(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        engine_with_program.redeem_code(
            platform_id="test_platform",
            code_str=code.code,
            referee_identity_id="referee_001",
        )
        code2 = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_002",
        )
        with pytest.raises(ValueError, match="already been referred"):
            engine_with_program.redeem_code(
                platform_id="test_platform",
                code_str=code2.code,
                referee_identity_id="referee_001",
            )

    def test_revoked_code_rejected(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        engine_with_program.revoke_code(code.id)
        with pytest.raises(ValueError, match="revoked"):
            engine_with_program.redeem_code(
                platform_id="test_platform",
                code_str=code.code,
                referee_identity_id="referee_001",
            )

    def test_expired_code_rejected(self, engine_with_program):
        code = engine_with_program.generate_code(
            platform_id="test_platform",
            referrer_identity_id="referrer_001",
        )
        code.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        with pytest.raises(ValueError, match="expired"):
            engine_with_program.redeem_code(
                platform_id="test_platform",
                code_str=code.code,
                referee_identity_id="referee_001",
            )

    def test_max_uses_enforced(self, engine):
        engine.create_program(
            platform_id="limited",
            name="Limited",
            max_referrals_per_user=2,
        )
        code = engine.generate_code(
            platform_id="limited",
            referrer_identity_id="referrer_001",
        )
        code.max_uses = 2
        engine.redeem_code("limited", code.code, "ref_1")
        engine.redeem_code("limited", code.code, "ref_2")
        with pytest.raises(ValueError, match="maximum uses"):
            engine.redeem_code("limited", code.code, "ref_3")

    def test_cross_platform_code_isolation(self, engine):
        engine.create_program(platform_id="plat_a", name="A")
        engine.create_program(platform_id="plat_b", name="B")
        code_a = engine.generate_code("plat_a", "referrer_001")
        found = engine.get_code("plat_b", code_a.code)
        assert found is None


class TestQualificationAndRewards:
    def test_qualify_referral(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        qualified = engine_with_program.qualify_referral(referral.id)
        assert qualified.status == ReferralStatus.QUALIFIED
        assert qualified.qualified_at is not None

    def test_qualify_non_pending_fails(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        engine_with_program.qualify_referral(referral.id)
        with pytest.raises(ValueError, match="Cannot qualify"):
            engine_with_program.qualify_referral(referral.id)

    def test_grant_rewards(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        engine_with_program.qualify_referral(referral.id)
        rewarded = engine_with_program.grant_rewards(referral.id)
        assert rewarded.status == ReferralStatus.REWARDED
        assert rewarded.rewarded_at is not None
        assert rewarded.referrer_reward.status == "granted"
        assert rewarded.referrer_reward.granted_at is not None
        assert rewarded.referee_reward.status == "granted"

    def test_reward_non_qualified_fails(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        with pytest.raises(ValueError, match="Cannot reward"):
            engine_with_program.grant_rewards(referral.id)

    def test_reject_referral(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        rejected = engine_with_program.reject_referral(referral.id, "Fraudulent")
        assert rejected.status == ReferralStatus.REJECTED
        assert rejected.metadata["rejection_reason"] == "Fraudulent"

    def test_full_lifecycle(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        referral = engine_with_program.redeem_code(
            "test_platform", code.code, "referee_001"
        )
        assert referral.status == ReferralStatus.PENDING

        engine_with_program.qualify_referral(referral.id)
        assert referral.status == ReferralStatus.QUALIFIED

        engine_with_program.grant_rewards(referral.id)
        assert referral.status == ReferralStatus.REWARDED
        assert referral.referrer_reward.status == "granted"
        assert referral.referee_reward.status == "granted"


class TestReferralQueries:
    def test_get_referrals_by_referrer(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        engine_with_program.redeem_code("test_platform", code.code, "referee_001")
        engine_with_program.redeem_code("test_platform", code.code, "referee_002")
        refs = engine_with_program.get_referrals_by_referrer(
            "test_platform", "referrer_001"
        )
        assert len(refs) == 2

    def test_get_referrals_by_referee(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        engine_with_program.redeem_code("test_platform", code.code, "referee_001")
        refs = engine_with_program.get_referrals_by_referee(
            "test_platform", "referee_001"
        )
        assert len(refs) == 1

    def test_referrer_stats(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        r1 = engine_with_program.redeem_code("test_platform", code.code, "ref_1")
        r2 = engine_with_program.redeem_code("test_platform", code.code, "ref_2")
        r3 = engine_with_program.redeem_code("test_platform", code.code, "ref_3")

        engine_with_program.qualify_referral(r1.id)
        engine_with_program.grant_rewards(r1.id)
        engine_with_program.qualify_referral(r2.id)

        stats = engine_with_program.get_referrer_stats(
            "test_platform", "referrer_001"
        )
        assert stats["total_referrals"] == 3
        assert stats["qualified_count"] == 2
        assert stats["rewarded_count"] == 1
        assert stats["total_reward_value"] == 500.0

    def test_referrer_stats_empty(self, engine_with_program):
        stats = engine_with_program.get_referrer_stats("test_platform", "nobody")
        assert stats["total_referrals"] == 0
        assert stats["qualified_count"] == 0


class TestCodeRevocation:
    def test_revoke_code(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        revoked = engine_with_program.revoke_code(code.id)
        assert revoked.status == ReferralCodeStatus.REVOKED

    def test_revoke_nonexistent_code(self, engine_with_program):
        with pytest.raises(ValueError, match="not found"):
            engine_with_program.revoke_code("fake_id")


class TestCodeUsability:
    def test_code_is_usable(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        assert code.is_usable() is True

    def test_expired_code_not_usable(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        code.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert code.is_usable() is False

    def test_revoked_code_not_usable(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        engine_with_program.revoke_code(code.id)
        assert code.is_usable() is False

    def test_maxed_code_not_usable(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        code.max_uses = 1
        code.current_uses = 1
        assert code.is_usable() is False


class TestSingleSidedProgram:
    def test_single_sided_no_referee_reward(self, engine):
        engine.create_program(
            platform_id="single",
            name="Single Sided",
            referrer_reward_type=RewardType.CREDIT,
            referrer_reward_value=100.0,
            double_sided=False,
        )
        code = engine.generate_code("single", "referrer_001")
        referral = engine.redeem_code("single", code.code, "referee_001")
        assert referral.referrer_reward is not None
        assert referral.referrer_reward.reward_value == 100.0
        assert referral.referee_reward is None


class TestEngineStats:
    def test_stats(self, engine_with_program):
        code = engine_with_program.generate_code("test_platform", "referrer_001")
        engine_with_program.redeem_code("test_platform", code.code, "referee_001")
        stats = engine_with_program.stats()
        assert stats["total_programs"] == 1
        assert stats["total_codes"] == 1
        assert stats["total_referrals"] == 1
        assert stats["referrals_by_status"]["pending"] == 1

    def test_stats_empty(self, engine):
        stats = engine.stats()
        assert stats["total_programs"] == 0
        assert stats["total_codes"] == 0
        assert stats["total_referrals"] == 0


class TestConfigIntegration:
    def test_referral_program_config_schema(self):
        from core.config.schema import ReferralProgramConfig

        config = ReferralProgramConfig(
            name="UCMC Referral",
            referrer_reward_type="credit",
            referrer_reward_value=500,
            referee_reward_type="discount_percent",
            referee_reward_value=10,
            reward_currency="KES",
            qualification_event="PAYMENT_COMPLETED",
        )
        assert config.name == "UCMC Referral"
        assert config.referrer_reward_value == 500
        assert config.double_sided is True
        assert config.code_expiry_days == 90

    def test_application_config_with_referral_program(self):
        from core.config.schema import (
            ApplicationConfig,
            ApplicationInfo,
            ReferralProgramConfig,
        )

        config = ApplicationConfig(
            application=ApplicationInfo(id="test", name="Test"),
            referral_program=ReferralProgramConfig(
                name="Test Referral",
                referrer_reward_type="credit",
                referrer_reward_value=100,
            ),
        )
        assert config.referral_program is not None
        assert config.referral_program.name == "Test Referral"

    def test_application_config_without_referral_program(self):
        from core.config.schema import ApplicationConfig, ApplicationInfo

        config = ApplicationConfig(
            application=ApplicationInfo(id="test", name="Test"),
        )
        assert config.referral_program is None

    def test_config_loader_registers_referral_program(self, tmp_path):
        import yaml as yaml_lib

        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        config_data = {
            "application": {"id": "test_app", "name": "Test App"},
            "referral_program": {
                "name": "Test Referral",
                "referrer_reward_type": "credit",
                "referrer_reward_value": 500,
                "referee_reward_type": "credit",
                "referee_reward_value": 250,
                "reward_currency": "KES",
                "qualification_event": "PAYMENT_COMPLETED",
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_lib.dump(config_data))

        engine = ReferralEngine()
        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
            referral_engine=engine,
        )
        loader.load_file(str(config_file))

        program = engine.get_program("test_app")
        assert program is not None
        assert program.name == "Test Referral"
        assert program.referrer_reward_value == 500
        assert program.reward_currency == "KES"

    def test_config_loader_without_referral_engine(self, tmp_path):
        import yaml as yaml_lib

        from core.config.loader import DomainConfigLoader
        from core.decision.policy import PolicyRegistry
        from core.entity.registry import EntityRegistry
        from core.entity.state import EntityStateMachine
        from core.events.validator import EventValidator

        config_data = {
            "application": {"id": "test_app", "name": "Test App"},
            "referral_program": {
                "name": "Test Referral",
                "referrer_reward_type": "credit",
                "referrer_reward_value": 100,
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_lib.dump(config_data))

        loader = DomainConfigLoader(
            entity_registry=EntityRegistry(),
            state_machine=EntityStateMachine(),
            event_validator=EventValidator(),
            policy_registry=PolicyRegistry(),
        )
        loader.load_file(str(config_file))
