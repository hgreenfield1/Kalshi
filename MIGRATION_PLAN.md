# Migration Plan: Baseball Backtest to Generalized Framework

## Executive Summary

Migrate `Baseball/Backtest/backtest.py` from the legacy baseball-specific backtesting system to the new generalized Core/Markets architecture. This will eliminate code duplication, improve maintainability, and enable multi-market backtesting.

---

## Current Architecture Issues

### Code Duplication
- **Strategies duplicated**: Same 5 strategies exist in both locations
  - Old: `Baseball/Strategies/backtest_strategies.py`
  - New: `Markets/Baseball/strategies.py`
- **Different interfaces**: Old uses `trade()`, new uses `on_timestep()`
- **Runner duplication**: BacktestRunner vs BacktestEngine
- **Analysis duplication**: analyze_database.py vs Core/performance.py + Scripts/analyze.py

### Technical Debt
- Old system lacks lookahead protection
- No unified database schema
- Tightly coupled to baseball domain
- Cannot backtest multiple markets in one run
- Manual portfolio management prone to bugs

---

## Migration Strategy

### Phase 1: Verify New Framework Completeness ✓

**Status**: COMPLETE (based on exploration)

The new framework has all necessary components:
- ✓ BacktestEngine in Core/engine.py
- ✓ All 5 strategies ported to Markets/Baseball/strategies.py
- ✓ BaseballDataLoader implements BaseDataLoader interface
- ✓ Unified database schema in Core/database.py
- ✓ CLI execution script in Scripts/run_backtest.py
- ✓ Analysis tools in Scripts/analyze.py

---

### Phase 2: Update Baseball/Backtest/backtest.py

**Objective**: Replace old BacktestRunner with new BacktestEngine

#### Step 2.1: Update Imports

**File**: `Baseball/Backtest/backtest.py`

**Changes**:
```python
# OLD IMPORTS TO REMOVE
from Baseball.Backtest.BacktestRunner import BacktestRunner
from Baseball.Strategies.backtest_strategies import (
    SimpleBacktestStrategy,
    ConservativeBacktestStrategy,
    AggressiveValueStrategy,
    ReverseSteamStrategy,
    ChangeInValueStrategy
)
from Baseball.analyze_database import BacktestAnalyzer

# NEW IMPORTS TO ADD
from Core.engine import BacktestEngine
from Core.market_filter import SeriesMarketFilter, StatusMarketFilter, CompositeMarketFilter
from Core.execution import SimpleExecutionModel
from Markets.Baseball.strategies import (
    SimpleBacktestStrategy,
    ConservativeBacktestStrategy,
    AggressiveValueStrategy,
    ReverseSteamStrategy,
    ChangeInValueStrategy
)
```

#### Step 2.2: Remove Custom Game Data Pre-loading

**Rationale**: New framework handles data loading via BaseballDataLoader

**Code to Remove**:
```python
from Baseball.Backtest.game_data_pre_loaders import preload_game_data

# In main loop:
game_data_cache = preload_game_data(game.game_id, timestamps)
```

**Replacement**: Engine automatically invokes loader.load() for all timestamps

#### Step 2.3: Simplify Market Filtering

**OLD**:
```python
all_markets = http_client.get_markets(['KXMLBGAME'], status="settled")
all_markets = dict(reversed(list(all_markets.items())))

for market in list(all_markets.values())[0:1]:
    # Skip if market ticker doesn't match home team
    if market.ticker.split('-')[-1] != game.home_team_abv:
        continue
```

**NEW**:
```python
# Create composable market filter
series_filter = SeriesMarketFilter(series_tickers=['KXMLBGAME'])
status_filter = StatusMarketFilter(status='settled')
market_filter = CompositeMarketFilter([series_filter, status_filter])

# Get filtered markets
markets = market_filter.filter_markets(http_client)

# Select market range
markets = list(markets.values())[0:1]  # Or interactive selection
```

#### Step 2.4: Replace Backtest Execution Loop

**OLD PATTERN**:
```python
for market in markets:
    game = market_to_game(market)

    # Timestamp logic
    game_timestamps = statsapi.get('game_timestamps', {'gamePk': game.game_id})
    timestamps = date_helpers.get_backtest_timestamps(start_time, end_time)

    # Game status check
    schedule = statsapi.schedule(game_id=game.game_id)
    if status != "Final":
        continue

    # Pre-load game data
    game_data_cache = preload_game_data(game.game_id, timestamps)

    # Run each strategy
    for strategy_name, strategy_class in selected_strategies:
        strategy = strategy_class()
        backtest = BacktestRunner(game, market, http_client, strategy)
        backtest.run(timestamps, game_data_cache)
        print(f"Done with {strategy_name}")
```

