# SumpPump - IBKR Trading Assistant Context

## Project Overview
SumpPump is an MCP (Model Context Protocol) server that bridges Claude Desktop with Interactive Brokers TWS for conversational options trading. It provides real-time market data access, strategy analysis, and trade execution with mandatory confirmation workflows.

**Current Version**: 2.0.2 (January 2025)
**Total MCP Tools**: 39 fully integrated and operational tools

## Core Architecture Principles

### 1. Safety First
- **NEVER** execute trades without explicit user confirmation
- Always calculate and display max loss before execution
- Prompt for stop loss after every fill
- Validate all orders against account constraints

### 2. Async-First Design
- Use `ib_async` for all TWS interactions
- Implement proper async/await patterns throughout
- Handle concurrent data streams efficiently
- Never block the event loop

### 3. MCP Integration
- Follow FastMCP patterns for tool implementation
- Use proper type hints for all MCP tools
- Implement comprehensive error handling
- Return structured responses for Claude interpretation

## Technology Stack

### Core Libraries
- **ib_async**: TWS API wrapper (NOT ib_insync - use the updated library)
- **FastMCP**: MCP server framework
- **asyncio**: Async runtime
- **pydantic**: Data validation

### Data Processing
- **pandas**: Options chain manipulation
- **numpy**: Mathematical calculations
- **py_vollib**: Black-Scholes pricing

## Coding Standards

### Python Style
```python
# Use type hints everywhere
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

@dataclass
class OptionContract:
    symbol: str
    strike: float
    expiry: datetime
    # ... always use dataclasses for data structures
```

### Async Patterns
```python
# Always use async context managers
async with TWSConnection() as tws:
    data = await tws.get_options_chain(symbol)
    
# Never use blocking calls
# BAD: time.sleep(1)
# GOOD: await asyncio.sleep(1)
```

### Error Handling
```python
# Always wrap TWS calls
try:
    result = await tws.execute_order(order)
except TWSError as e:
    logger.error(f"TWS execution failed: {e}")
    return MCPError(code="TWS_ERROR", message=str(e))
```

## Module Structure

### TWS Connection (`src/modules/tws/`)
- Maintains persistent connection
- Handles reconnection logic
- Manages rate limiting
- Subscribes to market data

### Data Module (`src/modules/data/`)
- Fetches and caches options chains
- Manages historical data
- Processes market statistics
- Handles news feeds

### Strategies Module (`src/modules/strategies/`)
- Implements IBKR Level 2 permitted strategies only
- Long options (calls/puts) and debit spreads
- Covered calls and protective strategies
- NO credit spreads or naked shorts (Level 3+ required)
- Calculates P&L profiles
- Determines breakeven points
- Suggests optimal strikes

### Risk Module (`src/modules/risk/`)
- Calculates max loss/gain
- Validates position sizing
- Checks margin requirements
- Implements stop loss logic

### Execution Module (`src/modules/execution/`)
- Builds combo orders
- Requires confirmation tokens
- Handles partial fills
- Reports execution status

## MCP Tool Specifications (39 Tools Total)

### Market Data Tools (12)
- `trade_get_quote` - Real-time stock/ETF quotes
- `trade_get_options_chain` - Full options chain with Greeks
- `trade_get_price_history` - Historical OHLCV data
- `trade_get_positions` - Current portfolio positions
- `trade_get_open_orders` - Pending orders
- `trade_get_account_summary` - Account balances and margin
- `trade_get_news` - News feed (if subscribed)
- `trade_get_watchlist_quotes` - Multiple symbol quotes
- `trade_get_market_depth` - Level 2 order book
- `trade_get_depth_analytics` - Price impact analysis
- `trade_scan_market` - Market scanner for opportunities (high IV, unusual options, momentum)
- `trade_check_market_data` - Verify market data feed status and subscriptions

### Strategy & Risk Tools (8)
- `trade_calculate_strategy` - Analyze options strategies with P&L
- `trade_check_margin_risk` - Margin call risk assessment
- `trade_get_volatility_analysis` - IV rank and volatility metrics
- `trade_get_index_quote` - Index quotes (SPX, NDX, VIX)
- `trade_get_index_options` - Index options chains
- `trade_get_vix_term_structure` - VIX term structure analysis
- `trade_analyze_opportunity` - Comprehensive trade opportunity analysis
- `trade_get_session_status` - Trading session state and workflow status

