"""Fast order book: tick-indexed price levels with intrusive linked lists.

The book has the same behaviour as the baseline in bench/baselines/sorted_book.py, but
every common operation takes the same time whatever the size of the book:

- Level lookup:   levels[price], one list index.
- Add an order:   append at the tail of its level's linked list.
- Cancel:         find the order in a dict, then unlink it from its neighbours.
- Best bid/ask:   read a stored price. It moves only when a level empties or a better
                  price arrives. When the best level empties, the book scans the array
                  to the next price that has orders.
"""

from obm.engine.orders import Fill, Order
from obm.engine.types import MAX_TICK, MIN_TICK, OrderId, Price, Qty, Side


class Level:
    """The queue of resting orders at one price, oldest at the head."""

    __slots__ = ("head", "qty", "tail")

    def __init__(self) -> None:
        self.head: Order | None = None  # Oldest order: fills first.
        self.tail: Order | None = None  # Newest order: new orders join here.
        self.qty = 0  # Total resting quantity at this price.

    def append(self, order: Order) -> None:
        order.prev = self.tail
        order.next = None
        if self.tail is None:
            self.head = order
        else:
            self.tail.next = order
        self.tail = order
        self.qty += order.qty

    def remove(self, order: Order) -> None:
        # Connect the neighbours to each other, then cut the order's own links.
        if order.prev is None:
            self.head = order.next
        else:
            order.prev.next = order.next
        if order.next is None:
            self.tail = order.prev
        else:
            order.next.prev = order.prev
        order.prev = order.next = None
        self.qty -= order.qty


class OrderBook:
    def __init__(self, min_tick: Price = MIN_TICK, max_tick: Price = MAX_TICK) -> None:
        if not 0 < min_tick <= max_tick:
            raise ValueError(f"invalid tick range {min_tick}..{max_tick}")
        self.min_tick = min_tick
        self.max_tick = max_tick
        # One Level per possible price. Index = price, so slots below min_tick stay unused.
        self._bids = [Level() for _ in range(max_tick + 1)]
        self._asks = [Level() for _ in range(max_tick + 1)]
        self._orders: dict[OrderId, Order] = {}
        # Stored best prices. The sentinels mean "no orders": one tick outside the range,
        # so every comparison in the matching loops works without a None check.
        self._best_bid = min_tick - 1
        self._best_ask = max_tick + 1

    def best_bid(self) -> Price | None:
        return Price(self._best_bid) if self._best_bid >= self.min_tick else None

    def best_ask(self) -> Price | None:
        return Price(self._best_ask) if self._best_ask <= self.max_tick else None

    def submit(self, order: Order) -> list[Fill]:
        """Match a limit order against the other side, then rest any remainder."""
        if not self.min_tick <= order.price <= self.max_tick:
            raise ValueError(f"price {order.price} outside {self.min_tick}..{self.max_tick}")
        if order.qty <= 0:
            raise ValueError(f"quantity must be positive, got {order.qty}")
        if order.id in self._orders:
            raise ValueError(f"order id {order.id} is already resting")

        fills: list[Fill] = []
        if order.side == Side.BUY:
            self._take_asks(order, fills)
        else:
            self._take_bids(order, fills)
        if order.qty > 0:
            self._rest(order)
        return fills

    def cancel(self, order_id: OrderId) -> bool:
        """Remove a resting order. Returns False if no resting order has this id."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return False
        if order.side == Side.BUY:
            level = self._bids[order.price]
            level.remove(order)
            if level.head is None and order.price == self._best_bid:
                self._best_bid = self._next_bid_from(order.price - 1)
        else:
            level = self._asks[order.price]
            level.remove(order)
            if level.head is None and order.price == self._best_ask:
                self._best_ask = self._next_ask_from(order.price + 1)
        return True

    def _take_asks(self, order: Order, fills: list[Fill]) -> None:
        # A buy order: take the lowest asks first, while they are at or below its limit.
        while order.qty > 0 and self._best_ask <= order.price:
            price = self._best_ask
            level = self._asks[price]
            maker = level.head
            assert maker is not None  # The best ask level always has orders.

            fill_qty = Qty(min(order.qty, maker.qty))
            fills.append(Fill(maker.id, order.id, Price(price), fill_qty))
            order.qty = Qty(order.qty - fill_qty)
            maker.qty = Qty(maker.qty - fill_qty)
            level.qty -= fill_qty

            if maker.qty == 0:
                level.remove(maker)
                del self._orders[maker.id]
                if level.head is None:
                    self._best_ask = self._next_ask_from(price + 1)

    def _take_bids(self, order: Order, fills: list[Fill]) -> None:
        # A sell order: the mirror of _take_asks. Highest bids first, at or above its limit.
        while order.qty > 0 and self._best_bid >= order.price:
            price = self._best_bid
            level = self._bids[price]
            maker = level.head
            assert maker is not None  # The best bid level always has orders.

            fill_qty = Qty(min(order.qty, maker.qty))
            fills.append(Fill(maker.id, order.id, Price(price), fill_qty))
            order.qty = Qty(order.qty - fill_qty)
            maker.qty = Qty(maker.qty - fill_qty)
            level.qty -= fill_qty

            if maker.qty == 0:
                level.remove(maker)
                del self._orders[maker.id]
                if level.head is None:
                    self._best_bid = self._next_bid_from(price - 1)

    def _rest(self, order: Order) -> None:
        self._orders[order.id] = order
        if order.side == Side.BUY:
            self._bids[order.price].append(order)
            if order.price > self._best_bid:
                self._best_bid = order.price
        else:
            self._asks[order.price].append(order)
            if order.price < self._best_ask:
                self._best_ask = order.price

    def _next_ask_from(self, price: int) -> int:
        # Walk up to the first ask level with orders. Returns the sentinel if none is left.
        while price <= self.max_tick and self._asks[price].head is None:
            price += 1
        return price

    def _next_bid_from(self, price: int) -> int:
        # Walk down to the first bid level with orders. Returns the sentinel if none is left.
        while price >= self.min_tick and self._bids[price].head is None:
            price -= 1
        return price
