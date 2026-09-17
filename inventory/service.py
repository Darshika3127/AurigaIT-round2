"""Business rules for pharmacy inventory management."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Dict, List, Union

from .exceptions import (
    DuplicateBatchError,
    InsufficientStockError,
    ValidationError,
)
from .models import Batch

DateInput = Union[date, str]


class InventoryService:
    """Manage batches and dispense medicines using FEFO."""

    def __init__(self) -> None:
        self._batches: Dict[str, Batch] = {}

    def add_batch(
        self,
        batch_id: str,
        medicine_name: str,
        expiry_date: DateInput,
        quantity: int,
    ) -> Batch:
        """Validate and add a batch to the in-memory repository."""
        normalized_id = self._validate_batch_id(batch_id)
        normalized_name = self._validate_medicine_name(medicine_name)
        parsed_expiry = self._parse_date(expiry_date)
        self._validate_quantity(quantity)

        if normalized_id in self._batches:
            raise DuplicateBatchError(f"Batch ID already exists: {normalized_id}")

        batch = Batch(normalized_id, normalized_name, parsed_expiry, quantity)
        self._batches[normalized_id] = batch
        return deepcopy(batch)

    def list_batches(self) -> List[Batch]:
        """Return all batches without exposing repository objects for mutation."""
        return [deepcopy(batch) for batch in self._batches.values()]

    def run_clock(self, today: DateInput = None) -> dict:
        """Quarantine expired batches and report the seven-day expiry window."""
        current_date = self._parse_date(today if today is not None else date.today())
        last_alert_date = current_date + timedelta(days=7)
        batches = list(self._batches.values())
        approaching = [
            batch
            for batch in batches
            if not batch.quarantined
            and current_date <= batch.expiry_date <= last_alert_date
        ]
        already_quarantined = sum(batch.quarantined for batch in batches)
        newly_quarantined = []
        for batch in batches:
            if batch.expiry_date < current_date and not batch.quarantined:
                batch.quarantined = True
                newly_quarantined.append(batch.batch_id)

        return {
            "today": current_date.isoformat(),
            "batches_checked": len(batches),
            "expiring_within_7_days": len(approaching),
            "quarantined": len(newly_quarantined),
            "already_quarantined": already_quarantined,
            "approaching_batches": [deepcopy(batch) for batch in approaching],
            "newly_quarantined_batch_ids": newly_quarantined,
        }

    def dispense(
        self,
        medicine_name: str,
        quantity: int,
        today: DateInput = None,
    ) -> List[Batch]:
        """Dispense medicine from valid batches in expiry-date order.

        The availability check happens before any quantity is changed, so an
        unsuccessful request leaves every batch exactly as it was.
        """
        normalized_name = self._validate_medicine_name(medicine_name)
        self._validate_quantity(quantity)
        current_date = self._parse_date(today if today is not None else date.today())

        valid_batches = self._fefo_batches(normalized_name, current_date)
        available = sum(batch.quantity for batch in valid_batches)
        if available < quantity:
            raise InsufficientStockError(
                f"Only {available} sellable units of {normalized_name} are available"
            )

        remaining = quantity
        dispensed: List[Batch] = []
        for batch in valid_batches:
            amount = min(batch.quantity, remaining)
            if amount == 0:
                break
            batch.quantity -= amount
            dispensed.append(
                Batch(batch.batch_id, batch.medicine_name, batch.expiry_date, amount)
            )
            remaining -= amount

        return dispensed

    def sellable_stock(
        self,
        medicine_name: str,
        today: DateInput = None,
    ) -> int:
        """Return the quantity in batches that have not expired."""
        normalized_name = self._validate_medicine_name(medicine_name)
        current_date = self._parse_date(today if today is not None else date.today())
        return sum(
            batch.quantity
            for batch in self._batches.values()
            if batch.medicine_name.casefold() == normalized_name.casefold()
            and batch.expiry_date >= current_date
            and not batch.quarantined
            and not batch.quarantined
        )

    def search_medicine(
        self,
        medicine_name: str,
        today: DateInput = None,
    ) -> dict:
        """Return availability, sellable quantity, and current valid batches."""
        normalized_name = self._validate_medicine_name(medicine_name)
        current_date = self._parse_date(today if today is not None else date.today())
        batches = self._fefo_batches(normalized_name, current_date)
        return {
            "medicine_name": normalized_name,
            "available": bool(batches),
            "sellable_quantity": sum(batch.quantity for batch in batches),
            "batches": [deepcopy(batch) for batch in batches],
        }

    def expiry_alerts(
        self,
        days: int,
        today: DateInput = None,
    ) -> List[Batch]:
        """Return valid batches expiring within the requested number of days."""
        if not isinstance(days, int) or isinstance(days, bool) or days < 0:
            raise ValidationError("Alert days must be a non-negative integer")

        current_date = self._parse_date(today if today is not None else date.today())
        last_alert_date = current_date + timedelta(days=days)
        matches = [
            batch
            for batch in self._batches.values()
            if current_date <= batch.expiry_date <= last_alert_date
        ]
        return [
            deepcopy(batch)
            for batch in sorted(matches, key=lambda item: (item.expiry_date, item.batch_id))
        ]

    def _fefo_batches(self, medicine_name: str, today: date) -> List[Batch]:
        """Find valid batches for one medicine in FEFO order."""
        matching = [
            batch
            for batch in self._batches.values()
            if batch.medicine_name.casefold() == medicine_name.casefold()
            and batch.expiry_date >= today
            and batch.quantity > 0
        ]
        return sorted(matching, key=lambda item: (item.expiry_date, item.batch_id))

    @staticmethod
    def _validate_batch_id(batch_id: str) -> str:
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValidationError("Batch ID cannot be empty")
        return batch_id.strip()

    @staticmethod
    def _validate_medicine_name(medicine_name: str) -> str:
        if not isinstance(medicine_name, str) or not medicine_name.strip():
            raise ValidationError("Medicine name cannot be empty")
        return medicine_name.strip()

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValidationError("Quantity must be a positive integer")

    @staticmethod
    def _parse_date(value: DateInput) -> date:
        if isinstance(value, datetime):
            raise ValidationError("Expiry date must be a date, not a datetime")
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as error:
                raise ValidationError(
                    "Date must use the YYYY-MM-DD format"
                ) from error
        raise ValidationError("Date must be a date or YYYY-MM-DD string")