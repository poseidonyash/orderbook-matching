"""Worked example: a finished SortedBook, with a comment on every step.

This file is for reading only. Your own code stays in sorted_book.py. Read this file
from top to bottom, then close it and write submit() in your own file from memory.

The comments follow the first paper example:

    The book holds two sell orders:  id 1 sells 10 lots at 52
                                     id 2 sells  5 lots at 53
    A new buy order arrives:         id 3 buys  12 lots at up to 53

    Result: 10 lots trade at 52, then 2 lots trade at 53.
            3 lots stay in the book at 53.

This version matches BUY orders only. Matching a SELL order is the mirror image,
and it is your exercise.
"""

from collections import deque
from dataclasses import dataclass

from sortedcontainers import SortedDict

from obm.engine.types import OrderId, Price, Qty, Side, TraderId


@dataclass
class Order:
    id: OrderId
    trader: TraderId
    side: Side
    price: Price
    qty: Qty  # Not frozen, because qty goes down when the order partly fills.


@dataclass(frozen=True)
class Fill:
    maker_id: OrderId  # The order that was already waiting in the book.
    taker_id: OrderId  # The new order that arrived and caused the trade.
    price: Price
    qty: Qty


class SortedBook:
    def __init__(self) -> None:
        # Each side maps a price to a deque of the orders waiting at that price.
        # After the two sell orders arrive, self.asks looks like this:
        #     {52: deque([order 1]), 53: deque([order 2])}
        # The keys stay sorted, so the lowest and highest prices are easy to find.
        self.bids = SortedDict()
        self.asks = SortedDict()

    def best_bid(self) -> Price | None:
        # The best bid is the HIGHEST buy price, so take the last key.
        if not self.bids:
            return None
        return self.bids.peekitem(-1)[0]

    def best_ask(self) -> Price | None:
        # The best ask is the LOWEST sell price, so take the first key.
        if not self.asks:
            return None
        return self.asks.peekitem(0)[0]

    def _rest(self, order: Order) -> None:
        # Put an order into the book to wait. Orders 1 and 2 go through here.
        book_side = self.bids if order.side == Side.BUY else self.asks
        book_side.setdefault(order.price, deque()).append(order)

    def submit(self, order: Order) -> list[Fill]:
        fills: list[Fill] = []

        # A SELL order does not match yet in this version. It goes straight into the
        # book. That is how orders 1 and 2 get in.
        if order.side == Side.SELL:
            self._rest(order)
            return fills

        # Order 3 arrives: buy 12 lots, pay at most 53.
        #
        # Keep trading while all three are true:
        #   the buyer still wants lots      (12 > 0, yes)
        #   somebody is selling             (asks are not empty, yes)
        #   the cheapest seller is cheap enough  (52 <= 53, yes)
        while order.qty > 0 and self.best_ask() is not None and self.best_ask() <= order.price:
            # Step 1. Find the cheapest price and the queue of sellers there.
            #   Round 1: price = 52, level = deque([order 1])
            #   Round 2: price = 53, level = deque([order 2])
            price = self.best_ask()
            level = self.asks[price]

            # Step 2. The maker is the OLDEST seller at that price: the front of the deque.
            #   Round 1: maker = order 1 (10 lots)
            #   Round 2: maker = order 2 (5 lots)
            maker = level[0]

            # Step 3. They can only trade the smaller of the two amounts.
            #   Round 1: buyer wants 12, seller has 10 -> trade 10
            #   Round 2: buyer wants  2, seller has  5 -> trade 2
            fill_qty = Qty(min(order.qty, maker.qty))

            # Step 4. Record the trade. It happens at the MAKER's price, not the buyer's.
            #   Round 1: Fill(maker 1, taker 3, price 52, qty 10)
            #   Round 2: Fill(maker 2, taker 3, price 53, qty 2)
            fills.append(Fill(maker.id, order.id, price, fill_qty))

            # Step 5. Both sides now have less left.
            #   Round 1: buyer 12 -> 2,  seller 10 -> 0
            #   Round 2: buyer  2 -> 0,  seller  5 -> 3
            order.qty = Qty(order.qty - fill_qty)
            maker.qty = Qty(maker.qty - fill_qty)

            # Step 6. A seller with nothing left leaves the queue.
            #   Round 1: order 1 has 0 left, so remove it. The deque at 52 is now empty.
            #   Round 2: order 2 still has 3 left, so it stays.
            if maker.qty == 0:
                level.popleft()

            # Step 7. An empty price level leaves the book. Otherwise best_ask() would
            # still say 52 even though nobody sells at 52 any more.
            #   Round 1: delete 52. The asks are now {53: deque([order 2])}.
            #   Round 2: the deque at 53 is not empty, so nothing happens.
            if not level:
                del self.asks[price]

            # Back to the top of the loop.
            #   After round 1: buyer wants 2, best ask is 53, 53 <= 53 -> go again.
            #   After round 2: buyer wants 0 -> stop.

        # Whatever the buyer could not buy waits in the book as a bid.
        # In this example the buyer got all 12, so nothing rests.
        # In the second paper example (limit 52), 2 lots are left, and they rest at 52.
        if order.qty > 0:
            self._rest(order)

        return fills
