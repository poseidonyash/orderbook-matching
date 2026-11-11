"""Matching rules that every order book must follow.

Each test runs twice: once on the SortedDict baseline and once on the fast OrderBook.
"""

from collections.abc import Callable
from typing import Protocol

import pytest
from bench.baselines.sorted_book import SortedBook

from obm.engine.book import OrderBook
from obm.engine.orders import Fill, Order
from obm.engine.types import OrderId, Price, Qty, Side, TraderId


class Book(Protocol):
    def submit(self, order: Order) -> list[Fill]: ...
    def cancel(self, order_id: OrderId) -> bool: ...
    def best_bid(self) -> Price | None: ...
    def best_ask(self) -> Price | None: ...


MakeBook = Callable[[], Book]


@pytest.fixture(params=[SortedBook, OrderBook], ids=["baseline", "fast"])
def make_book(request: pytest.FixtureRequest) -> MakeBook:
    factory: MakeBook = request.param
    return factory


def order(id: int, side: Side, price: int, qty: int, trader: int = 0) -> Order:
    return Order(OrderId(id), TraderId(trader), side, Price(price), Qty(qty))


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

    assert book.submit(order(id=1, side=Side.BUY, price=50, qty=1)) == []
    assert book.submit(order(id=2, side=Side.SELL, price=52, qty=1)) == []
    assert (book.best_bid(), book.best_ask()) == (50, 52)


def test_buy_sweeps_two_levels(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    fills = book.submit(order(id=3, side=Side.BUY, price=53, qty=12))

    assert trades(fills) == [(1, 3, 52, 10), (2, 3, 53, 2)]
    assert book.best_ask() == 53
    assert book.best_bid() is None


def test_unfilled_buy_remainder_rests_as_a_bid(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=12))

    assert trades(fills) == [(1, 3, 52, 10)]
    assert book.best_bid() == 52
    assert book.best_ask() == 53


def test_sell_sweeps_two_levels(make_book: MakeBook) -> None:
    # The mirror of the buy sweep: the seller takes the HIGHEST bid first.
    book = book_with_bids(make_book())

    fills = book.submit(order(id=3, side=Side.SELL, price=49, qty=12))

    assert trades(fills) == [(1, 3, 50, 10), (2, 3, 49, 2)]
    assert book.best_bid() == 49
    assert book.best_ask() is None


def test_unfilled_sell_remainder_rests_as_an_ask(make_book: MakeBook) -> None:
    book = book_with_bids(make_book())

    fills = book.submit(order(id=3, side=Side.SELL, price=50, qty=12))

    assert trades(fills) == [(1, 3, 50, 10)]
    assert book.best_ask() == 50
    assert book.best_bid() == 49


def test_oldest_order_at_a_price_fills_first(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=3))
    book.submit(order(id=2, side=Side.SELL, price=52, qty=3))

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=4))

    assert trades(fills) == [(1, 3, 52, 3), (2, 3, 52, 1)]


def test_trade_happens_at_the_makers_price(make_book: MakeBook) -> None:
    # The buyer would pay up to 60, but the resting seller asked 52.
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=1))

    fills = book.submit(order(id=2, side=Side.BUY, price=60, qty=1))

    assert trades(fills) == [(1, 2, 52, 1)]


def test_cancel_removes_order_and_empty_level(make_book: MakeBook) -> None:
    book = book_with_asks(make_book())

    assert book.cancel(OrderId(1)) is True
    assert book.best_ask() == 53

    # The cancelled order no longer trades.
    fills = book.submit(order(id=3, side=Side.BUY, price=53, qty=1))
    assert trades(fills) == [(2, 3, 53, 1)]


def test_cancel_keeps_other_orders_at_the_same_price(make_book: MakeBook) -> None:
    book = make_book()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=3))
    book.submit(order(id=2, side=Side.SELL, price=52, qty=3))

    assert book.cancel(OrderId(1)) is True

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=3))
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
