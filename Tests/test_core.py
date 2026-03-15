import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Core.portfolio import Portfolio
from Core.strategy import Order, OrderSide
from Core.execution import SimpleExecutionModel

def test_portfolio_buy_long():
    """Test buying contracts from flat position."""
    p = Portfolio(cash=100, positions=0)
    p.execute_buy(50, 1)
    assert p.positions == 1
    assert p.cash == 99.50

def test_portfolio_buy_covers_short():
    """Test buying covers short position first."""
    p = Portfolio(cash=100, positions=-2)
    p.execute_buy(50, 1)
    assert p.positions == -1
    assert p.cash == 100.50  # Gained (100-50)/100

def test_portfolio_sell_from_long():
    """Test selling from long position."""
    p = Portfolio(cash=99.50, positions=1)
    p.execute_sell(60, 1)
    assert p.positions == 0
    assert p.cash == 100.10  # 99.50 + 60/100

def test_portfolio_sell_short():
    """Test selling short from flat position."""
    p = Portfolio(cash=100, positions=0)
    p.execute_sell(40, 1)
    assert p.positions == -1
    assert p.cash == 99.40  # 100 - (100-40)/100

def test_close_all_long():
    """Test closing long position."""
    p = Portfolio(cash=99, positions=2)
    p.close_all_positions(bid_price=55, ask_price=60)
    assert p.positions == 0
    assert p.cash == 100.10  # 99 + 2*55/100

def test_close_all_short():
    """Test closing short position."""
    p = Portfolio(cash=99, positions=-2)
    p.close_all_positions(bid_price=55, ask_price=60)
    assert p.positions == 0
    assert p.cash == 98.20  # 99 - 2*60/100

def test_execution_model():
    """Test simple execution model."""
    p = Portfolio()
    model = SimpleExecutionModel()

    order = Order(OrderSide.BUY, 1, 50)
    model.execute_order(order, p, bid_price=48, ask_price=52)

    assert p.positions == 1
    assert p.cash == 99.48  # Filled at ask=52
