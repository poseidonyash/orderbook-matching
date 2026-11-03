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
    LIMIT = 0
    MARKET = 1
    IOC = 2
    POST_ONLY = 3
