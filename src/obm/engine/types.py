"""Core types shared by the engine, the event log, and the agents.

Prices are integer ticks and quantities are integer lots. No floats on the matching path.
"""

from enum import IntEnum
from typing import NewType

OrderId = NewType("OrderId", int)
TraderId = NewType("TraderId", int)
Price = NewType("Price", int)  # ticks
Qty = NewType("Qty", int)  # lots

MIN_TICK = Price(1)
MAX_TICK = Price(10_000)


class Side(IntEnum):
    BUY = 0
    SELL = 1


class OrderType(IntEnum):
    LIMIT = 0  # Trades up to its price. The remainder rests in the book.
    MARKET = 1  # No price limit. The remainder is cancelled.
    IOC = 2  # Immediate-or-cancel: trades up to its price. The remainder is cancelled.
    POST_ONLY = 3  # Must not trade on arrival. Rejected if it would. Otherwise it rests.


class Outcome(IntEnum):
    """What happened to an order after submit()."""

    RESTED = 0  # Some or all of the order now waits in the book.
    FILLED = 1  # The whole order traded.
    CANCELLED = 2  # A MARKET or IOC remainder was dropped.
    REJECTED = 3  # A POST_ONLY order would have traded. Nothing changed.