**NEW PATTERN**:
```python
# Initialize engine components
execution_model = SimpleExecutionModel()

for strategy_name, strategy_class in selected_strategies:
    strategy = strategy_class()

    # Create engine with strategy
    engine = BacktestEngine(
        strategy=strategy,
        market_filter=market_filter,
        execution_model=execution_model,
        http_client=http_client
    )

    # Run backtest across all markets
    results = engine.run_multiple_markets(
        markets=markets,
        market_type="baseball"
    )

    # Print summary
    print(f"\n{strategy_name} Results:")
    print(f"  Markets: {results['total_markets']}")
    print(f"  Successful: {results['successful']}")
    print(f"  Failed: {results['failed']}")
    print(f"  Average Final Cash: ${results['avg_cash']:.2f}")
    print(f"  ROI: {results['roi']:.2f}%")
```

**Benefits**:
- Engine handles timestamp extraction automatically
- Data loading delegated to BaseballDataLoader
- Built-in error handling and logging
- Automatic database persistence
- Multi-market batch processing

#### Step 2.5: Update Analysis Section

**OLD**:
```python
from Baseball.analyze_database import BacktestAnalyzer

analyzer = BacktestAnalyzer()
analyzer.database_summary()
analyzer.compare_strategies()
analyzer.analyze_model_versions()
analyzer.plot_calibration_curve()
```

**NEW OPTION 1 - Use Scripts/analyze.py**:
```python
# At end of backtest.py, suggest running:
print("\nBacktest complete! Run analysis with:")
print("  python Scripts/analyze.py")
```

**NEW OPTION 2 - Inline Analysis**:
```python
from Core.database import BacktestDatabase
from Core.performance import calculate_brier_score

db = BacktestDatabase()
predictions = db.get_predictions(market_type="baseball")

# Calculate metrics
brier_score = calculate_brier_score(predictions)
print(f"\nBrier Score: {brier_score:.4f}")

# Strategy comparison
for strategy_version in predictions['strategy_version'].unique():
    strategy_preds = predictions[predictions['strategy_version'] == strategy_version]
    roi = ((strategy_preds['cash'].iloc[-1] - 100.0) / 100.0) * 100
    print(f"{strategy_version}: ROI = {roi:.2f}%")
```

#### Step 2.6: Remove Unnecessary Game Logic

**Rationale**: BaseballDataLoader already handles game status checking

**Code to Remove**:
```python
# Verify game is completed before backtesting
schedule = statsapi.schedule(game_id=game.game_id)
status = schedule[0]['status']
if status != "Final":
    logging.info(f"Skipping backtest for {game.home_team_abv} vs {game.away_team_abv} because the game is not final.")
    continue
```

**Handled by**: BaseballDataLoader.load() method filters non-final games

---

### Phase 3: Deprecate Old Components

#### Step 3.1: Mark Old Files as Deprecated

**Files to deprecate**:
- `Baseball/Backtest/BacktestRunner.py`
- `Baseball/Strategies/backtest_strategies.py`
- `Baseball/analyze_database.py`
- `Baseball/Backtest/game_data_pre_loaders.py`

**Action**: Add deprecation notice at top of each file:
```python
"""
DEPRECATED: This module is deprecated and will be removed in a future version.

Use the generalized backtesting framework instead:
- Engine: Core.engine.BacktestEngine
- Strategies: Markets.Baseball.strategies
- Analysis: Scripts.analyze

For migration guide, see MIGRATION_PLAN.md
"""
import warnings
warnings.warn(
    "This module is deprecated. Use Core.engine.BacktestEngine instead.",
    DeprecationWarning,
    stacklevel=2
)
```

#### Step 3.2: Update CLAUDE.md

**Add section**:
```markdown
## Backtesting Framework

This project uses a generalized backtesting framework in Core/ that works with any market type.

### Running Backtests

**Option 1 - Interactive CLI**:
```bash
python Scripts/run_backtest.py
```

**Option 2 - Updated baseball script**:
```bash
python Baseball/Backtest/backtest.py
```

### Architecture

- **Engine**: `Core/engine.py` - Market-agnostic backtesting orchestration
- **Strategies**: `Markets/{MarketType}/strategies.py` - Market-specific trading logic
- **Data Loaders**: `Markets/{MarketType}/data_loader.py` - Market-specific data fetching
- **Database**: `Core/database.py` - Unified multi-market predictions storage
- **Analysis**: `Scripts/analyze.py` - Performance metrics and visualization

### Adding New Strategies

Inherit from `Core.strategy.BaseStrategy`:

1. Implement `get_data_requirements()` - declare what data you need
2. Implement `on_timestep(context) -> List[Order]` - generate trading signals
3. Optionally implement `on_resolution(context, outcome)` - cleanup hook

See `Markets/Baseball/strategies.py` for examples.

### Deprecated Components

The following are deprecated and will be removed:
- `Baseball/Backtest/BacktestRunner.py` → Use `Core.engine.BacktestEngine`
- `Baseball/Strategies/backtest_strategies.py` → Use `Markets.Baseball.strategies`
- `Baseball/analyze_database.py` → Use `Scripts/analyze.py`
```

