"""Tests for the Flask inventory API."""

import unittest

from app import create_app
from inventory.service import InventoryService


class FlaskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = create_app(InventoryService(":memory:")).test_client()

    def add_batch(self, batch_id: str, medicine: str, expiry: str, quantity: int):
        return self.client.post(
            "/api/batches",
            json={
                "batch_id": batch_id,
                "medicine_name": medicine,
                "expiry_date": expiry,
                "quantity": quantity,
            },
        )

    def test_add_and_list_batches_return_json(self) -> None:
        response = self.add_batch("B-1", "Paracetamol", "2099-10-01", 20)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["batch"]["expiry_date"], "2099-10-01")
        listed = self.client.get("/api/batches")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json["batches"]), 1)

    def test_dispense_uses_fefo_and_returns_dispensed_batches(self) -> None:
        self.add_batch("LATER", "Paracetamol", "2099-12-01", 10)
        self.add_batch("SOONER", "Paracetamol", "2099-10-01", 10)

        response = self.client.post(
            "/api/dispense", json={"medicine_name": "paracetamol", "quantity": 6}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["dispensed"][0]["batch_id"], "SOONER")

    def test_validation_and_business_errors_have_clear_statuses(self) -> None:
        invalid = self.client.post("/api/batches", json={"quantity": 0})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("error", invalid.json)

        self.add_batch("B-1", "Medicine", "2099-10-01", 1)
        duplicate = self.add_batch("B-1", "Medicine", "2099-10-01", 1)
        self.assertEqual(duplicate.status_code, 409)

        insufficient = self.client.post(
            "/api/dispense", json={"medicine_name": "Medicine", "quantity": 2}
        )
        self.assertEqual(insufficient.status_code, 409)

    def test_stock_search_and_alerts_endpoints(self) -> None:
        self.add_batch("ALERT", "Aspirin", "2099-10-01", 4)

        stock = self.client.get("/api/stock/Aspirin")
        search = self.client.get("/api/search?name=aspirin")
        alerts = self.client.get("/api/alerts?days=7")

        self.assertEqual(stock.json["sellable_quantity"], 4)
        self.assertTrue(search.json["available"])
        self.assertEqual(alerts.status_code, 200)

    def test_alert_days_must_be_an_integer(self) -> None:
        response = self.client.get("/api/alerts?days=soon")
        self.assertEqual(response.status_code, 400)

    def test_health_endpoint_returns_ok(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_clock_endpoint_is_idempotent(self) -> None:
        self.add_batch("OLD", "Medicine", "2026-09-16", 5)
        self.add_batch("TODAY", "Medicine", "2026-09-17", 2)

        first = self.client.post("/clock", json={"today": "2026-09-17"})
        second = self.client.post("/clock", json={"today": "2026-09-17"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["newly_quarantined_batch_ids"], ["OLD"])
        self.assertEqual(second.json["newly_quarantined_batch_ids"], [])
        self.assertEqual(second.json["already_quarantined"], 1)

    def test_import_endpoint_returns_row_statistics(self) -> None:
        response = self.client.post(
            "/api/import",
            json=[
                {
                    "batch_id": "IMPORT-1",
                    "medicine_name": "Medicine",
                    "expiry_date": "17/10/2026",
                    "quantity": "10 units",
                },
                {"batch_id": "IMPORT-1", "medicine_name": "Medicine", "expiry_date": "2026-10-17", "quantity": 10},
                {"batch_id": "BAD", "medicine_name": None, "expiry_date": "2026-10-17", "quantity": 1},
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {key: response.json[key] for key in ("imported", "deduped", "rejected")},
            {"imported": 1, "deduped": 1, "rejected": 1},
        )

    def test_reorder_threshold_and_outbox_after_dispensing(self) -> None:
        self.add_batch("LOW-STOCK", "Paracetamol", "2099-10-01", 10)
        threshold = self.client.post(
            "/api/reorder-thresholds",
            json={"medicine_name": "paracetamol", "threshold": 10},
        )
        dispense = self.client.post(
            "/api/dispense", json={"medicine_name": "Paracetamol", "quantity": 1}
        )
        outbox = self.client.get("/outbox")

        self.assertEqual(threshold.status_code, 200)
        self.assertEqual(dispense.status_code, 200)
        self.assertEqual(len(outbox.json["notifications"]), 1)
        self.assertEqual(outbox.json["notifications"][0]["medicine_name"], "paracetamol")

    def test_reorder_threshold_does_not_duplicate_low_stock_notification(self) -> None:
        self.add_batch("LOW-STOCK", "Medicine", "2099-10-01", 5)
        self.client.post(
            "/api/reorder-thresholds",
            json={"medicine_name": "Medicine", "threshold": 10},
        )
        self.client.post(
            "/api/dispense", json={"medicine_name": "Medicine", "quantity": 1}
        )
        self.client.post(
            "/api/dispense", json={"medicine_name": "Medicine", "quantity": 1}
        )

        response = self.client.get("/outbox")

        self.assertEqual(len(response.json["notifications"]), 1)


if __name__ == "__main__":
    unittest.main()