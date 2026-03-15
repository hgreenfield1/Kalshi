from dataclasses import dataclass, field
from typing import List, Dict, Any
import logging

@dataclass
class Portfolio:
    """Tracks positions, cash, and trade history."""
    cash: float = 100.0
    positions: int = 0
    trade_history: List[Dict[str, Any]] = field(default_factory=list)

    def execute_buy(self, ask_price: float, quantity: int):
        """
        Buy contracts (exact logic from TradingStrategy.buy).
        - If net short, buying covers short (generates cash)
        - If flat/long, buying increases long (uses cash)
        """
        if self.positions < 0:
            # Cover short position first
            cover_qty = min(quantity, abs(self.positions))
            self.positions += cover_qty
            self.cash += round(cover_qty * (100 - ask_price) / 100, 2)
            quantity -= cover_qty
            logging.info(f"Covered {cover_qty} short contracts. Position: {self.positions}")

        if quantity > 0:
            # Add to long position
            self.positions += quantity
            self.cash -= round(quantity * ask_price / 100, 2)
            logging.info(f"Bought {quantity} contracts. Position: {self.positions}")

        self.trade_history.append({
            'action': 'buy',
            'price': ask_price,
            'quantity': quantity,
            'positions': self.positions,
            'cash': self.cash
        })

    def execute_sell(self, bid_price: float, quantity: int):
        """
        Sell contracts (exact logic from TradingStrategy.sell).
        - If net long, selling reduces long (generates cash)
        - If flat/short, selling increases short (uses cash)
        """
        if self.positions > 0:
            # Sell from long position first
            sell_qty = min(quantity, self.positions)
            self.positions -= sell_qty
            self.cash += round(sell_qty * bid_price / 100, 2)
            quantity -= sell_qty
            logging.info(f"Sold {sell_qty} long contracts. Position: {self.positions}")

        if quantity > 0:
            # Open/increase short position
            self.positions -= quantity
            self.cash -= round(quantity * (100 - bid_price) / 100, 2)
            logging.info(f"Sold short {quantity} contracts. Position: {self.positions}")

        self.trade_history.append({
            'action': 'sell',
            'price': bid_price,
            'quantity': quantity,
            'positions': self.positions,
            'cash': self.cash
        })

    def close_all_positions(self, bid_price: float, ask_price: float):
        """Close all open positions."""
        if self.positions > 0:
            self.execute_sell(bid_price, self.positions)
        elif self.positions < 0:
            self.execute_buy(ask_price, abs(self.positions))
        logging.info(f"Closed all positions: Cash={self.cash}, Positions={self.positions}")

    def snapshot(self) -> Dict[str, Any]:
        """Return immutable snapshot for Context."""
        return {
            'cash': self.cash,
            'positions': self.positions,
            'trade_count': len(self.trade_history)
        }