---

### Phase 4: Testing & Validation

#### Step 4.1: Functional Equivalence Testing

**Objective**: Verify new framework produces same results as old framework

**Test Plan**:
1. Run old backtest.py on single market, save predictions
2. Run new backtest.py on same market, save predictions
3. Compare:
   - Final cash values
   - Position counts
   - Trade timing
   - Prediction values

**Acceptance Criteria**: Results match within 0.01% tolerance

#### Step 4.2: Performance Testing

**Metrics to measure**:
- Execution time for 10 markets
- Memory usage during data loading
- Database write performance

**Expected improvements**:
- Faster due to unified data loading
- Lower memory (no duplicate strategy instances)
- Better database indexing

#### Step 4.3: Integration Testing

**Test scenarios**:
1. Run all 5 strategies on 100 markets
2. Verify database schema correctness
3. Run analysis scripts on results
4. Test error handling (bad game IDs, API failures)

---

### Phase 5: Cleanup & Removal

#### Step 5.1: Archive Old Code

**Create archive directory**:
```
Baseball/Archive/
  ├── BacktestRunner.py
  ├── backtest_strategies.py
  ├── analyze_database.py
  └── game_data_pre_loaders.py
```

#### Step 5.2: Update All Imports

**Search for**:
```bash
git grep "from Baseball.Backtest.BacktestRunner import"
git grep "from Baseball.Strategies.backtest_strategies import"
git grep "from Baseball.analyze_database import"
```

**Update** all references to use new imports

#### Step 5.3: Remove Deprecated Files

**After confirming no usage**:
```bash
git rm Baseball/Backtest/BacktestRunner.py
git rm Baseball/Strategies/backtest_strategies.py
git rm Baseball/analyze_database.py
git rm Baseball/Backtest/game_data_pre_loaders.py
```

---

## Implementation Checklist

### Preparation
- [ ] Read and understand new framework architecture (Core/ and Markets/)
- [ ] Review all 5 strategy implementations in Markets/Baseball/strategies.py
- [ ] Understand BacktestEngine flow in Core/engine.py
- [ ] Review BaseballDataLoader implementation

### Code Changes
- [ ] Update imports in Baseball/Backtest/backtest.py
- [ ] Replace BacktestRunner with BacktestEngine
- [ ] Implement market filtering using CompositeMarketFilter
- [ ] Remove game data pre-loading code
- [ ] Update strategy loop to use engine.run_multiple_markets()
- [ ] Update analysis section to use new database/performance modules

### Testing
- [ ] Run single market backtest with old system, record results
- [ ] Run same market with new system, verify results match
- [ ] Run multi-strategy backtest on 10 markets
- [ ] Verify database contains correct predictions
- [ ] Run Scripts/analyze.py to confirm metrics calculate correctly
- [ ] Test error handling (invalid markets, API failures)

### Documentation
- [ ] Update CLAUDE.md with new architecture documentation
- [ ] Add deprecation warnings to old files
- [ ] Document migration process for future reference
- [ ] Update any README files

### Cleanup
- [ ] Move deprecated files to Baseball/Archive/
- [ ] Search codebase for any remaining old imports
- [ ] Remove archived files after confirmation period
- [ ] Clean up any unused dependencies

---

## Benefits After Migration

### Developer Experience
- **Single source of truth** - No confusion about which system to use
- **Cleaner code** - Reduced duplication, better separation of concerns
- **Easier testing** - Abstract interfaces enable mocking
- **Better debugging** - Immutable context prevents state bugs

### Functionality
- **Multi-market backtesting** - Test strategies across hundreds of games in one run
- **Market type flexibility** - Same framework works for other markets (crypto, elections)
- **Data integrity** - Built-in lookahead protection prevents future-peeking
- **Unified analytics** - Compare strategies across all markets in one database

### Performance
- **Faster execution** - Optimized data loading with caching
- **Lower memory usage** - Shared data loaders across strategies
- **Better database performance** - Indexed multi-market schema

### Maintainability
- **Modular architecture** - Changes to engine don't affect strategies
- **Plugin system** - Add new markets without modifying core code
- **Versioning** - Strategy and model versions tracked in database
- **Extensibility** - Easy to add new execution models, filters, analyzers

---

## Risk Mitigation

### Risk 1: Results Divergence
**Risk**: New framework produces different results than old system

