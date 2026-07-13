"""CLI do relatório diário."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .db import Database
from .report import build_daily_report


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config.json").read_text())
    db_path = Path(config["database"])
    if not db_path.is_absolute():
        db_path = root / db_path
    db = Database(db_path)
    db.initialize()
    today = datetime.now().date()
    report = build_daily_report(db, today)
    output = root / "reports" / f"candidaturas-{today.isoformat()}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
