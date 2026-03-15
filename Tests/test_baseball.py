import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Markets.Baseball.strategies import SimpleBacktestStrategy

def test_simple_strategy_data_requirements():
    """Test strategy declares data requirements."""
    strategy = SimpleBacktestStrategy()
    reqs = strategy.get_data_requirements()

    assert len(reqs) == 1
    assert reqs[0].data_key == "game"
    assert "BaseballDataLoader" in reqs[0].loader_class

def test_simple_strategy_versions():
    """Test strategy version metadata."""
    strategy = SimpleBacktestStrategy()
    assert strategy.version == "v1.1.0"
    assert strategy.prediction_model_version == "v1.1.0"
