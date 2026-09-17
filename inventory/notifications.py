"""Low-stock reorder notification service."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, List, Optional

from .exceptions import ValidationError
from .service import InventoryService


@dataclass
class Notification:
    notification_id: str
    medicine_name: str
    current_sellable_stock: int
    threshold: int
    notification_type: str
    message: str
    created_date: date
    status: str = "pending"


class NotificationService:
    """Track reorder thresholds and create one notification per low-stock state."""

    def __init__(self) -> None:
        self._thresholds: Dict[str, tuple[str, int]] = {}
        self._low_stock_active: set[str] = set()
        self._outbox: List[Notification] = []
        self._next_id = 1

    def set_threshold(self, medicine_name: str, threshold: int) -> dict:
        normalized_name = self._validate_name(medicine_name)
        self._validate_threshold(threshold)
        key = normalized_name.casefold()
        self._thresholds[key] = (normalized_name, threshold)
        return {"medicine_name": normalized_name, "threshold": threshold}

    def evaluate(
        self,
        medicine_name: str,
        sellable_quantity: int,
        today: Optional[date] = None,
    ) -> Optional[Notification]:
        normalized_name = self._validate_name(medicine_name)
        if not isinstance(sellable_quantity, int) or sellable_quantity < 0:
            raise ValidationError("Sellable stock must be a non-negative integer")
        key = normalized_name.casefold()
        configured = self._thresholds.get(key)
        if configured is None:
            return None

        display_name, threshold = configured
        if sellable_quantity >= threshold:
            self._low_stock_active.discard(key)
            return None
        if key in self._low_stock_active:
            return None

        notification = Notification(
            notification_id=f"REORDER-{self._next_id}",
            medicine_name=display_name,
            current_sellable_stock=sellable_quantity,
            threshold=threshold,
            notification_type="reorder",
            message=(
                f"Reorder {display_name}: sellable stock is {sellable_quantity}, "
                f"below threshold {threshold}"
            ),
            created_date=today or date.today(),
        )
        self._next_id += 1
        self._low_stock_active.add(key)
        self._outbox.append(notification)
        return deepcopy(notification)

    def evaluate_after_dispense(
        self,
        inventory: InventoryService,
        medicine_name: str,
        today=None,
    ) -> Optional[Notification]:
        stock = inventory.sellable_stock(medicine_name, today)
        return self.evaluate(medicine_name, stock, today)

    def list_notifications(self) -> List[Notification]:
        return [deepcopy(notification) for notification in self._outbox]

    @staticmethod
    def _validate_name(medicine_name: str) -> str:
        if not isinstance(medicine_name, str) or not medicine_name.strip():
            raise ValidationError("Medicine name cannot be empty")
        return medicine_name.strip()

    @staticmethod
    def _validate_threshold(threshold: int) -> None:
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 0:
            raise ValidationError("Threshold must be a non-negative integer")


def notification_to_dict(notification: Notification) -> dict:
    data = asdict(notification)
    data["created_date"] = notification.created_date.isoformat()
    return data
