# Approval Queue

Run date: 2026-09-28

Technical review status: pass

Publishing status: not_enabled

## Approval Instructions

Use the local queue CLI to approve or reject a platform draft:

```powershell
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform linkedin --decision approved
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform blog --decision rejected
python -m src.marketing_agents.approval_queue --date 2026-09-28 --platform reddit --decision needs_changes --note "Check r/androiddev rules first."
```

Approval only updates local state. It does not publish.

## Items

- Platform: blog
  Status: pending
  Draft status: queued_for_approval
  Title: Android.bp mistakes that slow down platform teams
- Platform: linkedin
  Status: pending
  Draft status: queued_for_approval
  Title: Android.bp mistakes that slow down platform teams
- Platform: reddit
  Status: pending
  Draft status: needs_rules_check
  Title: Android.bp mistakes that slow down platform teams
