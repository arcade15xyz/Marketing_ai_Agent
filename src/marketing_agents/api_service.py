from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import ApprovalRecord, ContentItemRecord
from .linkedin_client import LinkedInClient
from .repositories import LifecycleRepository


class ApiResourceNotFoundError(RuntimeError):
    """Raised when an API resource does not exist."""


class ApiConflictError(RuntimeError):
    """Raised when an API operation conflicts with durable state or safety rules."""


class ApiPublishFailedError(ApiConflictError):
    """Raised after a failed external publish attempt has been recorded."""


@dataclass(frozen=True)
class PublishOutcome:
    content_item_id: str
    publish_job_id: str
    channel: str
    status: str
    message: str
    external_post_id: str = ""


LinkedInClientFactory = Callable[[], LinkedInClient]


def publishing_kill_switch_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    values = os.environ if environ is None else environ
    return values.get("PUBLISHING_KILL_SWITCH", "true").strip().lower() not in {
        "false",
        "0",
        "off",
        "no",
    }


class DatabaseContentPublisher:
    """Publish one durable content item with explicit safety and idempotency checks."""

    def __init__(
        self,
        session: Session,
        *,
        client_factory: LinkedInClientFactory = LinkedInClient,
    ) -> None:
        self.session = session
        self.client_factory = client_factory

    def publish(self, content_item_id: str, *, execute: bool) -> PublishOutcome:
        content = self.session.get(ContentItemRecord, content_item_id)
        if content is None:
            raise ApiResourceNotFoundError(
                f"Content item not found: {content_item_id}"
            )
        if content.channel == "reddit":
            raise ApiConflictError(
                "Reddit remains draft-and-approve only; API publishing is disabled."
            )
        if content.channel != "linkedin":
            raise ApiConflictError(
                f"Publishing is not supported for channel '{content.channel}'."
            )

        approval = self.session.scalar(
            select(ApprovalRecord).where(
                ApprovalRecord.content_item_id == content.id
            )
        )
        if approval is None:
            raise ApiConflictError("Publishing requires a human approval record.")
        if approval.status != "approved":
            raise ApiConflictError(
                f"Publishing requires approval; current status is {approval.status}."
            )
        if content.status != "queued_for_approval":
            raise ApiConflictError(
                "Publishing requires content status 'queued_for_approval'; "
                f"current status is {content.status}."
            )
        if not content.body.strip():
            raise ApiConflictError("Publishing requires non-empty content.")

        lifecycle = LifecycleRepository(self.session)
        job = lifecycle.ensure_publish_job(
            content_item_id=content.id,
            channel=content.channel,
            idempotency_key=f"{content.id}:{content.channel}:v{content.version}",
        )
        if job.status == "published":
            raise ApiConflictError("This content item has already been published.")

        if not execute:
            lifecycle.add_publish_event(
                publish_job_id=job.id,
                status="dry_run",
                message="Dry-run only. Nothing was published.",
            )
            return PublishOutcome(
                content_item_id=content.id,
                publish_job_id=job.id,
                channel=content.channel,
                status="dry_run",
                message="Dry-run passed. Send execute=true to publish.",
            )

        if publishing_kill_switch_enabled():
            raise ApiConflictError(
                "Publishing is blocked because PUBLISHING_KILL_SWITCH is enabled."
            )

        result = self.client_factory().create_text_share(content.body)
        job.attempts += 1
        if not result.ok:
            job.status = "failed"
            job.last_error = result.error or result.response_body
            lifecycle.add_publish_event(
                publish_job_id=job.id,
                status="failed",
                message=job.last_error,
            )
            raise ApiPublishFailedError(f"LinkedIn publish failed: {job.last_error}")

        job.status = "published"
        job.external_post_id = result.post_urn
        content.status = "published"
        lifecycle.add_publish_event(
            publish_job_id=job.id,
            status="published",
            external_post_id=result.post_urn,
            message=result.response_body,
        )
        return PublishOutcome(
            content_item_id=content.id,
            publish_job_id=job.id,
            channel=content.channel,
            status="published",
            message="Published to LinkedIn.",
            external_post_id=result.post_urn,
        )
