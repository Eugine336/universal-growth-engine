"""
Tests for Ad Platform Connectors and Audience Exporter.
"""

from __future__ import annotations

import hashlib
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.action.schema import Action
from core.audience.engine import AudienceEngine
from core.audience.exporter import AudienceExporter
from core.audience.schema import (
    AudienceDefinition,
    AudienceRule,
    AudienceRuleGroup,
    ExportDestination,
)
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile
from connectors.meta.connector import MetaAdsConnector
from connectors.google.connector import GoogleAdsConnector
from connectors.tiktok.connector import TikTokAdsConnector
from connectors.linkedin.connector import LinkedInAdsConnector


def _make_action(**overrides) -> Action:
    defaults = {
        "decision_id": "dec-001",
        "identity_id": "id-001",
        "application_id": "app-001",
        "action_type": "RUN_META_CAMPAIGN",
        "payload": {"campaign_name": "test"},
    }
    defaults.update(overrides)
    return Action(**defaults)


# ---------------------------------------------------------------------------
# PII Hashing
# ---------------------------------------------------------------------------


class TestPIIHashing:

    def test_email_normalization(self):
        assert AudienceExporter._normalize_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_phone_normalization(self):
        assert AudienceExporter._normalize_phone("+254 700-111-222") == "254700111222"
        assert AudienceExporter._normalize_phone("(555) 123-4567") == "5551234567"

    def test_hash_value_sha256(self):
        h = AudienceExporter._hash_value("alice@example.com")
        expected = hashlib.sha256(b"alice@example.com").hexdigest()
        assert h == expected

    def test_hash_identifiers_with_email_and_phone(self):
        repo = BehaviorRepository()
        p = BehavioralProfile(identity_id="u1", application_id="app1")
        p.traits["email"] = "Alice@Example.com"
        p.traits["phone"] = "+254 700 111 222"
        repo.save(p)

        records = AudienceExporter._hash_identifiers([p])
        assert len(records) == 1
        assert records[0]["email_hash"] is not None
        assert records[0]["phone_hash"] is not None
        assert records[0]["email_hash"] == hashlib.sha256(b"alice@example.com").hexdigest()
        assert records[0]["phone_hash"] == hashlib.sha256(b"254700111222").hexdigest()

    def test_hash_identifiers_no_pii(self):
        p = BehavioralProfile(identity_id="u2", application_id="app1")
        records = AudienceExporter._hash_identifiers([p])
        assert records[0]["email_hash"] is None
        assert records[0]["phone_hash"] is None


# ---------------------------------------------------------------------------
# Payload Formatting
# ---------------------------------------------------------------------------


