"""Tests for the Engine: commands in, sequenced events out."""

from hypothesis import given, settings
from hypothesis import strategies as st

from obm.engine.book import OrderBook
from obm.engine.engine import Engine, Sequencer, SimClock
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
from obm.engine.types import OrderId, OrderType, Price, Qty, Side, TraderId


def new(
    id: int,
    side: Side,
    price: int,
    qty: int,
    type: OrderType = OrderType.LIMIT,
    trader: int | None = None,
) -> NewOrder:
    owner = TraderId(id if trader is None else trader)
    return NewOrder(OrderId(id), owner, side, Price(price), Qty(qty), type)


def engine() -> Engine:
    # Commands arrive at 1,000 ns, 2,000 ns, 3,000 ns, and so on.
    return Engine(OrderBook(Price(1), Price(99)), Sequencer(SimClock(step_ns=1_000)))


def test_resting_order_is_accepted() -> None:
    e = engine()

    events = e.process(new(1, Side.BUY, 50, 10))

    assert events == [Accepted(1, 1_000, OrderId(1), TraderId(1), Side.BUY, Price(50),
                               Qty(10), OrderType.LIMIT)]  # fmt: skip


def test_each_command_gets_the_next_seq_and_a_timestamp() -> None:
    e = engine()

    first = e.process(new(1, Side.SELL, 52, 10))
    second = e.process(new(2, Side.BUY, 52, 4))

    assert (first[0].seq, first[0].ts) == (1, 1_000)
    assert [(ev.seq, ev.ts) for ev in second] == [(2, 2_000), (2, 2_000)]
    assert second[1] == Traded(2, 2_000, OrderId(1), OrderId(2), Price(52), Qty(4))


def test_bad_commands_are_rejected_with_a_reason() -> None:
    e = engine()
    e.process(new(1, Side.BUY, 50, 10))

    assert e.process(new(2, Side.BUY, 100, 1)) == [
        Rejected(2, 2_000, OrderId(2), RejectReason.PRICE_OUT_OF_RANGE)
    ]
    assert e.process(new(3, Side.BUY, 50, 0)) == [
        Rejected(3, 3_000, OrderId(3), RejectReason.BAD_QUANTITY)
    ]
    assert e.process(new(1, Side.BUY, 49, 5)) == [
        Rejected(4, 4_000, OrderId(1), RejectReason.DUPLICATE_ORDER_ID)
    ]
    assert e.process(CancelOrder(OrderId(99))) == [
        Rejected(5, 5_000, OrderId(99), RejectReason.UNKNOWN_ORDER)
    ]
    # Rejected commands leave the book unchanged.
    assert e.book.depth(Side.BUY) == [(50, 10)]


def test_post_only_that_would_trade_is_rejected() -> None:
    e = engine()
    e.process(new(1, Side.SELL, 52, 10))

    events = e.process(new(2, Side.BUY, 52, 5, OrderType.POST_ONLY))

    assert events == [Rejected(2, 2_000, OrderId(2), RejectReason.POST_ONLY_WOULD_TRADE)]


def test_user_cancel_reports_the_open_quantity() -> None:
    e = engine()
    e.process(new(1, Side.SELL, 52, 10))
    e.process(new(2, Side.BUY, 52, 4))  # Order 1 has 6 lots open.

    events = e.process(CancelOrder(OrderId(1)))

    assert events == [Cancelled(3, 3_000, OrderId(1), Qty(6), CancelReason.USER)]
    assert e.process(CancelOrder(OrderId(1)))[0] == Rejected(
        4, 4_000, OrderId(1), RejectReason.UNKNOWN_ORDER
    )


def test_ioc_remainder_is_cancelled() -> None:
    e = engine()
    e.process(new(1, Side.SELL, 52, 10))

    events = e.process(new(2, Side.BUY, 52, 12, OrderType.IOC))

    assert events[1:] == [
        Traded(2, 2_000, OrderId(1), OrderId(2), Price(52), Qty(10)),
        Cancelled(2, 2_000, OrderId(2), Qty(2), CancelReason.UNFILLED_REMAINDER),
    ]


