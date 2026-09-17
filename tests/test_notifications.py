"""Tests for reorder notifications."""

import unittest
from datetime import date

from inventory.notifications import NotificationService
from inventory.service import InventoryService


class NotificationServiceTests(unittest.TestCase):
    TODAY = date(2026, 9, 17)

    def setUp(self) -> None:
        self.inventory = InventoryService()
        self.notifications = NotificationService()
        self.inventory.add_batch("B-1", "Paracetamol", date(2026, 10, 1), 10)
        self.notifications.set_threshold("paracetamol", 10)

    def test_stock_below_threshold_creates_notification(self) -> None:
        notification = self.notifications.evaluate("Paracetamol", 9, self.TODAY)

        self.assertIsNotNone(notification)
        self.assertEqual(notification.current_sellable_stock, 9)
        self.assertEqual(notification.threshold, 10)
        self.assertEqual(notification.status, "pending")

    def test_equal_or_above_threshold_does_not_notify(self) -> None:
        self.assertIsNone(self.notifications.evaluate("Paracetamol", 10, self.TODAY))
        self.assertIsNone(self.notifications.evaluate("Paracetamol", 11, self.TODAY))
        self.assertEqual(self.notifications.list_notifications(), [])

    def test_repeated_low_stock_state_does_not_duplicate(self) -> None:
        first = self.notifications.evaluate("Paracetamol", 9, self.TODAY)
        second = self.notifications.evaluate("Paracetamol", 8, self.TODAY)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(self.notifications.list_notifications()), 1)

    def test_recovery_allows_a_new_notification_later(self) -> None:
        self.notifications.evaluate("Paracetamol", 9, self.TODAY)
        self.notifications.evaluate("Paracetamol", 10, self.TODAY)
        second = self.notifications.evaluate("Paracetamol", 8, self.TODAY)

        self.assertEqual(second.notification_id, "REORDER-2")
        self.assertEqual(len(self.notifications.list_notifications()), 2)

    def test_successful_dispensing_can_trigger_notification(self) -> None:
        self.inventory.dispense("Paracetamol", 1, self.TODAY)
        notification = self.notifications.evaluate_after_dispense(
            self.inventory, "paracetamol", self.TODAY
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.current_sellable_stock, 9)


if __name__ == "__main__":
    unittest.main()
