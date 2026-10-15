"""Run with python -m pokeradar; all output is JSON."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .core import FixtureAdapter, LiveAdapter, registry, timestamp
from .store import connect, ingest


def main():
    parser = argparse.ArgumentParser(description="PokéRadar offline inventory intelligence (no network)")
    parser.add_argument("--db", default="pokeradar.sqlite3", help="local SQLite path")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("registry", help="show product and disabled source policy")
    commands.add_parser("live", help="explain why live access is disabled")
    for name in ("history", "decisions", "alerts"):
        command = commands.add_parser(name, help="inspect persisted " + name)
        command.add_argument("--limit", type=int, default=20)
    command = commands.add_parser("import", help="normalize and store a local JSON fixture")
    command.add_argument("fixture", type=Path)
    command.add_argument("--demo-rule", action="store_true", help="use SYNTHETIC USD 100.00 rule")
    command.add_argument("--now", type=timestamp, help="explicit replay clock for offline fixtures only")
    args = parser.parse_args()
    try:
        if args.command == "registry":
            result = registry()
        elif args.command == "live":
            LiveAdapter().read("", datetime.now(timezone.utc))
        else:
            with connect(args.db) as connection:
                if args.command == "import":
                    raw = args.fixture.read_text(encoding="utf-8")
                    now = args.now or datetime.now(timezone.utc)
                    result = ingest(connection, raw, FixtureAdapter().read(raw, now), args.demo_rule)
                else:
                    if not 1 <= args.limit <= 1000:
                        raise ValueError("limit must be between 1 and 1000")
                    table = {"history": "observations", "decisions": "decisions", "alerts": "outbox"}[args.command]
                    result = [dict(row) for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (args.limit,))]
                    for row in result:
                        if "payload" in row:
                            row["payload"] = json.loads(row["payload"])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, PermissionError, sqlite3.Error) as error:
        parser.exit(2, f"PokéRadar: {error}\n")


if __name__ == "__main__":
    main()