class TestPayloadFormatting:

    def _sample_records(self):
        email_hash = hashlib.sha256(b"alice@example.com").hexdigest()
        phone_hash = hashlib.sha256(b"254700111222").hexdigest()
        return [
            {"identity_id": "u1", "email_hash": email_hash, "phone_hash": phone_hash},
            {"identity_id": "u2", "email_hash": email_hash, "phone_hash": None},
        ]

    def test_format_for_meta(self):
        records = self._sample_records()
        config = {"access_token": "tok", "ad_account_id": "act_123"}
        payload = AudienceExporter._format_for_meta(records, config)
        assert payload["payload"]["schema"] == ["EMAIL_SHA256", "PHONE_SHA256"]
        assert len(payload["payload"]["data"]) == 2
        assert payload["access_token"] == "tok"
        assert payload["ad_account_id"] == "act_123"

    def test_format_for_google(self):
        records = self._sample_records()
        config = {
            "developer_token": "dev",
            "customer_id": "cust",
            "login_customer_id": "login",
        }
        payload = AudienceExporter._format_for_google(records, config)
        assert len(payload["operations"]) == 1
        identifiers = payload["operations"][0]["operand"]["userIdentifiers"]
        assert len(identifiers) == 2
        assert "hashedEmail" in identifiers[0]
        assert payload["developer_token"] == "dev"

    def test_format_for_tiktok(self):
        records = self._sample_records()
        config = {
            "advertiser_id": "adv",
            "custom_audience_id": "ca1",
            "access_token": "tok",
        }
        payload = AudienceExporter._format_for_tiktok(records, config)
        assert payload["id_type"] == "EMAIL_SHA256"
        assert len(payload["id_list"]) == 2
        assert payload["advertiser_id"] == "adv"

    def test_format_for_linkedin(self):
        records = self._sample_records()
        config = {"ad_account_id": "li_act", "dmp_segment_id": "seg1"}
        payload = AudienceExporter._format_for_linkedin(records, config)
        assert len(payload["elements"]) == 2
        assert payload["elements"][0]["userIds"][0]["idType"] == "SHA256_EMAIL"
        assert payload["ad_account_id"] == "li_act"


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class TestAudienceExporter:

    def _setup(self):
        repo = BehaviorRepository()
        p1 = BehavioralProfile(identity_id="u1", application_id="app1")
        p1.engagement.tier = "power"
        p1.traits["email"] = "alice@example.com"
        repo.save(p1)

        p2 = BehavioralProfile(identity_id="u2", application_id="app1")
        p2.engagement.tier = "cold"
        repo.save(p2)

        engine = AudienceEngine(repo)
        audience = engine.create_audience(
            "plt1",
            AudienceDefinition(
                name="power_users",
                groups=[
                    AudienceRuleGroup(
                        rules=[
                            AudienceRule(
                                field="engagement.tier",
                                operator="eq",
                                value="power",
                            )
                        ]
                    )
                ],
            ),
        )
        exporter = AudienceExporter(engine, repo)
        return engine, exporter, audience

    def test_export_completes(self):
        engine, exporter, audience = self._setup()
        job = exporter.export(
            audience.id,
            ExportDestination.META,
            {"access_token": "tok", "ad_account_id": "act"},
        )
        assert job.status == "completed"
        assert job.records_exported == 1

    def test_export_empty_audience(self):
        repo = BehaviorRepository()
        engine = AudienceEngine(repo)
        audience = engine.create_audience(
            "plt1",
            AudienceDefinition(
                name="nobody",
                groups=[
                    AudienceRuleGroup(
                        rules=[
                            AudienceRule(
                                field="engagement.tier",
                                operator="eq",
                                value="nonexistent",
                            )
                        ]
                    )
                ],
            ),
        )
        exporter = AudienceExporter(engine, repo)
        job = exporter.export(audience.id, ExportDestination.GOOGLE, {})
        assert job.status == "completed"
        assert job.records_exported == 0

    def test_get_job(self):
        engine, exporter, audience = self._setup()
        job = exporter.export(audience.id, ExportDestination.META, {})
        fetched = exporter.get_job(job.id)
        assert fetched is not None
        assert fetched.id == job.id

    def test_list_jobs(self):
        engine, exporter, audience = self._setup()
        exporter.export(audience.id, ExportDestination.META, {})
        exporter.export(audience.id, ExportDestination.GOOGLE, {})
        jobs = exporter.list_jobs(audience.id)
        assert len(jobs) == 2


# ---------------------------------------------------------------------------
# Connector Manifests
# ---------------------------------------------------------------------------


class TestConnectorManifests:

    def test_meta_manifest(self):
        c = MetaAdsConnector()
        m = c.manifest
        assert m.id == "meta_ads"
        assert "RUN_META_CAMPAIGN" in m.supported_action_types
        assert "SYNC_META_AUDIENCE" in m.supported_action_types

    def test_google_manifest(self):
        c = GoogleAdsConnector()
        m = c.manifest
        assert m.id == "google_ads"
        assert "RUN_GOOGLE_CAMPAIGN" in m.supported_action_types
        assert "SYNC_GOOGLE_AUDIENCE" in m.supported_action_types

    def test_tiktok_manifest(self):
        c = TikTokAdsConnector()
        m = c.manifest
        assert m.id == "tiktok_ads"
        assert "RUN_TIKTOK_CAMPAIGN" in m.supported_action_types
        assert "SYNC_TIKTOK_AUDIENCE" in m.supported_action_types

    def test_linkedin_manifest(self):
        c = LinkedInAdsConnector()
        m = c.manifest
        assert m.id == "linkedin_ads"
        assert "RUN_LINKEDIN_CAMPAIGN" in m.supported_action_types
        assert "SYNC_LINKEDIN_AUDIENCE" in m.supported_action_types


