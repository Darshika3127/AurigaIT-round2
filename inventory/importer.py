"""Messy batch import support."""

import re
from datetime import date, datetime
from typing import Any, Dict, List

from .exceptions import DuplicateBatchError, ValidationError
from .service import InventoryService


_QUANTITY_PATTERN = re.compile(r"^(\d+)\s*(?:units?|u)?$", re.IGNORECASE)


class BatchImportService:
    """Normalize external rows and import valid batches independently of Flask."""

    def __init__(self, inventory: InventoryService) -> None:
        self.inventory = inventory

    def import_records(self, records: Any) -> dict:
        if not isinstance(records, list):
            raise ValidationError("Import payload must be a JSON array")

        report = {"imported": 0, "deduped": 0, "rejected": 0, "errors": []}
        known_ids = {batch.batch_id for batch in self.inventory.list_batches()}
        seen_ids = set()

        for row_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                self._reject(report, row_number, "Row must be an object")
                continue

            raw_id = record.get("batch_id")
            normalized_id = raw_id.strip() if isinstance(raw_id, str) else None
            if normalized_id and (normalized_id in known_ids or normalized_id in seen_ids):
                report["deduped"] += 1
                continue

            try:
                batch_id = self._required_text(raw_id, "Batch ID")
                medicine_name = self._required_text(
                    record.get("medicine_name"), "Medicine name"
                )
                expiry_date = self._parse_expiry(record.get("expiry_date"))
                quantity = self._parse_quantity(record.get("quantity"))
                self.inventory.add_batch(batch_id, medicine_name, expiry_date, quantity)
            except DuplicateBatchError:
                report["deduped"] += 1
                continue
            except ValidationError as error:
                self._reject(report, row_number, str(error))
                continue

            known_ids.add(batch_id)
            seen_ids.add(batch_id)
            report["imported"] += 1

        return report

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"Missing {field_name.lower()}")
        return value.strip()

    @staticmethod
    def _parse_quantity(value: Any) -> int:
        if isinstance(value, bool):
            raise ValidationError("Invalid quantity")
        if isinstance(value, int):
            quantity = value
        elif isinstance(value, str):
            match = _QUANTITY_PATTERN.fullmatch(value.strip())
            if not match:
                raise ValidationError("Invalid quantity")
            quantity = int(match.group(1))
        else:
            raise ValidationError("Invalid quantity")
        if quantity <= 0:
            raise ValidationError("Invalid quantity")
        return quantity

    @staticmethod
    def _parse_expiry(value: Any) -> date:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Missing expiry date")
        value = value.strip()
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value, "%d/%m/%Y").date()
            except ValueError as error:
                raise ValidationError("Invalid expiry date") from error

    @staticmethod
    def _reject(report: Dict[str, Any], row_number: int, reason: str) -> None:
        report["rejected"] += 1
        report["errors"].append({"row": row_number, "reason": reason})
