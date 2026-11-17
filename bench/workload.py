"""Seeded, realistic order flow for the benchmark.

The same seed always gives the same messages, so two runs, or two engines, see exactly the
same stream. The stream has two parts:

- Warm-up: resting limit orders spread around a middle price, so the timed part starts
  with a full book. The benchmark does not time these.
- Stream: the timed messages. About 60% new limit orders that rest near the middle
  price, 35% cancels of orders that are resting, and 5% IOC orders that trade at once.

To know which orders are resting, the generator runs its own copy of the fast book while
it builds the stream. That costs time, but only before the benchmark starts.
"""

import random
from dataclasses import dataclass

from obm.engine.book import OrderBook
from obm.engine.orders import Order
from obm.engine.types import MAX_TICK, MIN_TICK, OrderId, OrderType, Price, Qty, Side, TraderId

MID = 5_000  # Middle price, in ticks.
SPREAD = 50  # Resting orders sit 1 to SPREAD ticks away from MID.
TRADERS = 100


@dataclass(frozen=True, slots=True)
class NewOrder:
    id: OrderId
    trader: TraderId
    side: Side
    price: Price
    qty: Qty
    type: OrderType

    def to_order(self) -> Order:
        # Each engine needs its own Order objects, because books change the quantity.
        return Order(self.id, self.trader, self.side, self.price, self.qty, self.type)


@dataclass(frozen=True, slots=True)
class Cancel:
    id: OrderId


Message = NewOrder | Cancel


@dataclass(frozen=True, slots=True)
class Workload:
    seed: int
    warmup: list[NewOrder]
    stream: list[Message]


def generate(seed: int, messages: int, warmup_orders: int = 10_000) -> Workload:
    rng = random.Random(seed)
    book = OrderBook(MIN_TICK, MAX_TICK)
    resting = _RestingSet()
    next_id = 1

    def new_order(order_type: OrderType, aggressive: bool) -> NewOrder:
        nonlocal next_id
        side = Side.BUY if rng.random() < 0.5 else Side.SELL
        if aggressive:
            # Priced across the whole spread, so it trades at once with the best orders.
            price = MID + SPREAD if side == Side.BUY else MID - SPREAD
        else:
            offset = rng.randint(1, SPREAD)
            price = MID - offset if side == Side.BUY else MID + offset
        msg = NewOrder(
            OrderId(next_id),
            TraderId(rng.randint(1, TRADERS)),
            side,
            Price(price),
            Qty(rng.randint(1, 10)),
            order_type,
        )
        next_id += 1
        result = book.submit(msg.to_order())
        for fill in result.fills:
            resting.discard_if_gone(book, fill.maker_id)
        for oid in result.self_trade_cancels:
            resting.discard(oid)
        if book.is_resting(msg.id):
            resting.add(msg.id)
        return msg

    warmup = [new_order(OrderType.LIMIT, aggressive=False) for _ in range(warmup_orders)]

    stream: list[Message] = []
    for _ in range(messages):
        roll = rng.random()
        if roll < 0.35 and resting:
            oid = resting.pop_random(rng)
            book.cancel(oid)
            stream.append(Cancel(oid))
        elif roll < 0.40:
            stream.append(new_order(OrderType.IOC, aggressive=True))
        else:
            stream.append(new_order(OrderType.LIMIT, aggressive=False))
    return Workload(seed, warmup, stream)


class _RestingSet:
    """A set of order ids that also picks a random member in O(1)."""

    def __init__(self) -> None:
        self._ids: list[OrderId] = []
        self._index: dict[OrderId, int] = {}

    def __bool__(self) -> bool:
        return bool(self._ids)

    def add(self, oid: OrderId) -> None:
        self._index[oid] = len(self._ids)
        self._ids.append(oid)

    def discard(self, oid: OrderId) -> None:
        # Swap the last id into the removed slot, so removal needs no shifting.
        i = self._index.pop(oid, None)
        if i is None:
            return
        last = self._ids.pop()
        if last != oid:
            self._ids[i] = last
            self._index[last] = i

    def discard_if_gone(self, book: OrderBook, oid: OrderId) -> None:
        if not book.is_resting(oid):
            self.discard(oid)

    def pop_random(self, rng: random.Random) -> OrderId:
        oid = self._ids[rng.randrange(len(self._ids))]
        self.discard(oid)
        return oid
