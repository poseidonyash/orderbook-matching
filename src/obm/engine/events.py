"""Commands that go into the engine, and events that come out.

Commands are requests from traders. Events are facts: what the engine did. The ordered list
of events is the full record of the market. The book is only a copy that can be rebuilt from
the commands.

Every event carries the sequence number and timestamp of the command that caused it. One
command can cause several events. Within one command, the events come in this order:
Accepted, then self-trade cancels, then trades, then the cancel of an unfilled remainder.
"""

from dataclasses import dataclass
from enum import IntEnum

from obm.engine.types import OrderId, OrderType, Price, Qty, Side, TraderId

# Commands


@dataclass(frozen=True, slots=True)
class NewOrder:
    id: OrderId
    trader: TraderId
    side: Side
    price: Price  # Ignored for a MARKET order.
    qty: Qty
    type: OrderType = OrderType.LIMIT


@dataclass(frozen=True, slots=True)
class CancelOrder:
    id: OrderId


Command = NewOrder | CancelOrder


# Events


class RejectReason(IntEnum):
    PRICE_OUT_OF_RANGE = 1
    BAD_QUANTITY = 2
    DUPLICATE_ORDER_ID = 3  # An order with this id is still live.
    POST_ONLY_WOULD_TRADE = 4
    UNKNOWN_ORDER = 5  # A cancel for an order that is not resting.


class CancelReason(IntEnum):
    USER = 1  # The trader asked for it.
    SELF_TRADE = 2  # Self-trade prevention removed the trader's own resting order.
    UNFILLED_REMAINDER = 3  # What a MARKET or IOC order could not fill at once.


@dataclass(frozen=True, slots=True)
class Accepted:
    seq: int
    ts: int
    order_id: OrderId
    trader: TraderId
    side: Side
    price: Price
    qty: Qty
    type: OrderType


@dataclass(frozen=True, slots=True)
class Rejected:
    seq: int
    ts: int
    order_id: OrderId
    reason: RejectReason


@dataclass(frozen=True, slots=True)
class Traded:
    seq: int
    ts: int
    maker_id: OrderId
    taker_id: OrderId
    price: Price  # Always the maker's price.
    qty: Qty


@dataclass(frozen=True, slots=True)
class Cancelled:
    seq: int
    ts: int
    order_id: OrderId
    qty: Qty  # The quantity that was still open when the order was cancelled.
    reason: CancelReason


Event = Accepted | Rejected | Traded | Cancelled
