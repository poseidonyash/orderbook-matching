"""Matching rules that every order book must follow.

Each test runs twice: once on the SortedDict baseline and once on the fast OrderBook.
"""

from collections.abc import Callable
from typing import Protocol

import pytest
from bench.baselines.sorted_book import SortedBook

from obm.engine.book import OrderBook
from obm.engine.orders import Fill, Order, SubmitResult
from obm.engine.types import OrderId, OrderType, Outcome, Price, Qty, Side, TraderId


class Book(Protocol):
    def submit(self, order: Order) -> SubmitResult: ...
    def cancel(self, order_id: OrderId) -> bool: ...
    def best_bid(self) -> Price | None: ...
    def best_ask(self) -> Price | None: ...


MakeBook = Callable[[], Book]


@pytest.fixture(params=[SortedBook, OrderBook], ids=["baseline", "fast"])
def make_book(request: pytest.FixtureRequest) -> MakeBook:
    factory: MakeBook = request.param
    return factory


def order(
    id: int,
    side: Side,
    price: int,
    qty: int,
    type: OrderType = OrderType.LIMIT,
    trader: int | None = None,
) -> Order:
    # By default each order belongs to its own trader, so no test self-trades by accident.
    owner = TraderId(id if trader is None else trader)
    return Order(OrderId(id), owner, side, Price(price), Qty(qty), type)


def trades(fills: list[Fill]) -> list[tuple[int, int, int, int]]:
    return [(f.maker_id, f.taker_id, f.price, f.qty) for f in fills]


def book_with_asks(book: Book) -> Book:
    # Asks: 10 lots at 52 (id 1), 5 lots at 53 (id 2).
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10))
    book.submit(order(id=2, side=Side.SELL, price=53, qty=5))
    return book


def book_with_bids(book: Book) -> Book:
    # Bids: 10 lots at 50 (id 1), 5 lots at 49 (id 2).
    book.submit(order(id=1, side=Side.BUY, price=50, qty=10))
    book.submit(order(id=2, side=Side.BUY, price=49, qty=5))
    return book


def test_empty_book_has_no_best_prices(make_book: MakeBook) -> None:
    book = make_book()

    assert book.best_bid() is None
    assert book.best_ask() is None


def test_orders_that_do_not_cross_rest(make_book: MakeBook) -> None:
    book = make_book()

    assert book.submit(order(id=1, side=Side.BUY, price=50, qty=1)).outcome == Outcome.RESTED
    assert book.submit(order(id=2, side=Side.SELL, price=52, qty=1)).outcome == Outcome.RESTED
    assert (book.best_bid(), book.best_ask()) == (50, 52)


def test_buy_sweeps_two_levels(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    fills = book.submit(order(id=3, side=Side.BUY, price=53, qty=12)).fills

    assert trades(fills) == [(1, 3, 52, 10), (2, 3, 53, 2)]
    assert book.best_ask() == 53
    assert book.best_bid() is None


def test_unfilled_buy_remainder_rests_as_a_bid(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=12)).fills

    assert trades(fills) == [(1, 3, 52, 10)]
    assert book.best_bid() == 52
    assert book.best_ask() == 53


def test_sell_sweeps_two_levels(make_book: MakeBook) -> None:
    # The mirror of the buy sweep: the seller takes the HIGHEST bid first.
    book = book_with_bids(make_book())

    fills = book.submit(order(id=3, side=Side.SELL, price=49, qty=12)).fills

    assert trades(fills) == [(1, 3, 50, 10), (2, 3, 49, 2)]
    assert book.best_bid() == 49
    assert book.best_ask() is None


def test_unfilled_sell_remainder_rests_as_an_ask(make_book: MakeBook) -> None:
    book = book_with_bids(make_book())

    fills = book.submit(order(id=3, side=Side.SELL, price=50, qty=12)).fills

    assert trades(fills) == [(1, 3, 50, 10)]
    assert book.best_ask() == 50
    assert book.best_bid() == 49


