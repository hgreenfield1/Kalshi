from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any
from enum import Enum

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Order:
    """Represents a buy/sell order."""
    side: OrderSide
    quantity: int
    limit_price: float

@dataclass
class DataRequirement:
    """Declares data needed by strategy."""
    data_key: str
    loader_class: str
    params: Dict[str, Any]

class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    _version = "1.0.0"
    _prediction_model_version = "1.0.0"

    def __init__(self):
        self.state = {}  # Optional stateful data across timesteps

    @property
    def version(self) -> str:
        return self._version

    @property
    def prediction_model_version(self) -> str:
        return self._prediction_model_version

    @abstractmethod
    def get_data_requirements(self) -> List[DataRequirement]:
        """Declare what auxiliary data this strategy needs."""
        pass

    @abstractmethod
    def on_timestep(self, context) -> List[Order]:
        """Generate orders based on current context."""
        pass

    def on_resolution(self, context, outcome: bool):
        """Called when market resolves. Optional hook."""
        pass

    def save_state(self) -> dict:
        """
        Serialize strategy state for crash recovery.
        Subclasses should call super().save_state() and merge their own fields.
        """
        return {
            'active_signal': getattr(self, '_active_signal', None),
            'entry_price': getattr(self, '_entry_price', None),
        }

    def restore_state(self, state: dict) -> None:
        """
        Restore strategy state after a crash. Called before the first tick.
        Subclasses should call super().restore_state(state) first.
        """
        if hasattr(self, '_active_signal'):
            self._active_signal = state.get('active_signal')
        if hasattr(self, '_entry_price'):
            self._entry_price = state.get('entry_price')
