# SumpPump - IBKR Trading Assistant Context

## Project Overview
SumpPump is an MCP (Model Context Protocol) server that bridges Claude Desktop with Interactive Brokers TWS for conversational options trading. It provides real-time market data access, strategy analysis, and trade execution with mandatory confirmation workflows.

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

## MCP Tool Specifications

### Critical Tools
1. `get_options_chain()` - Full chain with Greeks
2. `calculate_strategy()` - Strategy analysis
3. `execute_trade()` - With confirmation
4. `set_stop_loss()` - Protective orders

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

## Important Reminders

- **LIVE TRADING ONLY** - No paper trading
- All trades need explicit confirmation
- Always calculate max risk
- Prompt for stops after fills
- Clear cache between symbols
