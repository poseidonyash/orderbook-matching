"""Order and Fill: the data that every engine in this project reads and writes.

Both the baseline book in bench/baselines and the fast engine use these classes, so their
outputs can be compared directly in the reference tests.
"""

from dataclasses import dataclass, field

from obm.engine.types import OrderId, OrderType, Outcome, Price, Qty, Side, TraderId


# eq=False: two orders are the same only if they are the same object. Field-by-field
# equality is wrong for an order, because two different orders can have equal fields.
@dataclass(slots=True, eq=False)
class Order:
    id: OrderId
    trader: TraderId
    side: Side
    price: Price
    qty: Qty  # Remaining quantity. It goes down as the order fills.
    type: OrderType = OrderType.LIMIT  # A MARKET order's price is ignored.

    # Links to the neighbours in the queue at this price (an intrusive doubly linked
    # list). Only the fast book in obm.engine.book uses them. The baseline ignores them.
    prev: "Order | None" = field(default=None, repr=False)
    next: "Order | None" = field(default=None, repr=False)


# frozen=True: a fill is a record of a trade that already happened, so it never changes.
@dataclass(slots=True, frozen=True)
class Fill:
    maker_id: OrderId  # The resting order that was already in the book.
    taker_id: OrderId  # The incoming order that caused the trade.
    price: Price  # Always the maker's price.
    qty: Qty


@dataclass(slots=True, frozen=True)
class SubmitResult:
    """What submit() did with one order: the trades it made, and what happened after."""

    fills: list[Fill]
    outcome: Outcome
