"""Tests for the Flask inventory API."""

import unittest

from app import create_app
from inventory.service import InventoryService


class FlaskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = create_app(InventoryService(":memory:")).test_client()
        self.client.post("/api/register", json={"username": "tester", "password": "password123"})
        self.client.post("/api/login", json={"username": "tester", "password": "password123"})

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

    def test_registration_login_logout_and_protected_route(self) -> None:
        client = create_app(InventoryService(":memory:")).test_client()
        self.assertEqual(client.get("/api/batches").status_code, 200)
        self.assertEqual(client.post("/api/batches", json={"batch_id": "X", "medicine_name": "M", "expiry_date": "2099-01-01", "quantity": 1}).status_code, 401)
        self.assertEqual(client.post("/api/register", json={"username": "alice", "password": "password123"}).status_code, 201)
        self.assertEqual(client.post("/api/register", json={"username": "alice", "password": "password123"}).status_code, 409)
        self.assertEqual(client.post("/api/login", json={"username": "alice", "password": "wrongpass"}).status_code, 401)
        self.assertEqual(client.post("/api/login", json={"username": "alice", "password": "password123"}).status_code, 200)
        self.assertEqual(client.post("/api/logout").status_code, 200)
        self.assertEqual(client.post("/api/batches", json={"batch_id": "X", "medicine_name": "M", "expiry_date": "2099-01-01", "quantity": 1}).status_code, 401)

    def test_batch_pagination_sorting_and_invalid_parameters(self) -> None:
        for batch_id, quantity in (("C", 3), ("A", 1), ("B", 2)):
            self.add_batch(batch_id, "Medicine", "2099-10-01", quantity)

        page = self.client.get("/api/batches?page=2&per_page=2&sort_by=batch_id&order=asc")
        descending = self.client.get("/api/batches?sort_by=quantity&order=desc")
        invalid = self.client.get("/api/batches?sort_by=drop_table")

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["total"], 3)
        self.assertEqual(page.json["total_pages"], 2)
        self.assertEqual([item["batch_id"] for item in page.json["batches"]], ["C"])
        self.assertEqual([item["quantity"] for item in descending.json["batches"]], [3, 2, 1])
        self.assertEqual(invalid.status_code, 400)

    def test_search_pagination_metadata(self) -> None:
        self.add_batch("A", "Medicine", "2099-10-01", 1)
        self.add_batch("B", "Medicine", "2099-10-02", 2)
        response = self.client.get("/api/search?name=medicine&page=1&per_page=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["total"], 2)
        self.assertEqual(response.json["total_pages"], 2)
        self.assertEqual(len(response.json["batches"]), 1)

    def test_public_landing_page_and_dashboard_guard(self) -> None:
        client = create_app(InventoryService(":memory:")).test_client()
        landing = client.get("/")
        dashboard = client.get("/dashboard")

        self.assertEqual(landing.status_code, 200)
        self.assertIn(b"Pharmacy Operations", landing.data)
        self.assertEqual(dashboard.status_code, 302)


if __name__ == "__main__":
    unittest.main()