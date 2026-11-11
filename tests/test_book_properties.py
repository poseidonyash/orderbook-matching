"""Property-based tests: rules that must hold after every possible sequence of orders.

Hypothesis builds sequences of submits and cancels and runs each one on the fast book and
the baseline side by side. After every step it checks that:

- both books return the same results and show the same book (differential check),
- the fast book's internal structures are consistent (check_invariants),
- the book is never crossed: best bid < best ask,
- no quantity appears or disappears: each order's sent quantity equals what filled,
  plus what rests, plus what was cancelled,
- every fill is at the maker's price, inside the taker's limit, and between two
  different traders.

When a rule breaks, Hypothesis shrinks the sequence to the shortest one that still fails.
"""

from dataclasses import dataclass

from bench.baselines.sorted_book import SortedBook
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from obm.engine.book import OrderBook
from obm.engine.orders import Order
from obm.engine.types import OrderId, OrderType, Outcome, Price, Qty, Side, TraderId

MIN, MAX = 1, 12  # A small range, so orders cross and levels empty often.


@dataclass
class Tracked:
    """What the test knows about one submitted order, independent of either book."""

    trader: TraderId
    side: Side
    price: Price
    type: OrderType
    sent: int
    filled: int = 0
    cancelled: int = 0
    resting: bool = False

    @property
    def left(self) -> int:
        return self.sent - self.filled - self.cancelled


class BookMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.fast = OrderBook(Price(MIN), Price(MAX))
        self.base = SortedBook()
        self.orders: dict[OrderId, Tracked] = {}

    @rule(
        side=st.sampled_from(Side),
        price=st.integers(MIN, MAX),
        qty=st.integers(1, 10),
        kind=st.sampled_from(OrderType),
        trader=st.integers(1, 3),  # Few traders, so self-trades happen often.
    )
    def submit(self, side: Side, price: int, qty: int, kind: OrderType, trader: int) -> None:
        oid = OrderId(len(self.orders) + 1)
        t = Tracked(TraderId(trader), side, Price(price), kind, sent=qty)
        self.orders[oid] = t

        # Each book gets its own Order object, because books change the quantity.
        def new() -> Order:
            return Order(oid, t.trader, side, t.price, Qty(qty), kind)

        result = self.fast.submit(new())
        assert result == self.base.submit(new()), "the books disagree"

        for cancelled_id in result.self_trade_cancels:
            maker = self.orders[cancelled_id]
            assert maker.resting and maker.trader == t.trader, "bad self-trade cancel"
            maker.cancelled += maker.left
            maker.resting = False

        for fill in result.fills:
            maker = self.orders[fill.maker_id]
            assert fill.taker_id == oid and fill.qty > 0
            assert maker.resting and maker.side != side, "fill against a non-resting order"
            assert maker.trader != t.trader, "self-trade printed"
            assert fill.price == maker.price, "fill not at the maker's price"
            if kind != OrderType.MARKET:
                inside = fill.price <= price if side == Side.BUY else fill.price >= price
                assert inside, "fill outside the taker's limit"
            maker.filled += fill.qty
            t.filled += fill.qty
            if maker.left == 0:
                maker.resting = False

        if result.outcome == Outcome.FILLED:
            assert t.left == 0
        elif result.outcome == Outcome.RESTED:
            assert t.left > 0 and kind in (OrderType.LIMIT, OrderType.POST_ONLY)
            t.resting = True
        elif result.outcome == Outcome.CANCELLED:
            assert t.left > 0 and kind in (OrderType.MARKET, OrderType.IOC)
            t.cancelled += t.left
        else:
            assert kind == OrderType.POST_ONLY and not result.fills
            t.cancelled += t.left

    @precondition(lambda self: self.orders)
    @rule(data=st.data())
    def cancel(self, data: st.DataObject) -> None:
        oid = data.draw(st.sampled_from(sorted(self.orders)))
        t = self.orders[oid]
        done = self.fast.cancel(oid)
        assert done == self.base.cancel(oid), "the books disagree on cancel"
        assert done == t.resting, "cancel result does not match whether the order rests"
        if done:
            t.cancelled += t.left
            t.resting = False

    @invariant()
    def fast_book_is_consistent(self) -> None:
        self.fast.check_invariants()

    @invariant()
    def books_agree_and_match_the_model(self) -> None:
        for side in Side:
            expected: dict[int, int] = {}
            for t in self.orders.values():
                assert t.left >= 0, "an order filled or cancelled more than it sent"
                if t.resting and t.side == side:
                    expected[t.price] = expected.get(t.price, 0) + t.left
                elif not t.resting:
                    assert t.left == 0, "quantity disappeared"
            best_first = sorted(expected.items(), reverse=side == Side.BUY)
            assert self.fast.depth(side) == best_first, f"{side.name} depth is wrong"
            assert self.base.depth(side) == best_first, f"baseline {side.name} depth is wrong"

    @invariant()
    def book_is_never_crossed(self) -> None:
        bid, ask = self.fast.best_bid(), self.fast.best_ask()
        assert (bid, ask) == (self.base.best_bid(), self.base.best_ask())
        if bid is not None and ask is not None:
            assert bid < ask, "crossed book"


BookMachine.TestCase.settings = settings(max_examples=200, stateful_step_count=60, deadline=None)
TestBookProperties = BookMachine.TestCase