class TestConnectorCanHandle:

    def test_meta_can_handle(self):
        c = MetaAdsConnector()
        assert c.can_handle("RUN_META_CAMPAIGN") is True
        assert c.can_handle("SEND_EMAIL") is False

    def test_google_can_handle(self):
        c = GoogleAdsConnector()
        assert c.can_handle("RUN_GOOGLE_CAMPAIGN") is True
        assert c.can_handle("SYNC_GOOGLE_AUDIENCE") is True

    def test_tiktok_can_handle(self):
        c = TikTokAdsConnector()
        assert c.can_handle("RUN_TIKTOK_CAMPAIGN") is True

    def test_linkedin_can_handle(self):
        c = LinkedInAdsConnector()
        assert c.can_handle("RUN_LINKEDIN_CAMPAIGN") is True


# ---------------------------------------------------------------------------
# Connector Execution (with httpx mocking)
# ---------------------------------------------------------------------------


class TestMetaAdsExecution:

    @patch("connectors.meta.connector.httpx.Client")
    def test_successful_campaign(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "campaign_123"}
        mock_response.text = '{"id": "campaign_123"}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"META_ACCESS_TOKEN": "tok", "META_AD_ACCOUNT_ID": "123"}):
            c = MetaAdsConnector()
            result = c.execute(_make_action())
        assert result.success is True
        assert result.connector_ref == "campaign_123"

    @patch("connectors.meta.connector.httpx.Client")
    def test_api_error(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "invalid token"}}
        mock_response.text = '{"error": {"message": "invalid token"}}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"META_ACCESS_TOKEN": "tok", "META_AD_ACCOUNT_ID": "123"}):
            c = MetaAdsConnector()
            result = c.execute(_make_action())
        assert result.success is False
        assert "400" in result.error

    def test_exception_handling(self):
        with patch("connectors.meta.connector.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_cls.return_value = mock_client

            c = MetaAdsConnector()
            result = c.execute(_make_action())
        assert result.success is False
        assert "error" in result.error.lower()


class TestGoogleAdsExecution:

    @patch("connectors.google.connector.httpx.Client")
    def test_successful_campaign(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resourceName": "customers/123/campaigns/456"}
        mock_response.text = '{"resourceName": "customers/123/campaigns/456"}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {
            "GOOGLE_ADS_DEVELOPER_TOKEN": "dev",
            "GOOGLE_ADS_CUSTOMER_ID": "123",
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "456",
        }):
            c = GoogleAdsConnector()
            result = c.execute(_make_action(action_type="RUN_GOOGLE_CAMPAIGN"))
        assert result.success is True
        assert result.connector_ref == "customers/123/campaigns/456"


class TestTikTokAdsExecution:

    @patch("connectors.tiktok.connector.httpx.Client")
    def test_successful_campaign(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"campaign_id": "tt_789"}}
        mock_response.text = '{"data": {"campaign_id": "tt_789"}}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {
            "TIKTOK_ACCESS_TOKEN": "tok",
            "TIKTOK_ADVERTISER_ID": "adv",
        }):
            c = TikTokAdsConnector()
            result = c.execute(_make_action(action_type="RUN_TIKTOK_CAMPAIGN"))
        assert result.success is True
        assert result.connector_ref == "tt_789"


class TestLinkedInAdsExecution:

    @patch("connectors.linkedin.connector.httpx.Client")
    def test_successful_campaign(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "li_camp_001"}
        mock_response.text = '{"id": "li_camp_001"}'

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {
            "LINKEDIN_ACCESS_TOKEN": "tok",
            "LINKEDIN_AD_ACCOUNT_ID": "li_act",
        }):
            c = LinkedInAdsConnector()
            result = c.execute(_make_action(action_type="RUN_LINKEDIN_CAMPAIGN"))
        assert result.success is True
        assert result.connector_ref == "li_camp_001"


# ---------------------------------------------------------------------------
# Env Var Resolution
# ---------------------------------------------------------------------------


class TestEnvVarResolution:

    def test_meta_env_vars(self):
        from connectors.meta.connector import _resolve_env_vars
        with patch.dict(os.environ, {"META_ACCESS_TOKEN": "real_tok"}):
            assert _resolve_env_vars("${META_ACCESS_TOKEN}") == "real_tok"

    def test_unset_stays(self):
        from connectors.meta.connector import _resolve_env_vars
        assert _resolve_env_vars("${NOPE_XYZZY}") == "${NOPE_XYZZY}"
