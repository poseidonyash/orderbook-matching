import importlib

import obm
from obm.engine.types import MAX_TICK, MIN_TICK, OrderType, Side

MODULES = [
    "obm.engine.book",
    "obm.engine.engine",
    "obm.engine.order",
    "obm.protocol",
    "obm.log",
    "obm.sim",
    "obm.sim.agents",
    "obm.surveillance",
    "obm.gateway",
    "obm.dashboard",
]


def test_version() -> None:
    assert obm.__version__ == "0.1.0"


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)


def test_core_types() -> None:
    assert MIN_TICK < MAX_TICK
    assert {Side.BUY, Side.SELL} == set(Side)
    assert len(OrderType) == 4
