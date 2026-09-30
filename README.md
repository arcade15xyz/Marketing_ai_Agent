# AOSP Marketing Agents

Markdown-only multi-agent content pipeline for Ftechiz Pvt. Ltd.

Legacy workflow: Phase 7. Upgrade progress: database-backed daily generation, approvals, and publishing are available behind `STORAGE_BACKEND=database`; JSON remains the safe default.

## Setup

Start here:

- [Setup](docs/SETUP.md)
- [Operations](docs/OPERATIONS.md)
- [Kill Switch](docs/KILL_SWITCH.md)


## Persistence Foundation

Step 2 adds SQLAlchemy models and Alembic migrations for topics, content,
research sources, approvals, publish jobs/events, metrics, agent runs, and system
events. Topic reservation uses PostgreSQL row locking with `SKIP LOCKED` to avoid
concurrent duplicate selection.

```powershell
python -m pip install -e .
python -m alembic upgrade head
python -m src.marketing_agents.import_json --dry-run
python -m src.marketing_agents.import_json
```

See [Setup](docs/SETUP.md) before enabling database-backed operation.

## FastAPI Service

The API uses the same PostgreSQL records as the generation workflow. Apply
migrations and set `STORAGE_BACKEND=database` and `DATABASE_URL`, then start it:

```powershell
python -m alembic upgrade head
python -m uvicorn src.marketing_agents.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive OpenAPI interface.
Available resources include health, topics, weekly batches, content, approvals,
runs, metrics, publishing, and an analytics summary.

Publishing is a dry run unless the request body contains `{"execute": true}`.
Execution additionally requires an approved LinkedIn item, the
`queued_for_approval` content state, and
`PUBLISHING_KILL_SWITCH=false`. Reddit publishing remains disabled.

## Weekly Scheduler

Weekly preparation requires PostgreSQL with `STORAGE_BACKEND=database`.

Validate a JSON week without changing the database:

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json --dry-run
```

Prepare and persist the complete configured week:

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json
```

In AI mode, omit `--input`. An AI dry-run checks topic capacity without calling
the LLM provider:

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --dry-run
```

Process only already-scheduled, due, approved jobs. This is a dry-run unless
`--execute` is supplied:

```powershell
python -m src.marketing_agents.scheduler publish-due
python -m src.marketing_agents.scheduler publish-due --execute
```

Generate the existing analytics report:

```powershell
python -m src.marketing_agents.scheduler weekly-report --week-start 2026-10-05
```

The previous daily-generation workflow remains temporarily available:

```powershell
python -m src.marketing_agents.scheduler legacy-daily --date 2026-09-28
```

Weekly preparation now creates durable pending approval records. The canonical
master and every derivative in `queued_for_approval` must be approved before the
batch moves to `ready`; Reddit drafts in `needs_rules_check` are excluded until
their rules check is complete. Creating scheduled publish jobs remains a later
step, and `publish-due` never generates content.

## Weekly Approval Gate

Use the FastAPI service (or its interactive `/docs` page) to review and decide
weekly approvals:

- `GET /approvals?status=pending` lists pending decisions.
- `POST /content/{content_item_id}/approval` accepts `approved`, `rejected`, or
  `needs_changes`, with an optional note.
- `GET /batches/{batch_id}/approval-status` reports gate progress.
- `POST /batches/{batch_id}/approvals/sync` backfills approval records for an
  older weekly batch.

The last required approval automatically moves `pending_approval` to `ready`.
Changing a decision before publishing moves the batch back to
`pending_approval`. Decisions are locked once publishing starts. Approval does
not publish or create an external side effect.

## Legacy Daily Approval

Approval only updates local state. It does not publish.

```powershell
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform blog --decision approved
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform linkedin --decision needs_changes --note "Make the hook more specific."
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform reddit --decision needs_changes --note "Check target subreddit rules first."
```

## LinkedIn Publishing

LinkedIn publishing is blocked unless all of these are true:

- `PUBLISHING_KILL_SWITCH=false`
- `LINKEDIN_ACCESS_TOKEN` is set.
- `LINKEDIN_AUTHOR_URN` is set, for example `urn:li:person:...`.
- The LinkedIn draft is approved in `data/approval_queue.json`.
- You run the publisher with `--execute`.

Dry-run:

```powershell
python -m src.marketing_agents.publisher --date 2026-09-28 --platform linkedin
```

Publish:

```powershell
python -m src.marketing_agents.publisher --date 2026-09-28 --platform linkedin --execute
```

The implementation uses LinkedIn's official Share on LinkedIn flow with the `w_member_social` permission and `POST https://api.linkedin.com/v2/ugcPosts`.

Official docs:

- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- https://learn.microsoft.com/en-us/linkedin/compliance/integrations/shares/ugc-post-api

## Reddit Drafts

Reddit is draft-and-approve only in Phase 5.

The system creates `07-reddit-draft.md` as a value-first discussion draft. It intentionally omits the Ftechiz website link to avoid thin self-promotion. Before using a Reddit draft, check the current rules for the target subreddit and adapt the post manually.

Target subreddit metadata lives in:

```text
data/reddit_targets.json
```

The publisher refuses Reddit publishing:

```powershell
python -m src.marketing_agents.publisher --date 2026-09-28 --platform reddit
```

## Analytics

Record manual metrics after content has been live:

```powershell
python -m src.marketing_agents.metrics --date 2026-09-28 --platform linkedin --impressions 1200 --clicks 18 --comments 4 --profile-views 12 --inbound-dms 1 --leads 1 --note "Good comments from embedded engineers."
```

Generate a weekly report:

```powershell
python -m src.marketing_agents.analytics --week-start 2026-09-28
```

Reports are written to:

```text
outputs/reports/
```

## Logs

System actions are logged to:

```text
data/action_log.json
```

Publish attempts are logged to:

```text
data/publish_log.json
```

## Current Safety Boundaries

- Publishing is blocked by default and requires an explicit `--execute` run.
- No browser automation or scraping.
- No Reddit automation.
- Reddit is draft-and-approve only.
- Approval alone does not publish.
- LinkedIn publishing uses the official API only.
- The publish command is blocked by default by `PUBLISHING_KILL_SWITCH=true`.
- Analytics are local/manual until platform analytics APIs are added.
- Every command records an action where useful.
- No secrets in code.
- Technical sources are restricted by `data/approved_sources.json`.
- Drafts containing `[UNVERIFIED]` or `[NEEDS REVIEW]` are blocked by the reviewer.

## Phase 7 Files

- `src/marketing_agents/manager.py` coordinates the workflow.
- `src/marketing_agents/agents.py` contains specialist agents.
- `src/marketing_agents/scheduler.py` prepares weekly batches and processes due publish jobs.
- `src/marketing_agents/approval_queue.py` updates local approval decisions.
- `src/marketing_agents/linkedin_client.py` posts text shares through LinkedIn's official API.
- `src/marketing_agents/publisher.py` enforces approval and kill-switch checks before publishing.
- `src/marketing_agents/metrics.py` records manual performance metrics.
- `src/marketing_agents/analytics.py` creates weekly analytics reports.
- `data/topic_backlog.json` contains 30 starter topics.
- `data/reddit_targets.json` lists manual Reddit target candidates.
- `data/content_log.json` tracks used content.
- `data/approval_queue.json` tracks pending/approved/rejected platform drafts.
- `data/publish_log.json` records publish attempts.
- `data/metrics.json` stores manually recorded metrics.
- `data/action_log.json` records system actions.
- `outputs/` contains generated Markdown packages.
