import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def db_path() -> Path:
    url = os.environ.get("HM_DATABASE_URL", "sqlite:///./housing_monitor.db")
    if not url.startswith("sqlite:///"):
        sys.exit("Only SQLite URLs are supported by this script; use pg_dump for PostgreSQL.")
    return Path(url[len("sqlite:///"):])


def backup(dest_dir: str) -> Path:
    src = db_path()
    if not src.exists():
        sys.exit(f"database not found: {src}")
    out_dir = Path(dest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"housing_monitor-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(out) as d:
        s.backup(d)
    with sqlite3.connect(out) as d:
        if d.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("integrity check failed on backup copy")
    os.chmod(out, 0o600)
    return out


def restore(backup_file: str) -> Path:
    src = Path(backup_file)
    with sqlite3.connect(src) as d:
        if d.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("backup file failed integrity check; not restoring")
    dst = db_path()
    if dst.exists():
        keep = dst.with_suffix(f".pre-restore-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db")
        with sqlite3.connect(dst) as cur, sqlite3.connect(keep) as k:
            cur.backup(k)
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    return dst


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("backup", "restore"):
        sys.exit("usage: python scripts/backup.py backup <dir> | restore <file>")
    print(backup(sys.argv[2]) if sys.argv[1] == "backup" else restore(sys.argv[2]))
