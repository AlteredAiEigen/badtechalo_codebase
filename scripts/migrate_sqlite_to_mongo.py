#!/usr/bin/env python3
"""One-time migration from SQLite assignment_platform.db to MongoDB."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config_env import load_all_dotenv
from app.db.mongo import col, ping_mongo


def main() -> None:
    load_all_dotenv()
    if not ping_mongo():
        print("MongoDB not reachable")
        sys.exit(1)
    try:
        from sqlalchemy import create_engine, text
        from app.db.database import DATABASE_URL
    except Exception as exc:
        print(f"SQLite unavailable: {exc}")
        return

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        for table, seq in [
            ("books", "books"),
            ("chunks", "chunks"),
            ("assignments", "assignments"),
            ("submissions", "submissions"),
        ]:
            try:
                rows = conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
            except Exception:
                continue
            if not rows:
                continue
            col(table).delete_many({})
            max_id = 0
            for row in rows:
                doc = dict(row)
                rid = doc.get("id")
                if rid is not None:
                    max_id = max(max_id, int(rid))
                    doc["_id"] = int(rid)
                for k, v in list(doc.items()):
                    if hasattr(v, "isoformat"):
                        doc[k] = v.isoformat()
                    elif isinstance(v, (dict, list)):
                        pass
                    elif v is not None and not isinstance(v, (str, int, float, bool)):
                        doc[k] = str(v)
                col(table).insert_one(doc)
            col("counters").update_one({"_id": seq}, {"$set": {"seq": max_id}}, upsert=True)
            print(f"Migrated {len(rows)} rows from {table}")


if __name__ == "__main__":
    main()
