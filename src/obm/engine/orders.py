"""Order and Fill: the data that every engine in this project reads and writes.

Both the baseline book in bench/baselines and the fast engine use these classes, so their
outputs can be compared directly in the reference tests.
"""

from dataclasses import dataclass

from obm.engine.types import OrderId, Price, Qty, Side, TraderId


# eq=False: two orders are the same only if they are the same object. Field-by-field
# equality is wrong for an order, because two different orders can have equal fields.
@dataclass(slots=True, eq=False)
class Order:
    id: OrderId
    trader: TraderId
    side: Side
    price: Price
    qty: Qty  # Remaining quantity. It goes down as the order fills.


# frozen=True: a fill is a record of a trade that already happened, so it never changes.
@dataclass(slots=True, frozen=True)
class Fill:
    maker_id: OrderId  # The resting order that was already in the book.
    taker_id: OrderId  # The incoming order that caused the trade.
    price: Price  # Always the maker's price.
    qty: Qty
