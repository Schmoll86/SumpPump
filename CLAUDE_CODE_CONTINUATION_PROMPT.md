# Claude Code Continuation Prompt for SumpPump Development

## Project Context
You are continuing development of SumpPump, an IBKR Options Trading Assistant MCP server that bridges Claude Desktop with Interactive Brokers TWS. The project architecture has been established with safety-first design principles and modular structure. You must follow the Claude Code Development Kit patterns already in place.

## Current Project State
- **Location**: `/Users/schmoll/Desktop/SumpPump`
- **Phase**: Initial architecture complete, ready for implementation
- **Framework**: MCP server with FastMCP, using ib_async for TWS
- **Documentation**: Claude Code Dev Kit integrated with 3-tier docs

## Critical Requirements
1. **ALWAYS read these files first**:
   - `CLAUDE.md` - Master context with coding standards
   - `docs/ai-context/project-structure.md` - Full tech stack
   - `docs/ai-context/handoff.md` - Current state and next steps
   - `PROJECT_SETUP.md` - Implementation guide

2. **Use ib_async, NOT ib_insync** - ib_async is the modern maintained fork
3. **Port Configuration**: 7496 for paper, 7497 for live (check .env)
4. **Safety First**: NEVER execute trades without explicit confirmation
5. **Async patterns**: All I/O operations must be async/await

## Development Priorities (In Order)

### Phase 1: Complete TWS Connection [CURRENT]
```python
# File: src/modules/tws/connection.py
# TODO: Complete the connection manager with:
- Implement market data subscriptions
- Add contract creation helpers
- Complete error handling
- Test connection with simple market data request
```

### Phase 2: Options Chain Data Module
```python
# Create: src/modules/data/options_chain.py
# Implement:
- Fetch full options chain with Greeks
- Cache in SQLite with TTL
- Real-time updates via subscription
- Use ib_async's Option contract properly
```

### Phase 3: Strategy Calculators
```python
# Create: src/modules/strategies/verticals.py
# Create: src/modules/strategies/calendar.py
# Implement all Level 2 strategies with:
- P&L calculations
- Max profit/loss
- Breakeven points
- Probability calculations using py_vollib
```

### Phase 4: Risk Management
```python
# Create: src/modules/risk/calculator.py
# Implement:
- Position sizing based on account percentage
- Max loss validation
- Margin requirement checks
- Stop loss calculations
```

### Phase 5: MCP Tool Integration
```python
# Update: src/mcp/server.py
# Wire the skeleton tools to actual implementations:
- Connect get_options_chain() to data module
- Connect calculate_strategy() to strategies module
- Add confirmation system for execute_trade()
- Implement all IBKR data feeds mentioned in requirements
```

## Key Implementation Patterns

### TWS Connection Pattern
```python
from ib_async import IB, Stock, Option, MarketOrder, LimitOrder, util

class TWSConnection:
    async def get_options_chain(self, symbol: str) -> List[OptionContract]:
        await self.ensure_connected()
        
        # Create underlying contract
        stock = Stock(symbol, 'SMART', 'USD')
        
        # Get option chain
        chains = await self.ib.reqSecDefOptParamsAsync(
            stock.symbol, '', stock.secType, stock.conId
        )
        
        # For each expiry, get contracts
        for chain in chains:
            for strike in chain.strikes:
                for right in ['C', 'P']:
                    contract = Option(
                        symbol, chain.expiry, strike, right, 'SMART'
                    )
                    # Subscribe to market data
                    ticker = self.ib.reqMktData(contract)
                    # Process Greeks from ticker
```

### MCP Tool Pattern
```python
@mcp.tool()
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None
) -> Dict[str, Any]:
    """Full implementation connecting to modules."""
    try:
        async with tws_connection.session() as tws:
            # Get data from data module
            from src.modules.data import options_data
            chain = await options_data.fetch_chain(symbol, expiry)
            
            # Include IBKR statistics
            stats = await options_data.get_statistics(symbol)
            
            return {
                "symbol": symbol,
                "chain": chain.to_dict(),
                "statistics": stats,
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"Failed to fetch chain: {e}")
        return {"error": str(e)}
```