def test_oldest_order_at_a_price_fills_first(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=3))
    book.submit(order(id=2, side=Side.SELL, price=52, qty=3))

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=4)).fills

    assert trades(fills) == [(1, 3, 52, 3), (2, 3, 52, 1)]


def test_trade_happens_at_the_makers_price(make_book: MakeBook) -> None:
    # The buyer would pay up to 60, but the resting seller asked 52.
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=1))

    fills = book.submit(order(id=2, side=Side.BUY, price=60, qty=1)).fills

    assert trades(fills) == [(1, 2, 52, 1)]


def test_cancel_removes_order_and_empty_level(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    assert book.cancel(OrderId(1)) is True
    assert book.best_ask() == 53

    # The cancelled order no longer trades.
    fills = book.submit(order(id=3, side=Side.BUY, price=53, qty=1)).fills
    assert trades(fills) == [(2, 3, 53, 1)]


def test_cancel_keeps_other_orders_at_the_same_price(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=3))
    book.submit(order(id=2, side=Side.SELL, price=52, qty=3))

    assert book.cancel(OrderId(1)) is True

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=3)).fills
    assert trades(fills) == [(2, 3, 52, 3)]


def test_cancel_of_a_partly_filled_order_removes_the_rest(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())
    book.submit(order(id=3, side=Side.BUY, price=52, qty=4))  # Order 1 has 6 lots left.

    assert book.cancel(OrderId(1)) is True
    assert book.best_ask() == 53


def test_cancel_of_unknown_or_filled_order_returns_false(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())
    book.submit(order(id=3, side=Side.BUY, price=52, qty=10))  # Order 1 fills completely.

    assert book.cancel(OrderId(1)) is False
    assert book.cancel(OrderId(99)) is False


# Order types. The book in each test is the paper example: asks of 10 at 52 and 5 at 53,
# or its mirror for sells: bids of 10 at 50 and 5 at 49.


def test_limit_order_that_fills_completely_reports_filled(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=52, qty=10))

    assert result.outcome == Outcome.FILLED
    assert book.best_bid() is None


def test_limit_order_with_a_remainder_reports_rested(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=52, qty=12))

    assert result.outcome == Outcome.RESTED
    assert trades(result.fills) == [(1, 3, 52, 10)]


def test_market_buy_takes_every_level_and_cancels_the_rest(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    # The price 1 is ignored: a market order has no limit.
    result = book.submit(order(id=3, side=Side.BUY, price=1, qty=20, type=OrderType.MARKET))

    assert trades(result.fills) == [(1, 3, 52, 10), (2, 3, 53, 5)]
    assert result.outcome == Outcome.CANCELLED
    assert (book.best_bid(), book.best_ask()) == (None, None)  # The 5 left did not rest.


def test_market_sell_takes_the_highest_bids_first(make_book: MakeBook) -> None:
    book = book_with_bids(make_book())

    result = book.submit(order(id=3, side=Side.SELL, price=99, qty=12, type=OrderType.MARKET))

    assert trades(result.fills) == [(1, 3, 50, 10), (2, 3, 49, 2)]
    assert result.outcome == Outcome.FILLED


def test_market_order_on_an_empty_side_is_cancelled(make_book: MakeBook) -> None:
    book = make_book()

    result = book.submit(order(id=1, side=Side.BUY, price=50, qty=5, type=OrderType.MARKET))

    assert result == SubmitResult([], Outcome.CANCELLED)
    assert book.best_bid() is None


def test_ioc_takes_what_it_can_and_cancels_the_rest(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=52, qty=12, type=OrderType.IOC))

    assert trades(result.fills) == [(1, 3, 52, 10)]
    assert result.outcome == Outcome.CANCELLED
    assert book.best_bid() is None  # A limit order would have left a bid of 2 at 52.


def test_ioc_that_fills_completely_reports_filled(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=53, qty=12, type=OrderType.IOC))

    assert result.outcome == Outcome.FILLED
    assert book.best_ask() == 53


