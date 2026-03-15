from abc import ABC, abstractmethod
from Core.strategy import Order, OrderSide
from Core.portfolio import Portfolio
import logging

class ExecutionModel(ABC):
    """Abstract base for order execution simulation."""

    @abstractmethod
    def execute_order(self, order: Order, portfolio: Portfolio,
                     bid_price: float, ask_price: float):
        """Execute order and update portfolio."""
        pass

class SimpleExecutionModel(ExecutionModel):
    """Simple execution: fill at bid/ask, no slippage."""

    def execute_order(self, order: Order, portfolio: Portfolio,
                     bid_price: float, ask_price: float):
        """Fill order immediately at market price."""
        if bid_price is None or ask_price is None:
            logging.warning(f"Cannot execute order: prices unavailable")
            return

        if order.side == OrderSide.BUY:
            portfolio.execute_buy(ask_price, order.quantity)
        elif order.side == OrderSide.SELL:
            portfolio.execute_sell(bid_price, order.quantity)
