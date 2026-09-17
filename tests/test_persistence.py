"""SQLite restart and transaction persistence tests."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from inventory.importer import BatchImportService
from inventory.notifications import NotificationService
from inventory.service import InventoryService


class SQLitePersistenceTests(unittest.TestCase):
    def test_batches_survive_restart_and_dispensing_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "inventory.db")
            first = InventoryService(path)
            first.add_batch("PERSIST-1", "Paracetamol", "2026-12-01", 5)
            first.close()

            second = InventoryService(path)
            self.assertEqual(second.list_batches()[0].quantity, 5)
            second.dispense("Paracetamol", 2, date(2026, 9, 17))
            second.close()

            third = InventoryService(path)
            self.assertEqual(third.list_batches()[0].quantity, 3)
            third.close()

    def test_imported_and_quarantined_state_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "inventory.db")
            first = InventoryService(path)
            BatchImportService(first).import_records(
                [
                    {
                        "batch_id": "IMPORTED",
                        "medicine_name": "Aspirin",
                        "expiry_date": "2026-09-16",
                        "quantity": "4 units",
                    }
                ]
            )
            first.run_clock(date(2026, 9, 17))
            first.close()

            second = InventoryService(path)
            batch = second.list_batches()[0]
            self.assertTrue(batch.quarantined)
            self.assertEqual(second.sellable_stock("Aspirin", date(2026, 9, 17)), 0)
            second.close()

    def test_threshold_and_outbox_survive_restart_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "inventory.db")
            first = InventoryService(path)
            first.add_batch("LOW", "Vitamin C", "2026-12-01", 5)
            notifications = NotificationService(first.database)
            notifications.set_threshold("Vitamin C", 10)
            first.dispense("Vitamin C", 1, date(2026, 9, 17))
            notifications.evaluate_after_dispense(first, "Vitamin C", date(2026, 9, 17))
            self.assertEqual(len(notifications.list_notifications()), 1)
            first.close()

            second = InventoryService(path)
            restarted_notifications = NotificationService(second.database)
            self.assertEqual(len(restarted_notifications.list_notifications()), 1)
            restarted_notifications.evaluate_after_dispense(
                second, "Vitamin C", date(2026, 9, 17)
            )
            self.assertEqual(len(restarted_notifications.list_notifications()), 1)
            second.close()


if __name__ == "__main__":
    unittest.main()
