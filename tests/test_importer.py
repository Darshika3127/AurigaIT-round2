"""Tests for messy batch imports."""

import unittest

from inventory.importer import BatchImportService
from inventory.service import InventoryService


class BatchImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = InventoryService(":memory:")
        self.importer = BatchImportService(self.inventory)

    def test_imports_messy_quantities_and_supported_dates(self) -> None:
        report = self.importer.import_records(
            [
                {
                    "batch_id": "ISO-1",
                    "medicine_name": "Paracetamol",
                    "expiry_date": "2026-10-01",
                    "quantity": "10 units",
                },
                {
                    "batch_id": "EU-1",
                    "medicine_name": "Ibuprofen",
                    "expiry_date": "01/10/2026",
                    "quantity": "10",
                },
            ]
        )

        self.assertEqual(report["imported"], 2)
        self.assertEqual(report["deduped"], 0)
        self.assertEqual(report["rejected"], 0)
        self.assertEqual(self.inventory.list_batches()[0].quantity, 10)
        self.assertEqual(self.inventory.list_batches()[1].expiry_date.isoformat(), "2026-10-01")

    def test_null_and_invalid_rows_are_rejected_without_partial_row_creation(self) -> None:
        report = self.importer.import_records(
            [
                {"batch_id": None, "medicine_name": "Medicine", "expiry_date": "2026-10-01", "quantity": 1},
                {"batch_id": "BAD-Q", "medicine_name": "Medicine", "expiry_date": "2026-10-01", "quantity": "ten units"},
                {"batch_id": "BAD-D", "medicine_name": "Medicine", "expiry_date": "31/02/2026", "quantity": 1},
                {"batch_id": "BAD-N", "medicine_name": None, "expiry_date": "2026-10-01", "quantity": 1},
            ]
        )

        self.assertEqual(report["imported"], 0)
        self.assertEqual(report["rejected"], 4)
        self.assertEqual(len(self.inventory.list_batches()), 0)
        self.assertEqual([error["row"] for error in report["errors"]], [1, 2, 3, 4])

    def test_identical_and_existing_batch_ids_are_deduped(self) -> None:
        self.inventory.add_batch("EXISTING", "Medicine", "2026-10-01", 4)
        record = {
            "batch_id": "NEW",
            "medicine_name": "Medicine",
            "expiry_date": "2026-10-01",
            "quantity": 2,
        }

        report = self.importer.import_records(
            [record, record.copy(), {**record, "batch_id": "EXISTING"}]
        )

        self.assertEqual(report["imported"], 1)
        self.assertEqual(report["deduped"], 2)
        self.assertEqual(report["rejected"], 0)
        self.assertEqual(len(self.inventory.list_batches()), 2)

    def test_mixed_import_statistics_are_correct(self) -> None:
        report = self.importer.import_records(
            [
                {"batch_id": "GOOD", "medicine_name": "Medicine", "expiry_date": "2026-10-01", "quantity": 3},
                {"batch_id": "GOOD", "medicine_name": "Medicine", "expiry_date": "2026-10-01", "quantity": 3},
                {"batch_id": "BAD", "medicine_name": "Medicine", "expiry_date": "wrong", "quantity": 3},
            ]
        )

        self.assertEqual(
            {key: report[key] for key in ("imported", "deduped", "rejected")},
            {"imported": 1, "deduped": 1, "rejected": 1},
        )
        self.assertEqual(report["errors"][0]["row"], 3)

    def test_non_array_payload_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "JSON array"):
            self.importer.import_records({})


if __name__ == "__main__":
    unittest.main()