### Confirmation System
```python
# CRITICAL: Every trade needs confirmation
@mcp.tool()
async def execute_trade(
    strategy: Dict[str, Any],
    confirm_token: str
) -> Dict[str, Any]:
    # Validate confirmation token
    if not confirm_token or confirm_token != "USER_CONFIRMED":
        return {
            "error": "Trade requires explicit confirmation",
            "required": "confirm_token='USER_CONFIRMED'"
        }
    
    # Only then proceed with execution
    from src.modules.execution import executor
    result = await executor.execute_strategy(strategy)
    
    # Prompt for stop loss after execution
    return {
        "execution": result,
        "next_action": "Set stop loss recommended",
        "suggested_stop": result.suggested_stop_price
    }
```

## Testing Workflow

1. **Test TWS Connection**:
```bash
cd /Users/schmoll/Desktop/SumpPump
source venv/bin/activate
python -c "
import asyncio
from src.modules.tws import tws_connection
asyncio.run(tws_connection.connect())
"
```

2. **Test MCP Server**:
```bash
python src/mcp/server.py
# Should start without errors
```

3. **Test Each Module**:
```bash
pytest tests/unit/test_tws_connection.py -v
pytest tests/unit/test_options_data.py -v
pytest tests/unit/test_strategies.py -v
```

## IBKR Data Integration Requirements

Remember to implement access to ALL these IBKR tools:
- **Option Chains**: Full chain with Greeks, IV, volume
- **Historical Data**: For backtesting strategies
- **Market Scanners**: Find high IV, unusual volume
- **News Feeds**: Dow Jones, Reuters integration
- **Option Statistics**: Put/call ratios, IV rank/percentile
- **Probability Lab**: Success rate calculations
- **Strategy Builder**: Pre-built strategy templates
- **Liquidity Analysis**: Bid-ask spreads, depth

## Documentation Update Protocol

After implementing each module:
1. Create/update CONTEXT.md in that module's directory
2. Update `docs/ai-context/handoff.md` with progress
3. Keep `CLAUDE.md` synchronized with any architectural changes

## Environment Variables to Set

Edit `.env` file:
```env
TWS_PORT=7496  # or 7497 for live
TWS_ACCOUNT=YOUR_ACCOUNT_ID
TWS_CLIENT_ID=1
MARKET_DATA_TIMEOUT=30
```

## Common Issues & Solutions

1. **ImportError for ib_async**:
   - Install: `pip install ib_async`
   - NOT ib_insync (that's the old library)

2. **TWS Connection Fails**:
   - Check TWS is running
   - Verify API enabled in Global Configuration
   - Confirm port matches .env setting
   - Add 127.0.0.1 to Trusted IPs

3. **No Market Data**:
   - Check subscriptions in TWS
   - Verify not using delayed data for options
   - Use market data type 1 (live) not 3 (delayed)

## Command Summary

```bash
# Quick start
cd /Users/schmoll/Desktop/SumpPump
source venv/bin/activate
make run  # Start MCP server

# Development
make test  # Run tests
make format  # Format code
make lint  # Check code quality
```

## IMPORTANT REMINDERS

1. **LIVE TRADING MODE** - Port 7497 is correct for TWS live trading
2. **NO PAPER TRADING** - This is production, trade carefully
3. **Always require confirmation** - User must explicitly confirm every trade
4. **Test with small positions first**
5. **Use sub-agents** for parallel development when implementing multiple modules
6. **Follow Claude Code Dev Kit patterns** - The framework is already in place

## Ready to Continue!

Start by running:
```bash
cd /Users/schmoll/Desktop/SumpPump
./setup.sh  # If not done already
source venv/bin/activate
```

Then implement Phase 1: Complete the TWS connection module.

**Remember: You're building a LIVE TRADING system. Safety protocols are not optional!**