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

## Daily Run

```powershell
python -m src.marketing_agents.scheduler
```

With explicit date:

```powershell
python -m src.marketing_agents.scheduler --date 2026-09-28
```

With weekly analytics:

```powershell
python -m src.marketing_agents.scheduler --date 2026-09-28 --weekly
```

## Windows Task Scheduler

Create a daily task that runs from this repo:

```powershell
python -m src.marketing_agents.scheduler
```

Set the task working directory to the repo root:

```text
E:\MyProjects\Marketing-Ai-agent
```

For weekly reporting, create a second weekly task:

```powershell
python -m src.marketing_agents.scheduler --weekly
```

## Approval

Approve a LinkedIn draft:

```powershell
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform linkedin --decision approved
```

Approval does not publish.

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

