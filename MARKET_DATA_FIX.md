# IBKR 100 Market Data Lines Limitation - Fixed

## Problem
IBKR warned that your account is limited to 100 simultaneous market data lines. The original implementation was trying to subscribe to too many options at once, causing connection issues.

## Solution Implemented

### 1. Limited Parameters in `connection.py`
- Reduced from ±20% to ±10% strike range
- Limited to 5 strikes maximum per expiry
- Fetch only 1 expiry by default (nearest)
- Added subscription counting to track usage
- Proper cleanup of subscriptions after use

### 2. Bug Fixes
- Fixed iteration bug on line 188 (incorrect nested loop syntax)
- Fixed attribute errors with `openInterest` and `rho`
- Added proper `hasattr()` checks for all ticker attributes
- Made `rho` optional in Greeks model

### 3. Key Changes Made

#### Connection Parameters
```python
# Before
strike_range_pct: float = 0.20  # ±20% from spot
max_strikes: int = 20           # Too many strikes
target_expiries[:3]              # 3 expiries

# After  
strike_range_pct: float = 0.10  # ±10% from spot
max_strikes: int = 5             # Only 5 strikes
target_expiries[:1]              # Just nearest expiry
```

#### Market Data Tracking
```python
MAX_MARKET_DATA_LINES = 95  # Keep under 100 to be safe
self._subscription_count: int = 0  # Track active subscriptions
```

## Testing

Run the test script to verify the connection stays within limits:

```bash
cd /Users/schmoll/Desktop/SumpPump
python test_limited_connection.py
```

This will:
1. Connect to TWS
2. Fetch limited options for SPY
3. Report how many market data lines were used
4. Verify it stays under 100

## Usage Recommendations

### For General Options Viewing
- Use default parameters (will fetch ~20 options total)
- This gives you ATM options plus a few strikes each side

### For Specific Strategy Building
- Use `get_specific_options()` method in `connection_limited.py`
- Only fetch the exact strikes you need for the strategy
- Much more efficient use of limited lines

### Example Usage
```python
# General viewing (uses ~20 lines)
options = await tws_connection.get_options_chain("AAPL")

# Specific strategy (uses only 4 lines)
options = await tws_connection.get_specific_options(
    symbol="AAPL",
    strikes=[150, 155],  # Just 2 strikes
    expiry="2024-01-19",
    rights=['C']  # Just calls
)
```

## Alternative Approaches

If you need more data, consider:

1. **Upgrade your IBKR data plan** - Get more simultaneous lines
2. **Use batching** - Fetch data in sequential batches, unsubscribing between
3. **Cache aggressively** - The SQLite cache reduces need for fresh fetches
4. **Use delayed data** - Set `use_delayed_data: true` in config (free, unlimited)

## Current Status

✅ Connection module fixed and tested
✅ MCP server updated to use limited parameters
✅ Bug fixes for attribute errors
✅ Test script created

You can now restart Claude Desktop and the MCP server should connect successfully without exceeding your 100 line limit.