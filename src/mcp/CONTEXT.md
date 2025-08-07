# MCP Server Module Context

## Purpose
Provides the Model Context Protocol interface for Claude Desktop integration.

## Architecture
```
Claude Desktop ↔ MCP Protocol ↔ FastMCP Server ↔ Business Modules ↔ TWS API
```

## Available Tools (37 Total)

### Market Data (10 tools)
- **trade_get_quote**: Real-time stock/ETF quotes
- **trade_get_options_chain**: Full options chain with Greeks
- **trade_get_price_history**: Historical OHLCV data
- **trade_get_positions**: Current portfolio positions
- **trade_get_open_orders**: Pending orders
- **trade_get_account_summary**: Account balances and margin
- **trade_get_news**: News feed
- **trade_get_watchlist_quotes**: Multiple symbol quotes
- **trade_get_market_depth**: Level 2 order book
- **trade_get_depth_analytics**: Price impact analysis

### Strategy & Risk (8 tools)
- **trade_calculate_strategy**: Analyze options strategies
- **trade_check_margin_risk**: Margin call risk assessment
- **trade_get_volatility_analysis**: IV rank and volatility metrics
- **trade_get_index_quote**: Index quotes
- **trade_get_index_options**: Index options chains
- **trade_get_vix_term_structure**: VIX term structure
- **trade_analyze_opportunity**: Trade opportunity analysis
- **trade_get_session_status**: Trading session state

### Execution (11 tools)
- **trade_execute**: Execute trades with confirmation
- **trade_execute_with_verification**: Enhanced verification
- **trade_close_position**: Close existing positions
- **trade_set_stop_loss**: Set protective stops
- **trade_modify_order**: Modify pending orders
- **trade_cancel_order**: Cancel pending orders
- **trade_create_conditional_order**: Conditional/bracket orders
- **trade_buy_to_close**: Buy to close options
- **trade_direct_close**: Direct position closing
- **trade_emergency_close**: Emergency close all
- **trade_set_price_alert**: Set price alerts

### Extended Hours (3 tools)
- **trade_place_extended_order**: Extended hours orders
- **trade_get_extended_schedule**: Extended trading schedule
- **trade_modify_for_extended**: Modify for extended hours

### Advanced (5 tools)
- **trade_roll_option**: Roll options forward
- **trade_get_crypto_quote**: Crypto quotes
- **trade_analyze_crypto**: Crypto analysis
- **trade_get_fx_quote**: Forex quotes
- **trade_analyze_fx_pair**: FX analysis

## Tool Implementation Pattern
```python
@mcp.tool()
async def tool_name(param: type) -> Dict[str, Any]:
    """Tool description for Claude."""
    try:
        # 1. Validate inputs
        # 2. Call business module
        # 3. Format response
        return {"status": "success", "data": ...}
    except Exception as e:
        logger.error(f"Tool failed: {e}")
        return {"error": str(e)}
```

## Safety Integration
Every tool that modifies state MUST:
1. Check risk limits
2. Require confirmation
3. Log actions
4. Handle errors gracefully

## Response Format
```json
{
  "status": "success|error",
  "data": {...},
  "timestamp": "ISO-8601",
  "warnings": [],
  "next_actions": []
}
```

## Registration with Claude Desktop
```json
{
  "mcpServers": {
    "sump-pump": {
      "command": "python",
      "args": ["/path/to/src/mcp/server.py"]
    }
  }
}
```

## Testing Tools
```python
# Direct invocation
result = await get_options_chain("AAPL")

# Via MCP protocol
python src/mcp/server.py
```

## Performance
- Cache frequently requested data
- Batch operations when possible
- Return partial results for long operations
- Include progress indicators