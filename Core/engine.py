import logging
from typing import List, Dict, Any
from dataclasses import dataclass
from Core.context import Context
from Core.strategy import BaseStrategy, OrderSide
from Core.portfolio import Portfolio
from Core.execution import ExecutionModel
from Core.market_filter import MarketFilter
from Core.database import BacktestDatabase
from Infrastructure.market import Market
import Utils.date_helpers as date_helpers

@dataclass
class BacktestResult:
    """Results from a single backtest run."""
    market_id: str
    final_cash: float
    final_positions: int
    trade_count: int
    predictions: List[Dict[str, Any]]

class BacktestEngine:
    """Main orchestration engine for backtesting."""

    def __init__(self, strategy: BaseStrategy, market_filter: MarketFilter,
                 execution_model: ExecutionModel, http_client,
                 db_path: str = "backtest_predictions.db"):
        self.strategy = strategy
        self.market_filter = market_filter
        self.execution_model = execution_model
        self.http_client = http_client
        self.db = BacktestDatabase(db_path)

    def run_single_market(self, market: Market, market_type: str) -> BacktestResult:
        """Run backtest on a single market."""
        logging.info(f"Starting backtest for market: {market.ticker}")

        # Initialize portfolio
        portfolio = Portfolio()

        # Initialize data loaders based on strategy requirements
        data_loaders = self._initialize_data_loaders(market)

        # Get timestamps for this market
        timestamps = self._get_timestamps(market, data_loaders)

        # Pre-load all data
        logging.info(f"Pre-loading data for {len(timestamps)} timestamps")
        for name, loader in data_loaders.items():
            loader.load(timestamps)

        # Get market prices (candlestick data)
        prices = self._get_market_prices(market, timestamps)

        # Main timestep loop
        prediction_log = []
        for timestamp in timestamps:
            # Build auxiliary data
            aux_data = {}
            for name, loader in data_loaders.items():
                aux_data[name] = loader.at_timestep(timestamp)

            # Round timestamp for price lookup
            ts_rounded = date_helpers.round_to_next_minute(timestamp)
            bid_price = prices.get(ts_rounded, {}).get('bid')
            ask_price = prices.get(ts_rounded, {}).get('ask')

            # Build context
            context = Context(
                timestamp=timestamp,
                market=market,
                bid_price=bid_price,
                ask_price=ask_price,
                portfolio_snapshot=portfolio.snapshot(),
                auxiliary_data=aux_data,
                metadata={'strategy_version': self.strategy.version}
            )

            # Get orders from strategy
            orders = self.strategy.on_timestep(context)

            # Execute orders
            if orders and bid_price is not None and ask_price is not None:
                for order in orders:
                    self.execution_model.execute_order(order, portfolio, bid_price, ask_price)

            # Log prediction
            prediction_log.append({
                'market_id': market.ticker,
                'timestamp': timestamp,
                'mid_price': context.mid_price,
                'bid_price': bid_price,
                'ask_price': ask_price,
                'cash': portfolio.cash,
                'positions': portfolio.positions,
                'signal': len(orders) if orders else 0
            })

        # Get market outcome
        outcome = self._get_market_outcome(market, data_loaders)

        # Call resolution hook
        final_context = context  # Last context
        self.strategy.on_resolution(final_context, outcome)

        # Close all positions at market resolution
        if timestamps:
            ts_final = date_helpers.round_to_next_minute(timestamps[-1])
            fallback_price = 100 if outcome else 0
            final_bid = prices.get(ts_final, {}).get('bid') or fallback_price
            final_ask = prices.get(ts_final, {}).get('ask') or fallback_price
            portfolio.close_all_positions(final_bid, final_ask)

        # Save to database
        self.db.save_predictions(
            market_type=market_type,
            predictions=prediction_log,
            actual_outcome=outcome,
            prediction_model_version=self.strategy.prediction_model_version,
            strategy_version=self.strategy.version
        )

        logging.info(f"Backtest complete: Final cash={portfolio.cash}, Positions={portfolio.positions}")

        return BacktestResult(
            market_id=market.ticker,
            final_cash=portfolio.cash,
            final_positions=portfolio.positions,
            trade_count=len(portfolio.trade_history),
            predictions=prediction_log
        )

    def run_multiple_markets(self, markets: List[Market], market_type: str) -> List[BacktestResult]:
        """Run backtests on multiple markets."""
        results = []
        for market in markets:
            try:
                result = self.run_single_market(market, market_type)
                results.append(result)
            except Exception as e:
                logging.error(f"Error backtesting {market.ticker}: {e}")
        return results

    def _initialize_data_loaders(self, market: Market) -> Dict[str, Any]:
        """Initialize data loaders from strategy requirements."""
        loaders = {}
        requirements = self.strategy.get_data_requirements()

        for req in requirements:
            # Dynamically import loader class
            module_path, class_name = req.loader_class.rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            loader_class = getattr(module, class_name)

            # Instantiate loader
            loaders[req.data_key] = loader_class(market, self.http_client, **req.params)

        return loaders

    def _get_timestamps(self, market: Market, data_loaders: Dict) -> List[str]:
        """Get timestamps for backtest (delegated to data loader)."""
        # For now, assume first data loader provides timestamps
        # This is market-specific logic
        if data_loaders:
            first_loader = list(data_loaders.values())[0]
            if hasattr(first_loader, 'get_timestamps'):
                return first_loader.get_timestamps()
        return []

    def _get_market_prices(self, market: Market, timestamps: List[str]) -> Dict[str, Dict[str, float]]:
        """Get market prices from Kalshi candlestick API."""
        if not timestamps:
            return {}

        # Get 60-second candlesticks
        candlesticks = self.http_client.get_market_candelstick(
            market.ticker,
            market.series_ticker,
            date_helpers.game_timestamp_to_unix(timestamps[0]),
            date_helpers.game_timestamp_to_unix(timestamps[-1]),
            1
        )

        # Map timestamps to bid/ask
        prices = {}
        candle_map = {
            date_helpers.unix_to_utc_timestamp(c['end_period_ts']): c
            for c in candlesticks['candlesticks']
        }

        def _parse_price(val):
            """Convert close_dollars string to cents float, or None."""
            if val is None:
                return None
            try:
                return float(val) * 100
            except (TypeError, ValueError):
                return None

        for timestamp in timestamps:
            ts_rounded = date_helpers.round_to_next_minute(timestamp)
            if ts_rounded in candle_map:
                candle = candle_map[ts_rounded]
                prices[ts_rounded] = {
                    'bid': _parse_price(candle.get('yes_bid', {}).get('close_dollars')),
                    'ask': _parse_price(candle.get('yes_ask', {}).get('close_dollars'))
                }
            else:
                prices[ts_rounded] = {'bid': None, 'ask': None}

        return prices

    def _get_market_outcome(self, market: Market, data_loaders: Dict) -> bool:
        """Get market outcome (delegated to data loader)."""
        # Market-specific logic - delegate to first loader
        if data_loaders:
            first_loader = list(data_loaders.values())[0]
            if hasattr(first_loader, 'get_outcome'):
                return first_loader.get_outcome()
        return False
