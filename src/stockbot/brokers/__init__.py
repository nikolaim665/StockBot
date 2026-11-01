from __future__ import annotations

from typing import Protocol

from ..models import AccountSnapshot


class Broker(Protocol):
    name: str

    def snapshot(self) -> AccountSnapshot: ...


class BrokerError(Exception):
    pass
