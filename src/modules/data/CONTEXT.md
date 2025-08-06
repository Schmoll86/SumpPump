# Data Module Context

## Purpose
Handles all market data operations including options chains, caching, and real-time updates.

## Key Components
- **OptionsChainData**: Main data handler with caching
- **OptionsChainCache**: SQLite-based cache with TTL
- **Statistics**: Put/call ratios, IV analysis, volume metrics

## Architecture
```
Claude → MCP Tool → OptionsChainData → Cache → TWS Connection
                                    ↓
                              SQLite Database
```

## Caching Strategy
- **TTL**: 5 minutes default (configurable)
- **Key Format**: `{symbol}_{expiry or 'all'}`
- **Invalidation**: On symbol change or manual clear

## Data Flow
1. Check cache for valid data
2. If miss/expired, fetch from TWS
3. Cache results with timestamp
4. Return formatted OptionContract objects

## Statistics Provided
- Put/Call ratio (volume & OI)
- ATM implied volatility
- IV by expiration
- Total volume/open interest

## Performance Considerations
- Batch requests when possible
- Limit strikes to ±20% of underlying
- Cache aggressively during market hours

## Testing
```python
from src.modules.data import options_data
await options_data.initialize()
chain = await options_data.fetch_chain("SPY")
```