"""Rebuild the English showcase; preserve original supplied source exports."""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.showcase_data import build


def publish_demo(source, destination):
    """Publish with permissions inherited from the destination folder.

    Moving out of TemporaryDirectory preserves its private Windows ACL.
    Copying bytes to a fresh sibling leaves that ACL behind.
    """
    destination = Path(destination)
    staged = destination.with_name(f".demo-{uuid4().hex}.db")
    try:
        with Path(source).open("rb") as reader, staged.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild the synthetic English showcase")
    parser.add_argument(
        "--database",
        action="store_true",
        help="Also atomically rebuild the published showcase DB and expected totals",
    )
    args = parser.parse_args()
    build()
    if args.database:
        from home_finance_cockpit.localization import set_language
        from home_finance_cockpit.storage import Database
        from tools.create_demo_database import populate
        from tools.showcase_data import EXAMPLE, save_json

        set_language("en")
        folder = EXAMPLE / "database"
        folder.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path = Path(temporary) / "demo.db"
            db = Database.create_new(path)
            try:
                summary = populate(db)
            finally:
                db.close()
            publish_demo(path, folder / "home_finance_demo.db")
        save_json(EXAMPLE / "expected_totals.json", summary)
        print("Published example/database/home_finance_demo.db and expected_totals.json")
