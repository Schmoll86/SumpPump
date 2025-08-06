# Trade Execution & News Feed Fix

## Issues Fixed

### 1. Contract Qualification Errors
**Problem**: "Contract can't be hashed because no 'conId' value exists"
**Solution**: 
- Added proper contract qualification check
- Use the qualified contract returned by TWS
- Skip contracts that can't be qualified

### 2. NaN Volume Conversion
**Problem**: "cannot convert float NaN to integer"
**Solution**: Added `math.isnan()` check before converting volume to integer

### 3. Missing py_vollib
**Problem**: Black-Scholes calculations failing
**Solution**: py_vollib is already installed, import warnings can be ignored

### 4. News Feed Support
**Added**: New MCP tool `get_news` that:
- Fetches IBKR news for any symbol
- Supports provider filtering
- Returns up to 50 articles
- Handles permission errors gracefully

## How to Test USAR Options

### 1. Test Data Fetching
```bash
cd /Users/schmoll/Desktop/SumpPump
python test_usar_trade.py
```

This will:
- Connect to TWS
- Fetch USAR options
- Display available strikes and expiries
- Show ATM options
- Create a sample long call strategy
- Display account info

### 2. Via Claude Desktop

To trade USAR options through Claude Desktop:

#### Step 1: Get Options Chain
Ask Claude: "Show me USAR options"

#### Step 2: Calculate Strategy
Ask Claude: "Calculate a long call strategy for USAR at the 15 strike expiring next month"

#### Step 3: Execute Trade (with confirmation)
Ask Claude: "Execute the USAR long call trade" 
Then confirm with: "USER_CONFIRMED"

### 3. Test News Feed
Ask Claude: "Get news for USAR" or "Show me recent AAPL news"

## Current Trade Execution Flow

1. **Data Fetch** → Gets limited options (5 strikes, ±10% from spot)
2. **Strategy Calculation** → Validates Level 2 compliance
3. **Confirmation Required** → Must provide "USER_CONFIRMED" token
4. **Execution** → Places combo order through TWS
5. **Stop Loss Prompt** → Reminds to set protective stop

## Troubleshooting

### If USAR options aren't loading:
- Check if market is open
- Verify USAR is a valid symbol in TWS
- Check if you have options permissions for this underlying
- Try a more liquid symbol like SPY or AAPL

### If execution fails:
- Ensure you provided "USER_CONFIRMED" as confirmation token
- Check account has sufficient buying power
- Verify the option contract exists and has liquidity
- Check TWS order permissions

### If news feed doesn't work:
- Verify you have news subscriptions in IBKR account
- Check config has `enable_news: true`
- Some symbols may not have news available

## Key Files Modified

1. `/src/modules/tws/connection.py`
   - Fixed contract qualification
   - Added NaN checks for volume
   - Improved error handling

2. `/src/mcp/server.py`
   - Added `get_news` tool
   - News provider filtering
   - Article fetching with error handling

3. Test scripts created:
   - `test_usar_trade.py` - Full USAR trading flow test
   - `test_limited_connection.py` - Market data limit test

## Next Steps

1. Run `test_usar_trade.py` to verify USAR options load correctly
2. Restart Claude Desktop to pick up the changes
3. Try the trade flow through Claude Desktop
4. Test news feed with various symbols

The system should now properly handle USAR options trading and provide news feeds through the MCP interface.