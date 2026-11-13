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

from obm.engine.orders import Fill, Order, SubmitResult
from obm.engine.types import MAX_TICK, MIN_TICK, OrderId, OrderType, Outcome, Price, Qty, Side


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

    def depth(self, side: Side) -> list[tuple[Price, Qty]]:
        """Each price on one side with its total resting quantity, best price first."""
        if side == Side.BUY:
            prices = range(self._best_bid, self.min_tick - 1, -1)
            levels = self._bids
        else:
            prices = range(self._best_ask, self.max_tick + 1)
            levels = self._asks
        return [(Price(p), Qty(levels[p].qty)) for p in prices if levels[p].head is not None]

    def check_invariants(self) -> None:
        """Walk every internal structure and raise AssertionError if any is inconsistent.

        For tests only: it visits every tick, so it is far too slow for the matching path.
        """
        seen = 0
        for side, levels in ((Side.BUY, self._bids), (Side.SELL, self._asks)):
            for price in range(self.min_tick, self.max_tick + 1):
                level = levels[price]
                total = 0
                prev = None
                node = level.head
                while node is not None:
                    _require(node.prev is prev, f"broken prev link at {side.name} {price}")
                    _require(node.side == side and node.price == price, f"misplaced {node}")
                    _require(node.qty > 0, f"empty order resting: {node}")
                    _require(self._orders.get(node.id) is node, f"{node} not in the id map")
                    total += node.qty
                    seen += 1
                    prev, node = node, node.next
                _require(level.tail is prev, f"wrong tail at {side.name} {price}")
                _require(level.qty == total, f"level total {level.qty} != {total} at {price}")
        _require(seen == len(self._orders), "id map holds orders that are not in the book")
        _require(self._best_bid == self._next_bid_from(self.max_tick), "stale best bid")
        _require(self._best_ask == self._next_ask_from(self.min_tick), "stale best ask")
        _require(self._best_bid < self._best_ask, "crossed book: best bid >= best ask")

    def submit(self, order: Order) -> SubmitResult:
        """Match an order against the other side, then decide what happens to the rest.

        The order type changes only two things: the limit price used for matching, and
        what happens to the remainder. The matching loops are the same for every type.
        """
        is_market = order.type == OrderType.MARKET
        if not is_market and not self.min_tick <= order.price <= self.max_tick:
            raise ValueError(f"price {order.price} outside {self.min_tick}..{self.max_tick}")
        if order.qty <= 0:
            raise ValueError(f"quantity must be positive, got {order.qty}")
        if order.id in self._orders:
            raise ValueError(f"order id {order.id} is already resting")

        is_buy = order.side == Side.BUY
        fills: list[Fill] = []
        cancels: list[OrderId] = []

        if order.type == OrderType.POST_ONLY:
            crosses = self._best_ask <= order.price if is_buy else self._best_bid >= order.price
            if crosses:
                return SubmitResult(fills, Outcome.REJECTED)
            self._rest(order)
            return SubmitResult(fills, Outcome.RESTED, cancels)

        # A market order has no limit: use the far edge of the range, so it can trade at
        # any price in the book.
        if is_buy:
            limit = self.max_tick if is_market else order.price
            self._take_asks(order, limit, fills, cancels)
        else:
            limit = self.min_tick if is_market else order.price
            self._take_bids(order, limit, fills, cancels)

        if order.qty == 0:
            return SubmitResult(fills, Outcome.FILLED, cancels)
        if order.type == OrderType.LIMIT:
            self._rest(order)
            return SubmitResult(fills, Outcome.RESTED, cancels)
        return SubmitResult(fills, Outcome.CANCELLED, cancels)  # MARKET or IOC: drop the remainder.

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

    def _take_asks(
        self, order: Order, limit: int, fills: list[Fill], cancels: list[OrderId]
    ) -> None:
        # A buy order: take the lowest asks first, while they are at or below the limit.
        while order.qty > 0 and self._best_ask <= limit:
            price = self._best_ask
            level = self._asks[price]
            maker = level.head
            assert maker is not None  # The best ask level always has orders.

            if maker.trader == order.trader:
                # Self-trade prevention: cancel the trader's own resting order, no trade.
                cancels.append(maker.id)
                maker_done = True
            else:
                fill_qty = Qty(min(order.qty, maker.qty))
                fills.append(Fill(maker.id, order.id, Price(price), fill_qty))
                order.qty = Qty(order.qty - fill_qty)
                maker.qty = Qty(maker.qty - fill_qty)
                level.qty -= fill_qty
                maker_done = maker.qty == 0

            if maker_done:
                level.remove(maker)
                del self._orders[maker.id]
                if level.head is None:
                    self._best_ask = self._next_ask_from(price + 1)

    def _take_bids(
        self, order: Order, limit: int, fills: list[Fill], cancels: list[OrderId]
    ) -> None:
        # A sell order: the mirror of _take_asks. Highest bids first, at or above the limit.
        while order.qty > 0 and self._best_bid >= limit:
            price = self._best_bid
            level = self._bids[price]
            maker = level.head
            assert maker is not None  # The best bid level always has orders.

            if maker.trader == order.trader:
                # Self-trade prevention: cancel the trader's own resting order, no trade.
                cancels.append(maker.id)
                maker_done = True
            else:
                fill_qty = Qty(min(order.qty, maker.qty))
                fills.append(Fill(maker.id, order.id, Price(price), fill_qty))
                order.qty = Qty(order.qty - fill_qty)
                maker.qty = Qty(maker.qty - fill_qty)
                level.qty -= fill_qty
                maker_done = maker.qty == 0

            if maker_done:
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


def _require(condition: bool, message: str) -> None:
    # Not `assert`: Python skips assert statements when it runs with -O.
    if not condition:
        raise AssertionError(message)
