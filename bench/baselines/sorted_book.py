"""Baseline order book: simple and correct, not fast.

Each side of the book is a SortedDict from price to a deque of orders, oldest first. The
fast engine in obm.engine is benchmarked against this book and must give the same fills.
"""

from collections import deque

from sortedcontainers import SortedDict

from obm.engine.orders import Fill, Order, SubmitResult
from obm.engine.types import OrderId, OrderType, Outcome, Price, Qty, Side


class SortedBook:
    def __init__(self) -> None:
        self.bids: SortedDict[Price, deque[Order]] = SortedDict()
        self.asks: SortedDict[Price, deque[Order]] = SortedDict()
        self._orders: dict[OrderId, Order] = {}  # Resting orders, for cancel by id.

    def best_bid(self) -> Price | None:
        if not self.bids:
            return None
        price: Price = self.bids.peekitem(-1)[0]
        return price

    def best_ask(self) -> Price | None:
        if not self.asks:
            return None
        price: Price = self.asks.peekitem(0)[0]
        return price

    def submit(self, order: Order) -> SubmitResult:
        """Match an order against the other side, then decide what happens to the rest."""
        fills: list[Fill] = []
        cancels: list[OrderId] = []  # Own resting orders removed by self-trade prevention.

        # A buy trades against the asks, cheapest first. A sell trades against the
        # bids, highest first. Everything else in the loop is the same for both.
        if order.side == Side.BUY:
            opposite, best = self.asks, self.best_ask
        else:
            opposite, best = self.bids, self.best_bid

        if order.type == OrderType.POST_ONLY:
            price = best()
            if price is not None and self._crosses(order, price):
                return SubmitResult(fills, Outcome.REJECTED)
            self._rest(order)
            return SubmitResult(fills, Outcome.RESTED)

        while order.qty > 0:
            price = best()
            if price is None:
                break
            # A market order has no limit, so it accepts any price.
            if order.type != OrderType.MARKET and not self._crosses(order, price):
                break
            level = opposite[price]
            maker = level[0]  # Oldest order at the best price: time priority.

            if maker.trader == order.trader:
                # Self-trade prevention: cancel the trader's own resting order, no trade.
                cancels.append(maker.id)
                maker_done = True
            else:
                fill_qty = Qty(min(order.qty, maker.qty))
                fills.append(Fill(maker.id, order.id, price, fill_qty))
                order.qty = Qty(order.qty - fill_qty)
                maker.qty = Qty(maker.qty - fill_qty)
                maker_done = maker.qty == 0

            if maker_done:
                level.popleft()
                del self._orders[maker.id]
            if not level:
                del opposite[price]

        if order.qty == 0:
            return SubmitResult(fills, Outcome.FILLED, cancels)
        if order.type == OrderType.LIMIT:
            self._rest(order)
            return SubmitResult(fills, Outcome.RESTED, cancels)
        return SubmitResult(fills, Outcome.CANCELLED, cancels)  # MARKET or IOC.

    def cancel(self, order_id: OrderId) -> bool:
        """Remove a resting order. Returns False if no resting order has this id."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return False
        book_side = self.bids if order.side == Side.BUY else self.asks
        level = book_side[order.price]
        level.remove(order)  # O(n) in the orders at this price: the fast engine fixes this.
        if not level:
            del book_side[order.price]
        return True

    @staticmethod
    def _crosses(order: Order, best_opposite: Price) -> bool:
        # A buyer accepts any ask at or below its limit. A seller accepts any bid at or above.
        if order.side == Side.BUY:
            return best_opposite <= order.price
        return best_opposite >= order.price

    def _rest(self, order: Order) -> None:
        book_side = self.bids if order.side == Side.BUY else self.asks
        book_side.setdefault(order.price, deque()).append(order)
        self._orders[order.id] = order
