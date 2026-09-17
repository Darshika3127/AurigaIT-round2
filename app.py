"""Flask HTTP interface for the pharmacy inventory service."""

from dataclasses import asdict
import math
import os
from functools import wraps
from typing import Any, Optional

from werkzeug.exceptions import HTTPException
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

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


def _pagination_params() -> tuple[int, int, str, str]:
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
    except ValueError as error:
        raise ValueError("page and per_page must be integers") from error
    sort_by = request.args.get("sort_by", "batch_id")
    order = request.args.get("order", "asc").lower()
    if page < 1 or per_page < 1 or per_page > 100:
        raise ValueError("page must be positive and per_page must be between 1 and 100")
    return page, per_page, sort_by, order


def _page_response(items: list, page: int, per_page: int, total: int, key: str) -> dict:
    return {
        key: items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": math.ceil(total / per_page) if total else 0,
    }


def create_app(
    service: Optional[InventoryService] = None,
    database_path: str = "inventory.db",
) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("PHARMACY_SECRET_KEY", "dev-only-change-me")
    inventory = service or InventoryService(database_path)
    importer = BatchImportService(inventory)
    notifications = NotificationService(inventory.database)

    @app.get("/")
    def index():
        return render_template("landing.html")

    @app.get("/dashboard")
    def dashboard():
        if "user_id" not in session:
            return redirect(url_for("index"))
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/register")
    def register():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or len(password) < 8:
            return jsonify(error="Username is required and password must be at least 8 characters"), 400
        try:
            inventory.database.create_user(username.strip().casefold(), generate_password_hash(password))
        except ValueError as error:
            return jsonify(error=str(error)), 409
        return jsonify(message="Registration successful"), 201

    @app.post("/api/login")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400
        username = payload.get("username")
        password = payload.get("password")
        user = inventory.database.get_user(username.strip().casefold()) if isinstance(username, str) else None
        if user is None or not isinstance(password, str) or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Invalid username or password"), 401
        session.clear()
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        return jsonify(message="Login successful", username=user["username"])

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(message="Logout successful")

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return jsonify(error="Authentication required"), 401
            return view(*args, **kwargs)
        return wrapped

    @app.post("/clock")
    @authenticated
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
    @authenticated
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
    @authenticated
    def import_batches():
        payload = request.get_json(silent=True)
        try:
            report = importer.import_records(payload)
        except ValidationError as error:
            return jsonify(error=str(error)), 400
        return jsonify(report), 200

    @app.get("/api/batches")
    def list_batches():
        try:
            page, per_page, sort_by, order = _pagination_params()
            batches, total = inventory.list_batches_page(page, per_page, sort_by, order)
        except (ValueError, ValidationError) as error:
            return jsonify(error=str(error)), 400
        return jsonify(_page_response([_batch_to_dict(batch) for batch in batches], page, per_page, total, "batches"))

    @app.post("/api/dispense")
    @authenticated
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
    @authenticated
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
            page, per_page, sort_by, order = _pagination_params()
            result, total = inventory.search_medicine_page(medicine_name, page, per_page, sort_by, order)
        except (ValueError, ValidationError) as error:
            return jsonify(error=str(error)), 400

        result["batches"] = [_batch_to_dict(batch) for batch in result["batches"]]
        result.update({"page": page, "per_page": per_page, "total": total, "total_pages": math.ceil(total / per_page) if total else 0})
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