"""Data models used by the inventory service."""

from dataclasses import dataclass
from datetime import date


@dataclass
class Batch:
    """A quantity of one medicine that shares an expiry date."""

    batch_id: str
    medicine_name: str
    expiry_date: date
    quantity: int