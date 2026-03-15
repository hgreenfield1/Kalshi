from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from Infrastructure.market import Market

@dataclass(frozen=True)
class Context:
    """Immutable snapshot of all state at a timestep."""
    timestamp: str
    market: Market
    bid_price: Optional[float]
    ask_price: Optional[float]
    portfolio_snapshot: Dict[str, Any]
    auxiliary_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate mid-price from bid/ask."""
        if self.bid_price is not None and self.ask_price is not None:
            return (self.bid_price + self.ask_price) / 2
        return None