### Execution Tools (11)
- `trade_execute` - Execute trades with confirmation
- `trade_execute_with_verification` - Execute with enhanced verification
- `trade_close_position` - Close existing positions
- `trade_set_stop_loss` - Set protective stops
- `trade_modify_order` - Modify pending orders
- `trade_cancel_order` - Cancel pending orders
- `trade_create_conditional_order` - Create conditional/bracket orders
- `trade_buy_to_close` - Buy to close options positions
- `trade_direct_close` - Direct position closing without confirmation
- `trade_emergency_close` - Emergency close all positions
- `trade_set_price_alert` - Set price alerts

### Extended Hours Tools (3)
- `trade_place_extended_order` - Place extended hours orders
- `trade_get_extended_schedule` - Get extended trading schedule
- `trade_modify_for_extended` - Modify order for extended hours

### Advanced Tools (5)
- `trade_roll_option` - Roll options forward
- `trade_get_crypto_quote` - Crypto quotes (config required)
- `trade_analyze_crypto` - Crypto analysis (config required)
- `trade_get_fx_quote` - Forex quotes (config required)
- `trade_analyze_fx_pair` - FX analysis (config required)

### Data Flow
```
Claude Desktop → MCP Server → TWS API → IBKR
              ←              ←         ←
```

## TWS Configuration Requirements

### API Settings
- Port: 7497 (TWS default)
- Enable: "Download open orders on connection"
- Memory: 4096 MB minimum
- Trusted IPs: 127.0.0.1

### Market Data Subscriptions
- US Options Level 1 (minimum)
- Real-time data (not delayed)
- News feeds enabled

## Session Management

### Per-Symbol Context
- Clear cache when switching symbols
- Don't persist between conversations
- Fresh context for each trade discussion

### State Management
```python
class SessionState:
    current_symbol: Optional[str] = None
    options_chain: Optional[Dict] = None
    active_strategy: Optional[Strategy] = None
    # Reset on symbol change
```

## Testing Strategy

### Unit Tests
- Mock TWS connections
- Test strategy calculations
- Validate risk logic

### Integration Tests
- Test MCP tool responses
- Validate confirmation flows
- Check error handling

## Deployment Checklist

- [ ] TWS running and configured
- [ ] API port enabled
- [ ] Market data subscriptions active
- [ ] MCP server registered with Claude Desktop
- [ ] Environment variables configured
- [ ] Logging enabled
- [ ] Cache directory created

## Common Issues & Solutions

### Connection Issues
- Verify TWS is running
- Check API settings
- Confirm port 7497 is open

### Data Issues
- Verify market data subscriptions
- Check for market hours
- Confirm symbol validity

### Execution Issues
- Always require confirmation
- Validate order parameters
- Check account permissions

## Development Workflow

1. Start TWS first
2. Activate virtual environment
3. Run MCP server
4. Connect Claude Desktop
5. Test with small positions first

## Debugging Commands

### Check MCP Server Status
```bash
# View server logs
tail -f /tmp/mcp_server.log

# Check if server is running
ps aux | grep server.py

# Restart MCP server
pkill -f "server.py" && sleep 1
/Users/schmoll/Desktop/SumpPump/venv/bin/python src/mcp/server.py
```

### Test Specific Components
```bash
# Test strategy persistence
/Users/schmoll/Desktop/SumpPump/venv/bin/python test_strategy_persistence.py

# Test single option routing
/Users/schmoll/Desktop/SumpPump/venv/bin/python test_single_option.py

# Test options order fixes
/Users/schmoll/Desktop/SumpPump/venv/bin/python test_options_order_fixes.py
```

## Important Reminders

- **LIVE TRADING ONLY** - No paper trading
- All trades need explicit confirmation
- Always calculate max risk
- Prompt for stops after fills
- Clear cache between symbols
- Single options use `place_option_order()` not combo orders
- Always verify dict vs object types when accessing attributes
- Use agents for code review before committing changes

## V2 Architecture Components (January 2025)

### Core System Components
- **TradingSession State Machine**: Enforces proper workflow (IDLE → ANALYZING → STRATEGY_SELECTED → RISK_VALIDATED → EXECUTING → FILLS_CONFIRMED → STOPS_PLACED → MONITORING → CLOSED)
- **StrategyManager**: Persistent strategy storage with 5-minute TTL
- **PreTradeAnalysisPipeline**: Comprehensive pre-trade analysis
- **RiskValidationFramework**: Multi-layer risk validation
- **ExecutionSafety Validator**: Prevents accidental executions

