# Operations

## Weekly Preparation Workflow

1. Run `prepare-week --dry-run` for the target Monday.
2. Run `prepare-week` to persist the complete batch.
3. Review the weekly batch and channel drafts.
4. Use the API to approve, reject, or request changes on required content.
5. Confirm `/batches/{batch_id}/approval-status` reports `ready`; the next
   scheduling phase creates publish jobs.
6. Run `publish-due` as a dry-run.
7. Enable publishing deliberately and run `publish-due --execute`.
8. Record metrics and generate the weekly report.

`publish-due` only processes already-scheduled, due, approved LinkedIn jobs. It
does not invoke content generation.

## Scheduler Commands

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json --dry-run
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json
python -m src.marketing_agents.scheduler publish-due
python -m src.marketing_agents.scheduler weekly-report --week-start 2026-10-05
```

For AI mode, omit `--input`. The legacy daily workflow is temporarily available
through `legacy-daily`.

## State To Watch

- `weekly_batches` records source mode and preparation state.
- `content_items` stores weekly position and scheduled-date metadata.
- `approvals` stores human decisions.
- `publish_jobs` stores due time, state, attempts, and external post ID.
- `publish_events` is the immutable attempt audit.
- `agent_runs` tracks AI calls and outcomes.
- `system_events` records exceptional lifecycle events.
- `outputs/reports/` contains weekly analytics reports.

## Safe Defaults

- Weekly scheduler commands require database-backed storage.
- JSON mode never falls back to AI.
- AI dry-run does not call the provider or spend tokens.
- Due publishing is a dry-run without `--execute`.
- Publishing is blocked while `PUBLISHING_KILL_SWITCH=true`.
- Only due, approved, queued LinkedIn content is eligible.
- Jobs at the retry limit are skipped.
- Reddit remains draft-only.
- Approval alone does not publish.
- All required approvals move a weekly batch to `ready`; changing one before
  publishing moves it back to `pending_approval`.
- Approval decisions are locked after the batch enters `publishing` or a
  terminal state.
- An already-published job cannot publish again.

## Weekly Approval API

- `GET /approvals?status=pending` lists work awaiting review.
- `POST /content/{content_item_id}/approval` records `approved`, `rejected`, or
  `needs_changes` and recalculates the batch gate.
- `GET /batches/{batch_id}/approval-status` reports counts and readiness.
- `POST /batches/{batch_id}/approvals/sync` safely creates missing pending
  records for a batch prepared before approval integration.

Required content is the canonical `master` plus every derivative currently in
`queued_for_approval`. A Reddit draft in `needs_rules_check` is not required
until that separate check promotes it to the approval queue.

## Baseline Tests

Run the regression suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```