**Mitigation**:
- Run parallel testing on same markets
- Compare predictions at timestamp level
- Validate portfolio state transitions
- Keep old system archived for reference

### Risk 2: Performance Regression
**Risk**: New system is slower than old system

**Mitigation**:
- Benchmark before migration
- Profile new system execution
- Optimize data loader caching
- Use multiprocessing where appropriate

### Risk 3: Breaking Changes
**Risk**: Other code depends on old system

**Mitigation**:
- Search entire codebase for imports
- Add deprecation warnings early
- Maintain old system during transition period
- Document all breaking changes

### Risk 4: Data Loss
**Risk**: Migration corrupts existing backtest results

**Mitigation**:
- Backup existing databases
- Use new database file initially (backtest_predictions_v2.db)
- Verify data migration scripts
- Keep both databases until fully validated

---

## Timeline Estimate

| Phase | Tasks | Effort |
|-------|-------|--------|
| Phase 1: Verification | Review new framework | 1 hour |
| Phase 2: Code Migration | Update backtest.py | 2-3 hours |
| Phase 3: Deprecation | Mark old files, update docs | 1 hour |
| Phase 4: Testing | Functional & integration tests | 2-3 hours |
| Phase 5: Cleanup | Archive & remove old code | 1 hour |
| **Total** | | **7-9 hours** |

---

## Success Metrics

### Functional
- [ ] New backtest.py produces identical results to old system
- [ ] All 5 strategies execute successfully
- [ ] Database contains correct predictions with proper schema
- [ ] Analysis scripts generate accurate metrics

### Non-Functional
- [ ] Code duplication reduced by >80%
- [ ] Execution time comparable or faster
- [ ] Memory usage comparable or lower
- [ ] Test coverage >70% for new components

### Process
- [ ] Zero production issues after migration
- [ ] No rollbacks required
- [ ] Team understands new architecture
- [ ] Documentation complete and accurate

---

## Post-Migration Opportunities

Once migration is complete, the new architecture enables:

1. **New Market Types**
   - Elections markets (KXELEC)
   - Crypto markets (KXCRYPTO)
   - Sports beyond baseball (NFL, NBA, etc.)

2. **Advanced Features**
   - Multi-market correlation strategies
   - Cross-market arbitrage detection
   - Portfolio optimization across markets
   - Real-time strategy parameter tuning

3. **Better Analytics**
   - Strategy performance across market types
   - Model calibration by market conditions
   - Risk metrics (Sharpe ratio, max drawdown)
   - Trade distribution analysis

4. **Operational Improvements**
   - Automated daily backtesting pipeline
   - Strategy A/B testing framework
   - Paper trading validation
   - Production deployment automation

---

## Questions & Decisions

### Decision 1: Database Migration
**Question**: Migrate existing backtest data to new schema?

**Options**:
A. Start fresh with new database
B. Write migration script to convert old data
C. Keep both databases

**Recommendation**: Option C initially, then B once validated

### Decision 2: CLI Interface
**Question**: Keep baseball-specific backtest.py or fully migrate to Scripts/run_backtest.py?

**Options**:
A. Update backtest.py to use new framework (backward compatibility)
B. Deprecate backtest.py, use only run_backtest.py
C. Maintain both with shared engine

**Recommendation**: Option A for smooth transition

### Decision 3: Strategy Versioning
**Question**: How to handle strategy version history?

**Options**:
A. Keep old strategy versions in archive
B. Delete old versions entirely
C. Maintain version history in database only

**Recommendation**: Option C - database tracks all versions used

---

## References

### Key Files - New Framework
- `Core/engine.py` - BacktestEngine implementation
- `Core/strategy.py` - BaseStrategy abstract interface
- `Core/context.py` - Immutable context passed to strategies
- `Core/data_loader.py` - BaseDataLoader interface
- `Markets/Baseball/data_loader.py` - Baseball-specific implementation
- `Markets/Baseball/strategies.py` - All 5 ported strategies
- `Scripts/run_backtest.py` - CLI execution script

### Key Files - Old Framework (Deprecated)
- `Baseball/Backtest/BacktestRunner.py` - Old runner
- `Baseball/Strategies/backtest_strategies.py` - Old strategies
- `Baseball/analyze_database.py` - Old analysis

### Documentation
- `CLAUDE.md` - Project overview
- `MIGRATION_PLAN.md` - This document
- Core/README.md (if exists)
- Markets/Baseball/README.md (if exists)

---

## Contact & Support

For questions about this migration:
- Review architecture documentation in Core/ and Markets/
- Check example implementations in Scripts/run_backtest.py
- Refer to CLAUDE.md for project conventions

---

**Last Updated**: 2026-03-15
**Status**: Ready for Implementation
**Estimated Completion**: Within 1-2 development sessions
