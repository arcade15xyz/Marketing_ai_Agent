from __future__ import annotations

import argparse

from .manager import ManagerAgent
from .config import append_action


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Markdown-only AOSP content pipeline.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format. Defaults to TIMEZONE local date.")
    args = parser.parse_args()

    paths = ManagerAgent().run(args.date)
    append_action(
        agent="manager",
        action="run_daily",
        result="success",
        details={"date": args.date, "output_dir": str(paths.output_dir)},
    )
    print(f"Wrote daily content package to {paths.output_dir}")
    print(f"Review file: {paths.review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

