"""Tests for the core pharmacy inventory rules."""

import unittest
from datetime import date

from inventory.exceptions import (
    DuplicateBatchError,
    InsufficientStockError,
    ValidationError,
)
from inventory.service import InventoryService


TODAY = date(2026, 9, 17)


class InventoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = InventoryService()

    def test_add_and_list_batch(self) -> None:
        batch = self.inventory.add_batch("B-1", "Paracetamol", "2026-10-01", 20)

        self.assertEqual(batch.batch_id, "B-1")
        self.assertEqual(self.inventory.list_batches(), [batch])

    def test_dispenses_earliest_expiring_batch_regardless_of_insertion_order(self) -> None:
        self.inventory.add_batch("LATER", "Paracetamol", date(2026, 12, 1), 10)
        self.inventory.add_batch("SOONER", "Paracetamol", date(2026, 10, 1), 10)

        dispensed = self.inventory.dispense("Paracetamol", 6, TODAY)

        self.assertEqual([item.batch_id for item in dispensed], ["SOONER"])
        self.assertEqual(dispensed[0].quantity, 6)
        self.assertEqual(self.inventory.sellable_stock("Paracetamol", TODAY), 14)

    def test_dispenses_across_multiple_batches(self) -> None:
        self.inventory.add_batch("FIRST", "Ibuprofen", date(2026, 9, 18), 4)
        self.inventory.add_batch("SECOND", "Ibuprofen", date(2026, 9, 20), 5)

        dispensed = self.inventory.dispense("Ibuprofen", 7, TODAY)

        self.assertEqual(
            [(item.batch_id, item.quantity) for item in dispensed],
            [("FIRST", 4), ("SECOND", 3)],
        )
        self.assertEqual(self.inventory.sellable_stock("Ibuprofen", TODAY), 2)

    def test_expired_batches_are_not_dispensed(self) -> None:
        self.inventory.add_batch("EXPIRED", "Aspirin", date(2026, 9, 16), 50)

        with self.assertRaises(InsufficientStockError):
            self.inventory.dispense("Aspirin", 1, TODAY)

        self.assertEqual(self.inventory.list_batches()[0].quantity, 50)

    def test_batch_expiring_today_is_sellable(self) -> None:
        self.inventory.add_batch("TODAY", "Cetirizine", TODAY, 7)

        self.assertEqual(self.inventory.sellable_stock("Cetirizine", TODAY), 7)
        self.assertEqual(self.inventory.dispense("Cetirizine", 7, TODAY)[0].quantity, 7)

    def test_insufficient_stock_does_not_change_any_batch(self) -> None:
        self.inventory.add_batch("FIRST", "Vitamin C", date(2026, 9, 18), 3)
        self.inventory.add_batch("SECOND", "Vitamin C", date(2026, 9, 19), 2)

        with self.assertRaises(InsufficientStockError):
            self.inventory.dispense("Vitamin C", 6, TODAY)

        self.assertEqual(self.inventory.sellable_stock("Vitamin C", TODAY), 5)

    def test_search_finds_available_medicine_and_sellable_batches(self) -> None:
        self.inventory.add_batch("VALID", "Paracetamol", date(2026, 9, 20), 8)
        self.inventory.add_batch("OLD", "Paracetamol", date(2026, 9, 16), 100)

        result = self.inventory.search_medicine("paracetamol", TODAY)

        self.assertTrue(result["available"])
        self.assertEqual(result["sellable_quantity"], 8)
        self.assertEqual([batch.batch_id for batch in result["batches"]], ["VALID"])

    def test_search_reports_unavailable_medicine(self) -> None:
        result = self.inventory.search_medicine("Unknown", TODAY)

        self.assertFalse(result["available"])
        self.assertEqual(result["sellable_quantity"], 0)
        self.assertEqual(result["batches"], [])

    def test_expiry_alerts_ignore_expired_and_include_configured_window(self) -> None:
        self.inventory.add_batch("EXPIRED", "Amoxicillin", date(2026, 9, 16), 5)
        self.inventory.add_batch("IN-WINDOW", "Amoxicillin", date(2026, 9, 20), 6)
        self.inventory.add_batch("OUTSIDE", "Amoxicillin", date(2026, 9, 25), 7)

        alerts = self.inventory.expiry_alerts(3, TODAY)

        self.assertEqual([batch.batch_id for batch in alerts], ["IN-WINDOW"])

    def test_rejects_invalid_quantities(self) -> None:
        for quantity in (0, -1, True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self.inventory.add_batch("B-1", "Medicine", TODAY, quantity)

    def test_rejects_empty_names_invalid_dates_and_invalid_batch_ids(self) -> None:
        invalid_values = (
            ("", "Medicine", TODAY, 1),
            ("B-1", "   ", TODAY, 1),
            ("B-1", "Medicine", "not-a-date", 1),
        )
        for batch_id, medicine_name, expiry_date, quantity in invalid_values:
            with self.subTest(batch_id=batch_id, medicine_name=medicine_name):
                with self.assertRaises(ValidationError):
                    self.inventory.add_batch(batch_id, medicine_name, expiry_date, quantity)

    def test_rejects_duplicate_batch_ids(self) -> None:
        self.inventory.add_batch("B-1", "Medicine", TODAY, 1)

        with self.assertRaises(DuplicateBatchError):
            self.inventory.add_batch("B-1", "Other Medicine", TODAY, 1)


if __name__ == "__main__":
    unittest.main()