def test_ioc_that_cannot_trade_is_cancelled_without_fills(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=51, qty=5, type=OrderType.IOC))

    assert result == SubmitResult([], Outcome.CANCELLED)


def test_post_only_that_would_trade_is_rejected(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=52, qty=5, type=OrderType.POST_ONLY))

    assert result == SubmitResult([], Outcome.REJECTED)
    assert (book.best_bid(), book.best_ask()) == (None, 52)  # The book did not change.


def test_post_only_sell_that_would_trade_is_rejected(make_book: MakeBook) -> None:
    book = book_with_bids(make_book())

    result = book.submit(order(id=3, side=Side.SELL, price=50, qty=5, type=OrderType.POST_ONLY))

    assert result.outcome == Outcome.REJECTED
    assert book.best_ask() is None


def test_post_only_that_does_not_cross_rests(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    result = book.submit(order(id=3, side=Side.BUY, price=51, qty=5, type=OrderType.POST_ONLY))

    assert result == SubmitResult([], Outcome.RESTED)
    assert book.best_bid() == 51


# Self-trade prevention: a trader's new order never trades with that trader's own resting
# order. The engine cancels the resting order instead, and matching goes on.


def test_self_trade_cancels_own_resting_order_then_trades_with_others(
    make_book: MakeBook,
) -> None:
    # Trader 7 sells 10 at 52 (order 1). Trader 9 sells 5 at 52 behind it (order 2).
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10, trader=7))
    book.submit(order(id=2, side=Side.SELL, price=52, qty=5, trader=9))

    # Trader 7 buys 8 at 52.
    result = book.submit(order(id=3, side=Side.BUY, price=52, qty=8, trader=7))

    assert result.self_trade_cancels == [1]
    assert trades(result.fills) == [(2, 3, 52, 5)]
    assert result.outcome == Outcome.RESTED  # 3 lots left, resting as a bid at 52.
    assert (book.best_bid(), book.best_ask()) == (52, None)


def test_self_trade_with_only_own_orders_trades_nothing(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10, trader=7))

    result = book.submit(order(id=2, side=Side.BUY, price=52, qty=4, trader=7))

    assert result == SubmitResult([], Outcome.RESTED, [OrderId(1)])
    assert (book.best_bid(), book.best_ask()) == (52, None)


def test_self_trade_cancels_own_orders_on_several_levels(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.BUY, price=50, qty=3, trader=7))
    book.submit(order(id=2, side=Side.BUY, price=49, qty=3, trader=8))
    book.submit(order(id=3, side=Side.BUY, price=48, qty=3, trader=7))

    result = book.submit(order(id=4, side=Side.SELL, price=48, qty=10, trader=7))

    assert result.self_trade_cancels == [1, 3]
    assert trades(result.fills) == [(2, 4, 49, 3)]
    assert (book.best_bid(), book.best_ask()) == (None, 48)  # 7 lots left rest at 48.


def test_self_trade_cancelled_order_can_no_longer_be_cancelled(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10, trader=7))
    book.submit(order(id=2, side=Side.BUY, price=52, qty=4, trader=7))

    assert book.cancel(OrderId(1)) is False


def test_market_order_self_trade_cancels_and_drops_the_rest(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10, trader=7))

    market = order(id=2, side=Side.BUY, price=1, qty=4, type=OrderType.MARKET, trader=7)
    result = book.submit(market)

    assert result == SubmitResult([], Outcome.CANCELLED, [OrderId(1)])
    assert (book.best_bid(), book.best_ask()) == (None, None)


def test_post_only_against_own_order_is_rejected_and_keeps_it(make_book: MakeBook) -> None:
    # Post-only never trades, so the usual post-only rule applies: reject, change nothing.
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10, trader=7))

    post = order(id=2, side=Side.BUY, price=52, qty=4, type=OrderType.POST_ONLY, trader=7)
    result = book.submit(post)

    assert result == SubmitResult([], Outcome.REJECTED)
    assert book.best_ask() == 52
