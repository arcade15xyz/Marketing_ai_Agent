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
## Run

```powershell
python -m src.marketing_agents.run_daily
```

With an explicit date:

```powershell
python -m src.marketing_agents.run_daily --date 2026-09-28
```

Scheduler-friendly entry point:

```powershell
python -m src.marketing_agents.scheduler --date 2026-09-28
```

Daily plus weekly report:

```powershell
python -m src.marketing_agents.scheduler --date 2026-09-28 --weekly
```

Outputs are written to:

```text
outputs/YYYY-MM-DD/
```

## Approve Or Reject Drafts

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
- `src/marketing_agents/scheduler.py` provides scheduler-friendly daily and weekly runs.
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

