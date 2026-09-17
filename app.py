"""Flask HTTP interface for the pharmacy inventory service."""

from dataclasses import asdict
from typing import Any, Optional

from werkzeug.exceptions import HTTPException
from flask import Flask, jsonify, render_template, request

from inventory.exceptions import (
    DuplicateBatchError,
    InsufficientStockError,
    ValidationError,
)
from inventory.importer import BatchImportService
from inventory.notifications import NotificationService, notification_to_dict
from inventory.service import InventoryService


def _batch_to_dict(batch: Any) -> dict:
    data = asdict(batch)
    data["expiry_date"] = batch.expiry_date.isoformat()
    return data


def create_app(service: Optional[InventoryService] = None) -> Flask:
    app = Flask(__name__)
    inventory = service or InventoryService()
    importer = BatchImportService(inventory)
    notifications = NotificationService()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.post("/clock")
    def clock():
        payload = request.get_json(silent=True)
        if payload is not None and not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400

        try:
            report = inventory.run_clock((payload or {}).get("today"))
        except ValidationError as error:
            return jsonify(error=str(error)), 400

        report["approaching_batches"] = [
            _batch_to_dict(batch) for batch in report["approaching_batches"]
        ]
        return jsonify(report)

    @app.post("/api/batches")
    def add_batch():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400

        try:
            batch = inventory.add_batch(
                payload.get("batch_id"),
                payload.get("medicine_name"),
                payload.get("expiry_date"),
                payload.get("quantity"),
            )
        except DuplicateBatchError as error:
            return jsonify(error=str(error)), 409
        except ValidationError as error:
            return jsonify(error=str(error)), 400

        return jsonify(batch=_batch_to_dict(batch)), 201

    @app.post("/api/import")
    def import_batches():
        payload = request.get_json(silent=True)
        try:
            report = importer.import_records(payload)
        except ValidationError as error:
            return jsonify(error=str(error)), 400
        return jsonify(report), 200

    @app.get("/api/batches")
    def list_batches():
        return jsonify(batches=[_batch_to_dict(batch) for batch in inventory.list_batches()])

    @app.post("/api/dispense")
    def dispense():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400

        try:
            dispensed = inventory.dispense(
                payload.get("medicine_name"), payload.get("quantity")
            )
        except InsufficientStockError as error:
            return jsonify(error=str(error)), 409
        except ValidationError as error:
            return jsonify(error=str(error)), 400

        notifications.evaluate_after_dispense(inventory, payload.get("medicine_name"))
        return jsonify(dispensed=[_batch_to_dict(batch) for batch in dispensed])

    @app.post("/api/reorder-thresholds")
    def set_reorder_threshold():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400

        try:
            threshold = notifications.set_threshold(
                payload.get("medicine_name"), payload.get("threshold")
            )
            current_stock = inventory.sellable_stock(threshold["medicine_name"])
        except ValidationError as error:
            return jsonify(error=str(error)), 400

        return jsonify(**threshold, sellable_quantity=current_stock), 200

    @app.get("/outbox")
    def outbox():
        return jsonify(
            notifications=[
                notification_to_dict(notification)
                for notification in notifications.list_notifications()
            ]
        )

    @app.get("/api/stock/<medicine_name>")
    def stock(medicine_name: str):
        try:
            quantity = inventory.sellable_stock(medicine_name)
        except ValidationError as error:
            return jsonify(error=str(error)), 400
        return jsonify(medicine_name=medicine_name, sellable_quantity=quantity)

    @app.get("/api/search")
    def search():
        medicine_name = request.args.get("name")
        try:
            result = inventory.search_medicine(medicine_name)
        except ValidationError as error:
            return jsonify(error=str(error)), 400

        result["batches"] = [_batch_to_dict(batch) for batch in result["batches"]]
        return jsonify(result)

    @app.get("/api/alerts")
    def alerts():
        days_value = request.args.get("days", "7")
        try:
            days = int(days_value)
        except (TypeError, ValueError):
            return jsonify(error="days must be a non-negative integer"), 400

        try:
            matches = inventory.expiry_alerts(days)
        except ValidationError as error:
            return jsonify(error=str(error)), 400
        return jsonify(days=days, batches=[_batch_to_dict(batch) for batch in matches])

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify(error=error.description), error.code
            return error
        app.logger.exception("Unhandled application error", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="An unexpected server error occurred"), 500
        return "An unexpected server error occurred", 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)