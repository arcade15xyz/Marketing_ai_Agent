# Operations

## Daily Workflow

1. Run the scheduler.
2. Review `outputs/YYYY-MM-DD/PACKAGE.md`.
3. Review platform drafts.
4. Approve, reject, or request changes using the approval queue CLI.
5. Publish LinkedIn only after approval and with the kill switch intentionally disabled.
6. Record metrics after content has had time to perform.
7. Generate a weekly report.

## Files To Watch

- `outputs/YYYY-MM-DD/` contains daily content packages.
- `data/approval_queue.json` contains approval state.
- `data/action_log.json` contains system actions.
- `data/publish_log.json` contains publishing attempts.
- `data/metrics.json` contains manual metrics.
- `outputs/reports/` contains weekly analytics.

## Safe Defaults

- Publishing is blocked by default.
- Reddit cannot be published by the publisher.
- LinkedIn publishing requires official API credentials and `--execute`.
- Approval alone does not publish.
- An item already marked as published cannot be published again.
- A new daily run stops instead of silently reusing an exhausted topic backlog.

## Baseline Tests

Run the dependency-free regression suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

