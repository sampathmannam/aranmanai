"""Daily CMC sweep — runs every morning at 9am.

This is what makes Kishore's loop actually work. Without this cron,
the daily sweep only runs when manually called.

Setup (Windows Task Scheduler):
    schtasks /create /tn "Aranmanai CMC Sweep" /tr "python C:\\path\\to\\scripts\\daily_cmc_sweep.py" /sc daily /st 09:00

Setup (Linux cron):
    0 9 * * * cd /path/to/aranmanai && python scripts/daily_cmc_sweep.py

What it does:
1. Run CMC overdue sweep (mark overdue + raise escalations)
2. Print summary of the daily view for each district
3. Send alert notifications to SPs (via the Alert model — surfaced in the API)
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from aranmanai.ai.services.cmc_loop import CmcLoopService
from aranmanai.config import get_settings
from aranmanai.db import SessionLocal
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger, setup_logging

log = get_logger(__name__)


def main() -> None:
    setup_logging()
    settings = get_settings()
    log.info("daily_sweep.start env=%s", settings.environment)

    db = SessionLocal()
    try:
        svc = CmcLoopService(db)
        n_esc = svc.check_overdue()
        log.info("daily_sweep.sweep_done escalations_raised=%d", n_esc)

        # Print per-district summary
        districts = db.query(User.district).filter(User.role == UserRole.SP).distinct().all()
        districts = [d[0] for d in districts if d[0]]

        today = date.today()
        print(f"\n=== Daily CMC sweep — {today.isoformat()} ===")
        print(f"  Overdue actions marked: {n_esc}")
        print()

        for district in districts:
            view = svc.daily_view(district=district, target_date=today)
            print(f"District: {district}")
            print(f"  Hearings today: {view.n_hearings}")
            print(f"  Pending actions: {view.n_actions_pending}")
            print(f"  Overdue actions: {view.n_actions_overdue}")
            print(f"  Open escalations: {view.n_escalations_open}")
            print(f"  Cases unreviewed by SP: {view.n_cases_unreviewed}")
            if view.top_priority:
                print(f"  Top priority:")
                for a in view.top_priority[:3]:
                    print(f"    - [{a['priority']}] {a['description'][:60]} (FIR: {a['fir_no']})")
            print()

        log.info("daily_sweep.done districts=%d", len(districts))
    finally:
        db.close()


if __name__ == "__main__":
    main()
