# SumpPump - IBKR Trading Assistant

Production-ready MCP (Model Context Protocol) server that bridges Claude Desktop with Interactive Brokers TWS for conversational options trading and market analysis. All 27 trading tools are fully integrated and operational.

## ✅ Current Status (v2.0 - January 2025)

- **27 MCP Tools**: Fully integrated and operational
- **Live Trading**: Production-ready with real money trading
- **TWS Integration**: Complete with auto-reconnection and event loop fixes
- **Risk Management**: Mandatory confirmation workflows
- **Level 2 Options**: Full support for IBKR Level 2 strategies
- **Session State**: Strategy persistence between calculate and execute
- **Greeks Data**: Full options Greeks now working correctly
- **Claude Code**: Developed with Claude Code development kit

## Features

### Core Trading Capabilities
- **Options Trading**: Full options chain access with Greeks, multi-leg strategies
- **Real-Time Market Data**: Live quotes, Level 1/2 data, options chains
- **Strategy Analysis**: Calculate P&L, breakeven points, and risk metrics
- **Trade Execution**: Place orders with mandatory confirmation workflow
- **Risk Management**: Position sizing, stop-loss prompts, max loss calculations

### Working MCP Tools (27 Total)

#### Market Data (8 tools)
- `trade_get_quote` - Real-time stock/ETF quotes
- `trade_get_options_chain` - Full options chain with Greeks
- `trade_get_price_history` - Historical OHLCV data
- `trade_get_positions` - Current portfolio positions
- `trade_get_open_orders` - Pending orders
- `trade_get_account_summary` - Account balances and margin
- `trade_get_news` - News feed (if subscribed)
- `trade_get_index_quote` - Index quotes (SPX, NDX, VIX)

#### Strategy & Risk (6 tools)
- `trade_calculate_strategy` - Analyze options strategies
- `trade_check_margin_risk` - Margin call risk assessment
- `trade_get_volatility_analysis` - IV rank and volatility metrics
- `trade_get_watchlist_quotes` - Multiple symbol quotes
- `trade_get_market_depth` - Level 2 order book
- `trade_get_depth_analytics` - Price impact analysis

#### Execution (5 tools)
- `trade_execute` - Execute trades with confirmation
- `trade_close_position` - Close existing positions
- `trade_set_stop_loss` - Set protective stops
- `trade_modify_order` - Modify pending orders
- `trade_cancel_order` - Cancel pending orders

#### Advanced (8 tools)
- `trade_roll_option_position` - Roll options forward
- `trade_set_price_alert` - Price alerts
- `trade_get_index_options` - Index options chains
- `trade_get_crypto_quote` - Crypto quotes (config required)
- `trade_get_fx_quote` - Forex quotes (config required)
- `trade_analyze_crypto` - Crypto analysis (config required)
- `trade_analyze_fx_pair` - FX analysis (config required)
- `trade_calculate_index_futures` - Futures calculations

## Quick Start

### Prerequisites
- Interactive Brokers TWS or IB Gateway running
- Python 3.11+
- Claude Desktop with MCP support
- Active IBKR account with Level 2 options permissions

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/SumpPump.git
cd SumpPump
```

2. Run setup:
```bash
./setup.sh
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your settings
```

4. Configure Claude Desktop:
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "sump-pump": {
      "command": "/path/to/SumpPump/venv/bin/python",
      "args": ["/path/to/SumpPump/src/mcp/server.py"],
      "env": {}
    }
  }
}
```

5. Start TWS and Claude Desktop

## Configuration

### Essential Settings (.env)

```bash
# TWS Connection
TWS_HOST=127.0.0.1
TWS_PORT=7497  # 7497 for live, 7496 for paper
TWS_CLIENT_ID=5
TWS_ACCOUNT=  # Leave empty for auto-detect

# Market Data
USE_DELAYED_DATA=false
USE_LEVEL2_DEPTH=true
ENABLE_INDEX_TRADING=true
SUBSCRIBE_TO_NEWS=true

# Optional Features
USE_CRYPTO_FEED=false  # Enable for crypto
USE_FX_FEED=false      # Enable for forex

# Risk Management
REQUIRE_CONFIRMATION=true
MAX_POSITION_SIZE_PERCENT=5.0
DEFAULT_STOP_LOSS_PERCENT=10.0
```

