"""Start the SmartBrew AI prototype.

Usage:
    python main.py                 # GUI with the persistent smartbrew.db
    python main.py --db demo.db    # use another database file
    python main.py --reset         # delete the database first (fresh demo data)
"""

from __future__ import annotations

import argparse
import os


def parse_args() -> argparse.Namespace:
    """Read command-line options.

    Returns:
        argparse.Namespace: ``db`` (path) and ``reset`` (bool).
    """
    parser = argparse.ArgumentParser(description="SmartBrew AI coffee machine prototype")
    parser.add_argument("--db", default="smartbrew.db", help="SQLite database file")
    parser.add_argument("--reset", action="store_true", help="start from fresh demo data")
    return parser.parse_args()


def main() -> None:
    """Entry point: optionally reset the database, then open the GUI.

    Returns:
        None.
    """
    args = parse_args()
    if args.reset and os.path.exists(args.db):
        os.remove(args.db)
    from smartbrew.ui.app import run

    run(args.db)


if __name__ == "__main__":
    main()
