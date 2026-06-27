"""
Audience Exporter

Evaluates audiences, hashes PII, and formats payloads
for export to ad platforms (Meta, Google, TikTok, LinkedIn).
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.behavior.repository import BehaviorRepository

from .engine import AudienceEngine
from .schema import ExportDestination, ExportJob

logger = logging.getLogger(__name__)

_PHONE_DIGITS_PATTERN = re.compile(r"\D")


class AudienceExporter:

    def __init__(
        self,
        audience_engine: AudienceEngine,
        behavior_repo: BehaviorRepository,
    ):
        self._audience_engine = audience_engine
        self._behavior_repo = behavior_repo
        self._jobs: Dict[str, ExportJob] = {}
        logger.info("AudienceExporter initialized")

    def export(
        self,
        audience_id: str,
        destination: ExportDestination,
        config: Dict[str, Any],
    ) -> ExportJob:
        job = ExportJob(
            audience_id=audience_id,
            platform_id=self._get_platform_id(audience_id),
            destination=destination,
            config=config,
            status="processing",
            started_at=datetime.now(timezone.utc),
        )
        self._jobs[job.id] = job

        try:
            profiles = self._audience_engine.evaluate(audience_id)
            if not profiles:
                job.status = "completed"
                job.records_exported = 0
                job.completed_at = datetime.now(timezone.utc)
                return job

            hashed = self._hash_identifiers(profiles)

            formatters = {
                ExportDestination.META: self._format_for_meta,
                ExportDestination.GOOGLE: self._format_for_google,
                ExportDestination.TIKTOK: self._format_for_tiktok,
                ExportDestination.LINKEDIN: self._format_for_linkedin,
            }
            formatter = formatters.get(destination, self._format_for_meta)
            payload = formatter(hashed, config)

            job.status = "completed"
            job.records_exported = len(hashed)
            job.external_audience_id = config.get("external_audience_id")
            job.completed_at = datetime.now(timezone.utc)

            logger.info(
                f"Exported audience {audience_id} to {destination.value} | "
                f"records={len(hashed)}"
            )

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            logger.error(f"Export failed for audience {audience_id}: {e}")

        return job

    def get_job(self, job_id: str) -> Optional[ExportJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, audience_id: str) -> List[ExportJob]:
        return [j for j in self._jobs.values() if j.audience_id == audience_id]

    def _get_platform_id(self, audience_id: str) -> str:
        audience = self._audience_engine.get_audience(audience_id)
        return audience.platform_id if audience else "unknown"

    @staticmethod
    def _hash_value(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return email.strip().lower()

    @classmethod
    def _normalize_phone(cls, phone: str) -> str:
        return _PHONE_DIGITS_PATTERN.sub("", phone.strip())

    @classmethod
    def _hash_identifiers(
        cls,
        profiles: list,
    ) -> List[dict]:
        records = []
        for profile in profiles:
            record: Dict[str, Optional[str]] = {
                "identity_id": profile.identity_id,
                "email_hash": None,
                "phone_hash": None,
            }

            email = profile.traits.get("email")
            if email:
                record["email_hash"] = cls._hash_value(
                    cls._normalize_email(email)
                )

            phone = profile.traits.get("phone")
            if phone:
                record["phone_hash"] = cls._hash_value(
                    cls._normalize_phone(phone)
                )

            records.append(record)
        return records

    @staticmethod
    def _format_for_meta(
        hashed_records: List[dict],
        config: Dict[str, Any],
    ) -> dict:
        data = []
        for rec in hashed_records:
            row = [rec.get("email_hash", ""), rec.get("phone_hash", "")]
            data.append(row)
        return {
            "payload": {
                "schema": ["EMAIL_SHA256", "PHONE_SHA256"],
                "data": data,
            },
            "access_token": config.get("access_token", ""),
            "ad_account_id": config.get("ad_account_id", ""),
        }

    @staticmethod
    def _format_for_google(
        hashed_records: List[dict],
        config: Dict[str, Any],
    ) -> dict:
        user_identifiers = []
        for rec in hashed_records:
            entry: Dict[str, str] = {}
            if rec.get("email_hash"):
                entry["hashedEmail"] = rec["email_hash"]
            if rec.get("phone_hash"):
                entry["hashedPhoneNumber"] = rec["phone_hash"]
            if entry:
                user_identifiers.append(entry)
        return {
            "operations": [
                {
                    "operand": {
                        "userIdentifiers": user_identifiers,
                    },
                    "operator": "ADD",
                }
            ],
            "developer_token": config.get("developer_token", ""),
            "customer_id": config.get("customer_id", ""),
            "login_customer_id": config.get("login_customer_id", ""),
        }

    @staticmethod
    def _format_for_tiktok(
        hashed_records: List[dict],
        config: Dict[str, Any],
    ) -> dict:
        id_list = []
        for rec in hashed_records:
            if rec.get("email_hash"):
                id_list.append(rec["email_hash"])
        return {
            "advertiser_id": config.get("advertiser_id", ""),
            "custom_audience_id": config.get("custom_audience_id", ""),
            "id_type": "EMAIL_SHA256",
            "id_list": id_list,
            "access_token": config.get("access_token", ""),
        }

    @staticmethod
    def _format_for_linkedin(
        hashed_records: List[dict],
        config: Dict[str, Any],
    ) -> dict:
        elements = []
        for rec in hashed_records:
            if rec.get("email_hash"):
                elements.append({
                    "userIds": [
                        {
                            "idType": "SHA256_EMAIL",
                            "idValue": rec["email_hash"],
                        }
                    ]
                })
        return {
            "elements": elements,
            "ad_account_id": config.get("ad_account_id", ""),
            "dmp_segment_id": config.get("dmp_segment_id", ""),
        }
