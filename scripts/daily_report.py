"""Daily spending text report — run by cron at 7:00 AM (Phase 7a).

    python -m scripts.daily_report            # sync, then send via NOTIFY_CHANNEL
    python -m scripts.daily_report --dry-run   # build + print, don't send
    python -m scripts.daily_report --no-sync   # skip the data refresh

Cron example (on the Pi):
    0 7 * * *  cd /home/pi/finance_dashboard && .venv/bin/python -m scripts.daily_report >> logs/daily.log 2>&1
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime

# Make the project importable when run directly (python scripts/daily_report.py).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ingest import sync          # noqa: E402
from notify import channels, report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the daily spending text.")
    parser.add_argument("--dry-run", action="store_true", help="build + print, don't send")
    parser.add_argument("--no-sync", action="store_true", help="skip the data refresh")
    args = parser.parse_args()

    stamp = datetime.now().isoformat(timespec="seconds")

    if not args.no_sync:
        result = sync.run_sync()
        print(f"[{stamp}] sync: {result.message} ({result.transactions} txns)")

    rep = report.build_report()
    print(rep["text"])

    if args.dry_run:
        print("[dry-run] not sent")
        return

    status = channels.send(rep["text"])
    print(f"[{stamp}] {status}")


if __name__ == "__main__":
    main()