## Usage Examples

In Claude Desktop:

```
"Show me SPY options chain for next Friday"
"Calculate a bull call spread on AAPL 150/155"
"Get my current positions"
"What's my account balance and margin status?"
"Execute a long call on TSLA 250 strike"
"Show Level 2 depth for NVDA"
```

## Safety Features

- **Mandatory Confirmation**: All trades require "USER_CONFIRMED" token
- **Max Loss Display**: Always shows maximum potential loss before execution
- **Stop Loss Prompts**: Automatic prompts after fills
- **Level 2 Only**: No naked options or credit spreads without Level 3
- **Rate Limiting**: Prevents API overload
- **Connection Monitoring**: Auto-reconnection on disconnect

## Project Structure

```
SumpPump/
├── src/
│   ├── mcp/
│   │   └── server.py          # MCP server with 27 tools
│   ├── core/                  # Infrastructure
│   │   ├── exceptions.py      # Error hierarchy
│   │   ├── connection_monitor.py
│   │   ├── rate_limiter.py
│   │   └── settings.py
│   ├── modules/
│   │   ├── tws/               # TWS connection
│   │   ├── data/              # Market data modules
│   │   ├── strategies/        # Level 2 strategies
│   │   ├── execution/         # Order execution
│   │   └── risk/              # Risk management
│   └── models.py              # Data models
├── tests/                     # Test suite
├── .env                       # Configuration
├── CLAUDE.md                  # Context for Claude
└── README.md                  # This file
```

## Recent Fixes (v2.0 - January 2025)

### Event Loop Conflicts
- **Problem**: "This event loop is already running" error
- **Solution**: Applied `nest_asyncio` patch for nested event loop compatibility
- **Files**: `src/mcp/server.py`, `src/modules/tws/connection.py`

### Greeks Data Retrieval
- **Problem**: Options Greeks showing as 0 or NaN
- **Solution**: Added explicit Greeks request with genericTickList='106' and proper wait time
- **File**: `src/modules/tws/connection.py` (lines 368-396)

### Strategy Session State
- **Problem**: Strategy lost between calculate and execute calls
- **Solution**: Implemented SessionState class for strategy persistence
- **File**: `src/mcp/server.py` (lines 44-79)

### Async/Await Syntax Errors
- **Problem**: 'await' outside async function in base strategy
- **Solution**: Made `_find_breakeven_in_range` async
- **File**: `src/modules/strategies/base.py` (line 394)

## Troubleshooting

### Connection Issues
- Verify TWS is running and API is enabled
- Check port settings (7497 for live)
- Ensure Client ID is not in use (auto-finds available ID)
- Check firewall settings
- Account should show as U16348403 (or your account)

### "FunctionTool not callable" in Claude Desktop
This is **normal behavior** for MCP tools. The tools work correctly through the MCP interface.

### Market Data Issues
- Verify market data subscriptions in IBKR
- Check if market is open
- Confirm symbol validity
- Greeks require options data subscription

### After Hours
- Options will show NaN for bid/ask
- Use limit orders with manual pricing
- News feeds may be empty

## Requirements

- IBKR Account with Level 2 options permissions
- Market data subscriptions (US equities/options minimum)
- TWS API enabled on port 7497
- Python packages: ib_async, fastmcp, pydantic, loguru

## Support

- Documentation: See CLAUDE.md for detailed context
- TWS API Docs: [IBKR API Documentation](https://interactivebrokers.github.io/)

## License

MIT License - See LICENSE file for details

## Disclaimer

**IMPORTANT**: This software executes real trades with real money. Trading involves substantial risk of loss. Always verify orders before execution. Test thoroughly in paper trading first. The authors are not responsible for any financial losses.