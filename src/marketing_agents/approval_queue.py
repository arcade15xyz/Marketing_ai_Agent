from __future__ import annotations

import argparse
from datetime import datetime

from .config import DATA_DIR, append_action, read_json, timezone, write_json
from .db import configured_session_factory, storage_backend
from .repositories import LifecycleRepository


VALID_DECISIONS = {"approved", "rejected", "needs_changes"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the local approval queue.")
    parser.add_argument("--date", required=True, help="Content date in YYYY-MM-DD format.")
    parser.add_argument("--platform", required=True, help="Platform name, for example blog or linkedin.")
    parser.add_argument("--decision", required=True, choices=sorted(VALID_DECISIONS))
    parser.add_argument("--note", default="", help="Optional approval note.")
    args = parser.parse_args()
    if storage_backend() == "database":
        return update_database_approval(args.date, args.platform, args.decision, args.note)


    queue_path = DATA_DIR / "approval_queue.json"
    queue = read_json(queue_path)
    matched = False

    for item in queue:
        if item.get("date") == args.date and item.get("platform") == args.platform:
            item["approval_status"] = args.decision
            item["decision_note"] = args.note
            item["decided_at"] = datetime.now(timezone()).isoformat(timespec="seconds")
            matched = True
            break

    if not matched:
        raise SystemExit(f"No approval item found for {args.date} / {args.platform}")

    write_json(queue_path, queue)
    append_action(
        agent="manager",
        action="approval_decision",
        result=args.decision,
        details={"date": args.date, "platform": args.platform, "note": args.note},
    )
    print(f"Updated {args.date} / {args.platform} to {args.decision}")
    return 0



def update_database_approval(date: str, platform: str, decision: str, note: str) -> int:
    with configured_session_factory()() as session:
        repository = LifecycleRepository(session)
        approval = repository.decide_approval(
            run_id=f"daily-{date}",
            channel=platform,
            decision=decision,
            note=note,
        )
        if approval is None:
            approval = repository.decide_approval(
                run_id=f"legacy-{date}",
                channel=platform,
                decision=decision,
                note=note,
            )
        if approval is None:
            raise SystemExit(f"No database approval item found for {date} / {platform}")
        session.commit()

    append_action(
        agent="manager",
        action="approval_decision",
        result=decision,
        details={"date": date, "platform": platform, "note": note, "storage": "database"},
    )
    print(f"Updated database approval {date} / {platform} to {decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
