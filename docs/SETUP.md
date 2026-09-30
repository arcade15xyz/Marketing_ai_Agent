# Setup

## Requirements

- Python 3.11 or newer.
- Install project dependencies before using database commands.
- PostgreSQL 14 or newer for database-backed operation.
- Install the project dependencies with `python -m pip install -e .`.
- JSON remains the default storage backend during this incremental step.
- Internet access only for future API publishing or live research integrations.

## Environment

Copy `.env.example` to `.env` and fill in values as needed.

```powershell
copy .env.example .env
```
The application loads the repository-root `.env` file automatically.

Required for local drafting:

- `TIMEZONE=Asia/Calcutta`
- `DAILY_POST_TIME=09:30`
- `COMPANY_NAME="Ftechiz Pvt. Ltd."`


## PostgreSQL Persistence

Create a PostgreSQL database and set a Psycopg-compatible connection URL:

```text
DATABASE_URL=postgresql+psycopg://marketing:your-password@localhost:5432/marketing_ai
```

Apply the schema migration:

```powershell
python -m alembic upgrade head
```

Validate the legacy JSON import without committing it:

```powershell
python -m src.marketing_agents.import_json --dry-run
```

Import the existing backlog and lifecycle state:

```powershell
python -m src.marketing_agents.import_json
```

After the migration and import succeed, activate database-backed daily runs,
approvals, and publishing:

```text
STORAGE_BACKEND=database
```

Metrics and analytics remain JSON-backed until the analytics migration phase.

Required only for LinkedIn publishing:

- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_AUTHOR_URN`
- `PUBLISHING_KILL_SWITCH=false`

Keep `PUBLISHING_KILL_SWITCH=true` until you intentionally publish.

## LinkedIn API Setup

Use LinkedIn's official developer flow only.

1. Create or open a LinkedIn Developer app.
2. Add the Share on LinkedIn product.
3. Request OAuth scope `w_member_social`.
4. Complete OAuth for the member profile.
5. Set `LINKEDIN_ACCESS_TOKEN`.
6. Set `LINKEDIN_AUTHOR_URN`, for example `urn:li:person:{id}`.

Official docs:

- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- https://learn.microsoft.com/en-us/linkedin/compliance/integrations/shares/ugc-post-api

## Weekly Preparation

JSON mode validates and imports the supplied complete content:

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json --dry-run
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --input data/weekly/2026-10-05.json
```

AI mode uses the configured provider. Its dry-run only checks database state and
topic capacity, so it does not spend tokens:

```powershell
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05 --dry-run
python -m src.marketing_agents.scheduler prepare-week --week-start 2026-10-05
```

## Due Publishing

`publish-due` never generates content. It selects only due LinkedIn jobs whose
content is approved and queued. Without `--execute`, it records dry-run events.

```powershell
python -m src.marketing_agents.scheduler publish-due
python -m src.marketing_agents.scheduler publish-due --execute
```

The execute form still requires `PUBLISHING_KILL_SWITCH=false` and valid
LinkedIn credentials.

## Windows Task Scheduler

After publish slots are created by the scheduling phase, configure a frequent
task for due jobs:

```powershell
python -m src.marketing_agents.scheduler publish-due --execute
```

Set the task working directory to the repository root. Create a separate weekly
task for `prepare-week`, using `--input` in JSON mode.

The previous workflow remains available temporarily:

```powershell
python -m src.marketing_agents.scheduler legacy-daily --date 2026-09-28
```

## Approval

Weekly JSON and AI preparation automatically create pending approval records.
Start the FastAPI service, open `/docs`, and use:

- `GET /approvals?status=pending`
- `POST /content/{content_item_id}/approval`
- `GET /batches/{batch_id}/approval-status`
- `POST /batches/{batch_id}/approvals/sync` for older batches

The approval request body is, for example:

```json
{"decision": "approved", "note": "Reviewed against primary sources."}
```

Every master and each derivative with status `queued_for_approval` is required.
When all required records are approved, the batch automatically becomes
`ready`. A changed decision returns it to `pending_approval` until publishing
starts; publishing and terminal batch states lock approval changes.

The previous daily JSON approval command remains available:

```powershell
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform linkedin --decision approved
```

Approval does not publish or create publish jobs.

## Publish LinkedIn

Dry-run:

```powershell
python -m src.marketing_agents.publisher --date 2026-09-28 --platform linkedin
```

Publish:

```powershell
python -m src.marketing_agents.publisher --date 2026-09-28 --platform linkedin --execute
```

## Kill Switch

Set this to block all publishing:

```powershell
$env:PUBLISHING_KILL_SWITCH='true'
```

Keep this in `.env` by default:

```text
PUBLISHING_KILL_SWITCH=true
```

The publisher refuses to run while the kill switch is enabled.
