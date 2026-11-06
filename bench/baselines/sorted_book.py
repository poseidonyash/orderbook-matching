from obm.engine.types import Price, Side, Qty
from sortedcontainers import SortedDict 
from dataclasses import dataclass
from collections import deque

@dataclass
class Order:
    id: int
    trader : int
    side: Side
    price: int
    qty : int

@dataclass(frozen=True)
class Fill:
    maker_id: int
    taker_id: int
    price: int
    qty: int

class SortedBook:
    def __init__(self) -> None:
        self.bids = SortedDict()
        self.asks = SortedDict()
    def best_bid(self) -> Price | None:
        if not self.bids:
            return None
        else:
            return self.bids.peekitem(-1)[0]
    def best_ask(self) -> Price | None:
        if not self.asks:
            return None
        else:
            return self.asks.peekitem(0)[0]
    
    def _rest(self, order: Order) -> None:
        book_side = self.bids if order.side == Side.BUY else self.asks
        book_side.setdefault(order.price, deque()).append(order)

    def submit(self, order: Order) -> list[Fill]:
        fills = []
        if order.side == Side.SELL:
            self._rest(order)
            return fills
        while order.qty and self.best_ask() and self.best_ask() <= order.price:
        # While the order still has qty left AND there are asks
        # AND the best ask price is at or below order.price:
            price = self.best_ask()
            level = self.asks[price]
            maker = level[0]
        #     3. The fill quantity is the smaller of the two quantities.
        #     4. Append a Fill(maker id, taker id, the MAKER's price, fill qty).
        #     5. Subtract the fill quantity from BOTH orders.
        #     6. If the maker has 0 left, remove it from the deque.
        #     7. If the deque is now empty, delete that price from self.asks.
        # After the loop: if the order still has qty left, rest it.
            fill_qty = Qty(min(order.qty, maker.qty))

            fills.append(Fill(maker.id, order.id, price, fill_qty))

            order.qty = Qty(order.qty - fill_qty)
            maker.qty = Qty(maker.qty - fill_qty)

            if maker.qty == 0:
                level.popleft()

            if not level:
                del self.asks[price]

        if order.qty > 0:
            self._rest(order)

        return fills

