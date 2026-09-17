"""SQLite persistence for inventory and notification state."""

import sqlite3
from datetime import date
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Iterable, List, Optional, Tuple

from .exceptions import DuplicateBatchError
from .models import Batch


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class SQLiteDatabase:
    """Small SQLite repository shared by the inventory and notification services."""

    def __init__(self, path: str = "inventory.db") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY,
                medicine_name TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                quarantined INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reorder_thresholds (
                medicine_key TEXT PRIMARY KEY,
                medicine_name TEXT NOT NULL,
                threshold INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notification_state (
                medicine_key TEXT PRIMARY KEY,
                low_stock_active INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                medicine_name TEXT NOT NULL,
                current_sellable_stock INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_date TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    @_synchronized
    def list_batches(self) -> List[Batch]:
        rows = self.connection.execute(
            "SELECT * FROM batches ORDER BY rowid"
        ).fetchall()
        return [self._batch_from_row(row) for row in rows]

    @_synchronized
    def insert_batch(self, batch: Batch) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO batches
                    (batch_id, medicine_name, expiry_date, quantity, quarantined)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    batch.batch_id,
                    batch.medicine_name,
                    batch.expiry_date.isoformat(),
                    batch.quantity,
                    int(batch.quarantined),
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            self.connection.rollback()
            raise DuplicateBatchError(
                f"Batch ID already exists: {batch.batch_id}"
            ) from error

    @_synchronized
    def update_batch(self, batch: Batch) -> None:
        self.connection.execute(
            """
            UPDATE batches
            SET medicine_name = ?, expiry_date = ?, quantity = ?, quarantined = ?
            WHERE batch_id = ?
            """,
            (
                batch.medicine_name,
                batch.expiry_date.isoformat(),
                batch.quantity,
                int(batch.quarantined),
                batch.batch_id,
            ),
        )
        self.connection.commit()

    @_synchronized
    def update_quantities(self, allocations: Iterable[Tuple[str, int]]) -> None:
        allocations = list(allocations)
        with self.connection:
            for batch_id, quantity in allocations:
                cursor = self.connection.execute(
                    """
                    UPDATE batches
                    SET quantity = quantity - ?
                    WHERE batch_id = ? AND quantity >= ? AND quarantined = 0
                    """,
                    (quantity, batch_id, quantity),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"Unable to update batch: {batch_id}")

    @_synchronized
    def quarantine_expired(self, current_date: date) -> List[str]:
        rows = self.connection.execute(
            """
            SELECT batch_id FROM batches
            WHERE expiry_date < ? AND quarantined = 0
            ORDER BY rowid
            """,
            (current_date.isoformat(),),
        ).fetchall()
        batch_ids = [row["batch_id"] for row in rows]
        with self.connection:
            self.connection.execute(
                """
                UPDATE batches SET quarantined = 1
                WHERE expiry_date < ? AND quarantined = 0
                """,
                (current_date.isoformat(),),
            )
        return batch_ids

    @_synchronized
    def get_threshold(self, medicine_key: str) -> Optional[Tuple[str, int]]:
        row = self.connection.execute(
            "SELECT medicine_name, threshold FROM reorder_thresholds WHERE medicine_key = ?",
            (medicine_key,),
        ).fetchone()
        return None if row is None else (row["medicine_name"], row["threshold"])

    @_synchronized
    def set_threshold(self, medicine_key: str, medicine_name: str, threshold: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO reorder_thresholds (medicine_key, medicine_name, threshold)
                VALUES (?, ?, ?)
                ON CONFLICT(medicine_key) DO UPDATE SET
                    medicine_name = excluded.medicine_name,
                    threshold = excluded.threshold
                """,
                (medicine_key, medicine_name, threshold),
            )

    @_synchronized
    def low_stock_active(self, medicine_key: str) -> bool:
        row = self.connection.execute(
            "SELECT low_stock_active FROM notification_state WHERE medicine_key = ?",
            (medicine_key,),
        ).fetchone()
        return bool(row["low_stock_active"]) if row is not None else False

    @_synchronized
    def set_low_stock_active(self, medicine_key: str, active: bool) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO notification_state (medicine_key, low_stock_active)
                VALUES (?, ?)
                ON CONFLICT(medicine_key) DO UPDATE SET
                    low_stock_active = excluded.low_stock_active
                """,
                (medicine_key, int(active)),
            )

    @_synchronized
    def next_notification_id(self) -> str:
        row = self.connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTR(notification_id, 9) AS INTEGER)), 0) + 1 AS next_id
            FROM notifications
            WHERE notification_id LIKE 'REORDER-%'
            """
        ).fetchone()
        return f"REORDER-{row['next_id']}"

    @_synchronized
    def insert_notification(self, values: tuple) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO notifications
                    (notification_id, medicine_name, current_sellable_stock,
                     threshold, notification_type, message, created_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    @_synchronized
    def list_notifications(self) -> list:
        return self.connection.execute(
            "SELECT * FROM notifications ORDER BY rowid"
        ).fetchall()

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> Batch:
        return Batch(
            batch_id=row["batch_id"],
            medicine_name=row["medicine_name"],
            expiry_date=date.fromisoformat(row["expiry_date"]),
            quantity=row["quantity"],
            quarantined=bool(row["quarantined"]),
        )

    @_synchronized
    def close(self) -> None:
        self.connection.close()