## CRITICAL RECENT FIXES (January 2025 - v2.0.2)

### Event Loop Issues - FULLY RESOLVED
- Applied `nest_asyncio.apply()` at module start to allow nested event loops
- Implemented lazy loading with `LazyTWSConnection` proxy class
- Fixed all async/await syntax errors in sync functions
- Files fixed: src/modules/tws/connection.py, src/mcp/server.py

### Greeks Data Retrieval - FIXED
- Added explicit genericTickList='106' for Greeks request
- Implemented retry mechanism with 3-second max wait
- Added IV calculation fallback for missing Greeks
- File: src/modules/tws/connection.py (lines 368-396)

### Strategy Session State - IMPLEMENTED
- Created `SessionState` class for strategy persistence
- Strategies now persist between calculate and execute calls
- 5-minute TTL for security
- File: src/mcp/server.py (lines 44-79)

### Account Connection - VALIDATED
- Account U16348403 configured in .env
- Auto-detection of account ID working
- Client ID auto-finds available ID (no more conflicts)
- Positions and balances retrieving correctly

### MCP Integration - FULLY OPERATIONAL
- All 37 tools working correctly
- Session state management active with TradingSession state machine
- Strategy persistence with StrategyManager
- Comprehensive logging added with [SESSION], [CALC], [EXEC] prefixes
- Version 2.0 with complete V2 architecture

### Order Attributes Fix - RESOLVED (January 2025)
- Fixed missing order attributes (orderRef, parentId, tif, ocaType) 
- Added proper type coercion in utils/type_coercion.py
- Handles both old camelCase and new snake_case attributes
- Prevents AttributeError in order execution flow

### Type Coercion Module - IMPLEMENTED
- Created centralized type conversion for all TWS objects
- Handles Contract, Order, Trade, Position conversions
- Ensures compatibility between ib_async versions
- File: src/modules/utils/type_coercion.py

### Production Stability - VERIFIED
- All critical trading paths tested and operational
- Greeks data retrieval working with retry mechanism
- Order execution with proper attribute handling
- Stop loss recommendations with logging (not print statements)
- Session state persistence across tool calls

### Single Option Order Routing - FIXED (January 2025)
- Single options now route to `place_option_order()` not combo orders
- Creates proper Option contracts with secType="OPT"
- Combo orders only used for multi-leg strategies (spreads)
- File: src/mcp/server.py (lines 793-803), src/modules/tws/connection.py (lines 835-956)

### Dict vs Object Access - RESOLVED (January 2025)
- Fixed 'dict' object has no attribute 'contract' error
- Proper type checking with `isinstance(leg_data, dict)`
- Correct reconstruction of OptionLeg objects from dict data
- Enhanced enum parsing for OptionRight and OrderAction
- File: src/mcp/server.py (lines 669-730)

### TWS API Compliance - CORRECTED (January 2025)
- Orders and Contracts properly separated (no order.contract)
- Option multiplier explicitly set to '100'
- Account dynamically loaded from config (no hardcoding)
- Use openTrades() not openOrders() for order info
- Files: src/modules/tws/connection.py, src/modules/execution/

### Market Scanner Tools - ADDED (January 2025)
- New market scanner module for finding opportunities
- Scans for high IV stocks, unusual options volume, momentum
- Market overview with indices (SPY, QQQ, IWM, VIX)
- Files: src/modules/scanner/, src/mcp/server.py (lines 3524-3672)

## Coding Workflow

### Code Review Guidelines
- Use `data-flow-architect` agent when:
  - Analyzing data flow through complex systems
  - Identifying bottlenecks or failure points
  - Ensuring fault tolerance in data pipelines
  - Mapping information flow between components
  
- Use `python-code-reviewer` agent when:
  - Reviewing newly written Python functions or modules
  - Checking for best practices and project standards
  - After refactoring existing code
  - Implementing new features or fixing bugs

### Agent Usage Best Practices
- Launch agents proactively for significant code changes
- Use agents concurrently when possible for performance
- Agents are stateless - provide complete context in prompts
- Trust agent outputs but verify critical changes
- Clearly specify if expecting code writing vs research

### Testing Workflow
1. Write code changes
2. Use `python-code-reviewer` to validate implementation
3. Use `data-flow-architect` to verify data integrity
4. Run test scripts to confirm functionality
5. Restart MCP server to apply changes