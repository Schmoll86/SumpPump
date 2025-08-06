# SumpPump - IBKR Trading Assistant

A sophisticated MCP (Model Context Protocol) server that bridges Claude Desktop with Interactive Brokers TWS for conversational options trading and market analysis.

## Features

### Core Trading Capabilities
- **Options Trading**: Full options chain access with Greeks, multi-leg strategies
- **Real-Time Market Data**: Live quotes, Level 1 data, options chains
- **Strategy Analysis**: Calculate P&L, breakeven points, and risk metrics
- **Trade Execution**: Place orders with mandatory confirmation workflow
- **Risk Management**: Position sizing, stop-loss prompts, max loss calculations

### Advanced Data Feeds (NEW)
- **Level 2 Depth of Book**: IEX depth data with price impact analysis
- **Index Trading**: SPX, NDX, VIX options and futures
- **Cryptocurrency**: BTC, ETH, and major cryptos via ZEROHASH/PAXOS
- **Forex Trading**: Major and minor pairs via IDEALPRO
- **Premium News**: Dow Jones, Reuters, Benzinga feeds

### Infrastructure
- **Connection Monitoring**: Automatic reconnection and health checks
- **Rate Limiting**: Smart API throttling to prevent overload
- **Error Recovery**: Comprehensive exception handling with recovery strategies
- **Type Safety**: Pydantic validation for all configurations

## Quick Start

### Prerequisites
- Interactive Brokers TWS or IB Gateway running
- Python 3.11+
- Claude Desktop with MCP support
- Active IBKR account with appropriate permissions

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
TWS_PORT=7497  # 7497 for live, 7496 for paper
TWS_CLIENT_ID=5

# Market Data
USE_DELAYED_DATA=false
USE_LEVEL2_DEPTH=true
ENABLE_INDEX_TRADING=true

# Optional Features
USE_CRYPTO_FEED=false  # Enable for crypto
USE_FX_FEED=false      # Enable for forex

# Risk Management
REQUIRE_CONFIRMATION=true
MAX_POSITION_SIZE_PERCENT=5.0
```

## Available MCP Tools

### Options Trading
- `get_options_chain(symbol, expiry)` - Fetch options with Greeks
- `calculate_strategy(strategy_type, legs)` - Analyze multi-leg strategies
- `execute_trade(strategy, confirmation_token)` - Place orders

### Market Data
- `get_market_depth(symbol, levels)` - Level 2 order book
- `get_depth_analytics(symbol)` - Price impact analysis
- `get_index_quote(symbol)` - Index quotes (SPX, NDX, VIX)
- `get_index_options(symbol)` - Index options chains

### Crypto & Forex (Optional)
- `get_crypto_quote(symbol)` - Cryptocurrency quotes
- `analyze_crypto(symbol)` - Crypto technical analysis
- `get_fx_quote(pair)` - Forex quotes
- `analyze_fx_pair(pair)` - FX technical analysis

### News & Analysis
- `get_news(symbol, provider)` - Premium news feeds
- `get_vix_term_structure()` - VIX futures curve

## Usage Examples

In Claude Desktop:

```
"Show me the options chain for AAPL expiring next Friday"
"Calculate a bull call spread on SPY 450/455"
"Get Level 2 depth for TSLA"
"Show me SPX options near the money"
"What's the latest news on NVDA?"
```

## Safety Features

- **Mandatory Confirmation**: All trades require explicit confirmation
- **Max Loss Display**: Always shows maximum potential loss
- **Stop Loss Prompts**: Automatic prompts after fills
- **Position Limits**: Configurable maximum position sizes
- **Rate Limiting**: Prevents API overload

## Project Structure

```
SumpPump/
├── src/
│   ├── mcp/
│   │   └── server.py          # MCP server with tools
│   ├── core/                  # Infrastructure (NEW)
│   │   ├── exceptions.py      # Error hierarchy
│   │   ├── connection_monitor.py
│   │   ├── rate_limiter.py
│   │   └── settings.py
│   ├── modules/
│   │   ├── tws/               # TWS connection
│   │   ├── data/              # Market data modules
│   │   │   ├── depth_of_book.py
│   │   │   ├── indices.py
│   │   │   ├── crypto.py
│   │   │   └── forex.py
│   │   ├── strategies/        # Strategy calculations
│   │   └── risk/              # Risk management
│   └── models.py              # Data models
├── tests/                     # Test suite
├── .env.example              # Configuration template
└── CLAUDE.md                 # Context for Claude
```

## Development

### Running Tests
```bash
pytest tests/ -v
```

### Adding New Features
1. Create module in `src/modules/`
2. Add MCP tool in `src/mcp/server.py`
3. Update configuration in `src/config.py`
4. Add tests in `tests/`

## Troubleshooting

### Connection Issues
- Verify TWS is running and API is enabled
- Check port settings (7497 for live, 7496 for paper)
- Ensure Client ID is not in use

### Market Data Issues
- Verify market data subscriptions in IBKR
- Check market hours
- Confirm symbol validity

### Rate Limiting
- Reduce concurrent requests
- Check `MAX_MARKET_DATA_LINES` setting
- Monitor rate limit metrics in logs

## Requirements

- IBKR Account with appropriate permissions
- Market data subscriptions for desired feeds
- TWS API enabled (port 7497)
- Python packages: ib_async, fastmcp, pydantic

## License

MIT License - See LICENSE file for details

## Support

- Report issues: [GitHub Issues](https://github.com/yourusername/SumpPump/issues)
- Documentation: See CLAUDE.md for detailed context
- TWS API Docs: [IBKR API Documentation](https://interactivebrokers.github.io/)

## Disclaimer

This software is for educational purposes. Trading involves risk. Always verify orders before execution. The authors are not responsible for any financial losses.