from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .approval_workflow import WeeklyApprovalService
from .models import ContentSourceMode, WeeklyBatchResult, WeeklyBatchStatus, WeeklyContentItem
from .repositories import LifecycleRepository, WeeklyBatchRepository


class WeeklyImportError(RuntimeError):
    """Raised when a normalized weekly batch cannot be imported safely."""


class WeeklyImportConflictError(WeeklyImportError):
    """Raised when an import would mutate an existing weekly batch."""


@dataclass(frozen=True)
class WeeklyImportResult:
    batch_id: str
    content_item_ids: tuple[str, ...]
    created: bool


class JsonWeeklyBatchImporter:
    """Persist a validated JSON result without overwriting an existing batch."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def import_batch(self, result: WeeklyBatchResult) -> WeeklyImportResult:
        if result.spec.source_mode is not ContentSourceMode.JSON:
            raise WeeklyImportError("JsonWeeklyBatchImporter only accepts JSON batches.")

        checksum = str(result.source_metadata.get("source_checksum_sha256", ""))
        if not checksum:
            raise WeeklyImportError("JSON batch is missing its source checksum.")

        batches = WeeklyBatchRepository(self.session)
        lifecycle = LifecycleRepository(self.session)
        batch = batches.latest_for_week(result.spec.week_start)
        created = batch is None
        if batch is None:
            batch = batches.create(
                result.spec,
                configuration={"json_input": dict(result.source_metadata)},
            )
        else:
            self._assert_compatible_batch(batch, result, checksum)

        existing_items = {item.batch_position: item for item in batches.master_items(batch.id)}
        content_ids: list[str] = []
        missing_items = [
            item for item in result.items if item.position not in existing_items
        ]
        if missing_items and batch.status not in {
            WeeklyBatchStatus.DRAFT.value,
            WeeklyBatchStatus.VALIDATING.value,
        }:
            raise WeeklyImportConflictError(
                f"Weekly batch {batch.id} is {batch.status}; missing content cannot "
                "be added without explicit replacement."
            )

        if batch.status == WeeklyBatchStatus.DRAFT.value:
            batches.transition(batch.id, WeeklyBatchStatus.VALIDATING)

        for item in result.items:
            metadata = self._content_metadata(item, checksum)
            existing = existing_items.get(item.position)
            if existing is not None:
                self._assert_same_content(existing, item, metadata)
                content_ids.append(existing.id)
                continue

            content = lifecycle.create_content(
                run_id=(
                    f"weekly-{result.spec.week_start}-v{batch.version}"
                    f"-slot-{item.position}"
                ),
                channel="master",
                title=item.title,
                body=item.body,
                status="queued_for_approval",
                weekly_batch_id=batch.id,
                source_mode=ContentSourceMode.JSON,
                batch_position=item.position,
                metadata=metadata,
            )
            content_ids.append(content.id)

        if batch.status == WeeklyBatchStatus.VALIDATING.value:
            positions = {item.position for item in result.items}
            expected = set(range(1, batch.expected_item_count + 1))
            if positions != expected:
                raise WeeklyImportError(
                    "Validated JSON result is missing one or more batch positions."
                )
            batches.transition(batch.id, WeeklyBatchStatus.PENDING_APPROVAL)

        WeeklyApprovalService(self.session).ensure_batch_approvals(batch.id)

        return WeeklyImportResult(
            batch_id=batch.id,
            content_item_ids=tuple(content_ids),
            created=created,
        )

    def _assert_compatible_batch(
        self,
        batch,
        result: WeeklyBatchResult,
        checksum: str,
    ) -> None:
        if batch.source_mode != ContentSourceMode.JSON.value:
            raise WeeklyImportConflictError(
                "A batch already exists for this week with a different source mode."
            )
        if batch.expected_item_count != result.spec.expected_item_count:
            raise WeeklyImportConflictError(
                "A batch already exists for this week with a different item count."
            )

        previous_input = batch.configuration_snapshot.get("json_input", {})
        previous_checksum = previous_input.get("source_checksum_sha256")
        if previous_checksum != checksum:
            raise WeeklyImportConflictError(
                "A different JSON file was already imported for this week; "
                "use explicit batch replacement to change it."
            )

    def _content_metadata(
        self,
        item: WeeklyContentItem,
        checksum: str,
    ) -> dict[str, Any]:
        return {
            "scheduled_date": item.scheduled_date.isoformat(),
            "input_channel": item.channel,
            "sources": list(item.sources),
            "source_reference": item.source_reference,
            "source_checksum_sha256": checksum,
            "input_metadata": dict(item.metadata),
        }

    def _assert_same_content(
        self,
        existing,
        item: WeeklyContentItem,
        metadata: dict[str, Any],
    ) -> None:
        if (
            existing.title != item.title
            or existing.body != item.body
            or existing.source_mode != ContentSourceMode.JSON.value
            or existing.metadata_json != metadata
        ):
            raise WeeklyImportConflictError(
                f"Existing content at slot {item.position} differs from the JSON "
                "input; use explicit batch replacement to change it."
            )
