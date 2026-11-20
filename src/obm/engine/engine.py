"""Matching engine: stamps each command, applies it to the book, and emits events.

Single-threaded, with no I/O. The engine never reads the computer's clock: each command gets
its timestamp from the sequencer's clock, which a simulation or a test controls. Running the
same commands through a fresh engine therefore always gives the same events.
"""

from collections.abc import Callable

from obm.engine.book import OrderBook
from obm.engine.events import (
    Accepted,
    Cancelled,
    CancelOrder,
    CancelReason,
    Command,
    Event,
    NewOrder,
    Rejected,
    RejectReason,
    Traded,
)
from obm.engine.orders import Order
from obm.engine.types import OrderId, OrderType, Outcome, Qty


class SimClock:
    """A clock that a simulation controls. By default each read moves it 1 µs forward."""

    def __init__(self, start_ns: int = 0, step_ns: int = 1_000) -> None:
        self.now_ns = start_ns
        self.step_ns = step_ns

    def __call__(self) -> int:
        self.now_ns += self.step_ns
        return self.now_ns


class Sequencer:
    """Gives each command the next sequence number and a timestamp, in arrival order."""

    def __init__(self, clock: Callable[[], int] | None = None) -> None:
        self.clock = clock if clock is not None else SimClock()
        self.last_seq = 0

    def next(self) -> tuple[int, int]:
        self.last_seq += 1
        return self.last_seq, self.clock()


class Engine:
    def __init__(self, book: OrderBook | None = None, sequencer: Sequencer | None = None) -> None:
        self.book = book if book is not None else OrderBook()
        self.sequencer = sequencer if sequencer is not None else Sequencer()
        # The Order objects of all live orders. The book changes their quantity in place,
        # so the engine can read how much is still open when it reports a cancel.
        self._live: dict[OrderId, Order] = {}

    def process(self, command: Command) -> list[Event]:
        seq, ts = self.sequencer.next()
        if isinstance(command, NewOrder):
            return self._new_order(command, seq, ts)
        return self._cancel(command, seq, ts)

    def _new_order(self, cmd: NewOrder, seq: int, ts: int) -> list[Event]:
        # Check the command at the edge, so bad client input becomes a Rejected event
        # instead of an error inside the book.
        reason = self._validate(cmd)
        if reason is not None:
            return [Rejected(seq, ts, cmd.id, reason)]

        order = Order(cmd.id, cmd.trader, cmd.side, cmd.price, cmd.qty, cmd.type)
        result = self.book.submit(order)
        if result.outcome == Outcome.REJECTED:
            return [Rejected(seq, ts, cmd.id, RejectReason.POST_ONLY_WOULD_TRADE)]

        events: list[Event] = [
            Accepted(seq, ts, cmd.id, cmd.trader, cmd.side, cmd.price, cmd.qty, cmd.type)
        ]
        for oid in result.self_trade_cancels:
            own = self._live.pop(oid)
            events.append(Cancelled(seq, ts, oid, own.qty, CancelReason.SELF_TRADE))
        for fill in result.fills:
            events.append(Traded(seq, ts, fill.maker_id, fill.taker_id, fill.price, fill.qty))
            if self._live[fill.maker_id].qty == 0:
                del self._live[fill.maker_id]

        if result.outcome == Outcome.RESTED:
            self._live[cmd.id] = order
        elif result.outcome == Outcome.CANCELLED:
            events.append(Cancelled(seq, ts, cmd.id, order.qty, CancelReason.UNFILLED_REMAINDER))
        return events

    def _cancel(self, cmd: CancelOrder, seq: int, ts: int) -> list[Event]:
        order = self._live.pop(cmd.id, None)
        if order is None:
            return [Rejected(seq, ts, cmd.id, RejectReason.UNKNOWN_ORDER)]
        open_qty = Qty(order.qty)
        self.book.cancel(cmd.id)
        return [Cancelled(seq, ts, cmd.id, open_qty, CancelReason.USER)]

    def _validate(self, cmd: NewOrder) -> RejectReason | None:
        if cmd.qty <= 0:
            return RejectReason.BAD_QUANTITY
        in_range = self.book.min_tick <= cmd.price <= self.book.max_tick
        if cmd.type != OrderType.MARKET and not in_range:
            return RejectReason.PRICE_OUT_OF_RANGE
        if cmd.id in self._live:
            return RejectReason.DUPLICATE_ORDER_ID
        return None
