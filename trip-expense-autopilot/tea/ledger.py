import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ALLOWED = {
    ('new', 'drafted'),
    ('new', 'submitted'),
    ('new', 'skipped'),
    ('drafted', 'drafted'),
    ('drafted', 'submitted'),
    ('drafted', 'skipped'),
    ('new', 'submitting'),
    ('drafted', 'submitting'),
    ('submitting', 'submitted'),
}


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self._create_table()

    def _create_table(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS ledger (
                txn_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                ref TEXT,
                updated_at TEXT NOT NULL
            )
        ''')
        self.conn.commit()

    def get(self, txn_id: str) -> Optional[str]:
        cur = self.conn.execute(
            'SELECT status FROM ledger WHERE txn_id = ?', (txn_id,))
        row = cur.fetchone()
        return row[0] if row else None

    def set(self, txn_id: str, status: str, ref: Optional[str] = None) -> None:
        if status not in ('drafted', 'submitting', 'submitted', 'skipped'):
            raise ValueError(f"Unknown status: {status}")
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            self._set_locked(txn_id, status, ref)
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        self.conn.execute('COMMIT')

    def _set_locked(self, txn_id: str, status: str, ref: Optional[str]) -> None:
        current = self.get(txn_id)
        frm = current if current is not None else 'new'
        if frm == 'submitted':
            raise ValueError("Cannot modify submitted transaction")
        if frm == 'submitting' and status != 'submitted':
            raise ValueError("Transaction may already be on Deel; verify manually, then call resolve_submitting()")
        if (frm, status) not in _ALLOWED:
            raise ValueError(f"Invalid status transition: {frm} -> {status}")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            'INSERT INTO ledger (txn_id, status, ref, updated_at) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(txn_id) DO UPDATE SET status=excluded.status, '
            'ref=COALESCE(excluded.ref, ledger.ref), updated_at=excluded.updated_at',
            (txn_id, status, ref, now),
        )

    def resolve_submitting(self, txn_id: str, submitted: bool, ref: Optional[str] = None) -> None:
        if self.get(txn_id) != 'submitting':
            raise ValueError("resolve_submitting only allowed for submitting transactions")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            'UPDATE ledger SET status=?, ref=COALESCE(?, ref), updated_at=? WHERE txn_id=?',
            ('submitted' if submitted else 'drafted', ref, now, txn_id),
        )

    def reopen(self, txn_id: str) -> None:
        if self.get(txn_id) != 'skipped':
            raise ValueError("reopen only allowed for skipped transactions")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            'UPDATE ledger SET status=?, updated_at=? WHERE txn_id=?',
            ('drafted', now, txn_id),
        )
        self.conn.commit()

    def all(self) -> list[dict]:
        cur = self.conn.execute(
            'SELECT txn_id, status, ref, updated_at FROM ledger ORDER BY updated_at')
        return [
            {'txn_id': r[0], 'status': r[1], 'ref': r[2], 'updated_at': r[3]}
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> 'Ledger':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
