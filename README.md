# SumpPump - IBKR Options Trading Assistant

An MCP (Model Context Protocol) server that enables Claude Desktop to act as a conversational options trading assistant for Interactive Brokers TWS, focused on level 2 options strategies with real-time data access and risk management.

## 🚀 Quick Start

1. **Prerequisites**
   - Python 3.10+
   - Interactive Brokers TWS (not IB Gateway)
   - Claude Desktop with MCP support
   - Active IBKR account with options trading permissions

2. **Installation**
   ```bash
   cd /Users/schmoll/Desktop/SumpPump
   python -m venv venv
   source venv/bin/activate  # On macOS
   pip install -r requirements.txt
   ```

3. **TWS Configuration**
   - Enable API connections in TWS (File → Global Configuration → API → Settings)
   - Set Socket port: 7497 (default for TWS)
   - Add 127.0.0.1 to Trusted IPs
   - Check "Download open orders on connection"
   - Increase memory allocation to 4096 MB minimum

4. **Run MCP Server**
   ```bash
   python src/mcp/server.py
   ```

## 📂 Project Structure

```
SumpPump/
├── .claude/              # Claude Code Development Kit integration
├── src/
│   ├── mcp/             # MCP server implementation
│   └── modules/         # Core trading modules
│       ├── tws/         # TWS connection management
│       ├── data/        # Market data and options chains
│       ├── analysis/    # Strategy analysis tools
│       ├── strategies/  # Options strategy templates
│       ├── risk/        # Risk management
│       └── execution/   # Order execution
├── config/              # Configuration files
├── cache/               # Session data caching
├── logs/                # Application logs
└── tests/               # Test suite
```

## 🔧 Architecture

Built on:
- **ib_async**: Modern async framework for IBKR API
- **FastMCP**: High-performance MCP server implementation
- **asyncio**: Asynchronous I/O for real-time data handling

## 🛡️ Safety Features

- **No automatic trading** without explicit confirmation
- **Full strategy analysis** before execution
- **Max risk calculation** on every trade
- **Stop loss prompts** after fills
- **Clear separation** between analysis and execution

## 📊 Supported Strategies (IBKR Level 2)

**Available with Level 2 Permissions:**
- Long Calls & Puts
- Bull Call Spreads (debit)
- Bear Put Spreads (debit)
- Covered Calls
- Protective Puts & Calls
- Collars
- Long Straddles & Strangles
- Long Iron Condors

**NOT Available (Need Level 3+):**
- Credit Spreads (bear call, bull put)
- Cash-Secured Puts
- Calendar/Diagonal Spreads
- Butterflies
- Naked Short Options

## 🔌 MCP Tools Available

- `get_options_chain()` - Fetch full options chain with Greeks
- `calculate_strategy()` - Analyze P&L for strategies
- `execute_trade()` - Execute with mandatory confirmation
- `set_stop_loss()` - Set protective stops
- `get_market_data()` - Real-time quotes and statistics

## 📚 Documentation

See `/docs` for detailed documentation on:
- API integration patterns
- Strategy implementation
- Risk management protocols
- MCP tool specifications

## ⚠️ Important Notes

- **LIVE TRADING ONLY** - No paper trading mode
- Requires active market data subscriptions
- All trades require explicit confirmation
- Session data cleared between symbol discussions