def test_market_order_price_is_not_checked() -> None:
    e = engine()
    e.process(new(1, Side.SELL, 52, 10))

    events = e.process(new(2, Side.BUY, 0, 3, OrderType.MARKET))

    assert isinstance(events[0], Accepted)
    assert events[1] == Traded(2, 2_000, OrderId(1), OrderId(2), Price(52), Qty(3))


def test_self_trade_cancel_comes_before_the_trades() -> None:
    # Trader 7 rests 10 at 52, trader 9 rests 5 at 52, then trader 7 buys 8 at 52.
    e = engine()
    e.process(new(1, Side.SELL, 52, 10, trader=7))
    e.process(new(2, Side.SELL, 52, 5, trader=9))

    events = e.process(new(3, Side.BUY, 52, 8, trader=7))

    assert events[1:] == [
        Cancelled(3, 3_000, OrderId(1), Qty(10), CancelReason.SELF_TRADE),
        Traded(3, 3_000, OrderId(2), OrderId(3), Price(52), Qty(5)),
    ]


def test_filled_order_can_no_longer_be_cancelled() -> None:
    e = engine()
    e.process(new(1, Side.SELL, 52, 10))
    e.process(new(2, Side.BUY, 52, 10))

    assert e.process(CancelOrder(OrderId(1)))[0] == Rejected(
        3, 3_000, OrderId(1), RejectReason.UNKNOWN_ORDER
    )


# Properties over random command streams.

commands = st.lists(
    st.one_of(
        st.builds(
            new,
            id=st.integers(1, 30),
            side=st.sampled_from(Side),
            price=st.integers(0, 13),  # 0 and 13 fall outside the 1..12 range.
            qty=st.integers(0, 10),  # 0 is a bad quantity.
            type=st.sampled_from(OrderType),
            trader=st.integers(1, 3),
        ),
        st.builds(CancelOrder, st.integers(1, 30).map(OrderId)),
    ),
    max_size=80,
)


def run(cmds: list[Command]) -> list[Event]:
    e = Engine(OrderBook(Price(1), Price(12)))
    return [ev for cmd in cmds for ev in e.process(cmd)]


@settings(max_examples=300)
@given(commands)
def test_same_commands_always_give_the_same_events(cmds: list[Command]) -> None:
    assert run(cmds) == run(cmds)


@settings(max_examples=300)
@given(commands)
def test_events_account_for_every_lot(cmds: list[Command]) -> None:
    e = Engine(OrderBook(Price(1), Price(12)))
    events = [ev for cmd in cmds for ev in e.process(cmd)]

    # For each accepted order: accepted = traded + cancelled + still resting. An id can be
    # used again once its order is finished, so count per acceptance, in event order.
    open_qty: dict[OrderId, int] = {}
    for ev in events:
        if isinstance(ev, Accepted):
            assert ev.order_id not in open_qty, "accepted an id that is still open"
            open_qty[ev.order_id] = ev.qty
        elif isinstance(ev, Traded):
            open_qty[ev.maker_id] -= ev.qty
            open_qty[ev.taker_id] -= ev.qty
        elif isinstance(ev, Cancelled):
            open_qty[ev.order_id] -= ev.qty
            assert open_qty[ev.order_id] == 0, "a cancel left quantity behind"
        for oid in [k for k, v in open_qty.items() if v == 0]:
            del open_qty[oid]
        assert all(v > 0 for v in open_qty.values()), "an order traded more than it had"

    resting: dict[tuple[Side, int], int] = {}
    for oid, qty in open_qty.items():
        order = e._live[oid]
        resting[(order.side, order.price)] = resting.get((order.side, order.price), 0) + qty
    for side in Side:
        expected = sorted(
            ((p, q) for (s, p), q in resting.items() if s == side), reverse=side == Side.BUY
        )
        assert e.book.depth(side) == expected
