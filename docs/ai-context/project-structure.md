# SumpPump Project Structure

## Technology Stack

### Core Technologies
- **Python 3.10+**: Primary language
- **ib_async**: Modern async framework for IBKR API (successor to ib_insync)
- **FastMCP**: Model Context Protocol server
- **asyncio**: Asynchronous runtime
- **TWS API**: Interactive Brokers trading interface

### Data & Analysis
- **pandas**: Options chain manipulation
- **numpy**: Mathematical computations
- **py_vollib**: Black-Scholes pricing
- **scipy**: Statistical functions

### Infrastructure
- **SQLite/Redis**: Session caching
- **loguru**: Advanced logging
- **pydantic**: Data validation
- **python-dotenv**: Environment management

## Directory Structure

```
SumpPump/
├── .claude/                    # Claude Code Development Kit
│   ├── commands/              # AI orchestration commands
│   ├── hooks/                 # Automation hooks
│   │   ├── config/           # Hook configuration
│   │   └── *.sh              # Hook scripts
│   └── settings.local.json   # Claude Code config
```

├── src/                        # Source code
│   ├── mcp/                  # MCP server implementation
│   │   ├── __init__.py
│   │   └── server.py         # Main MCP server entry
│   ├── modules/              # Core business logic
│   │   ├── tws/             # TWS connection management
│   │   │   ├── __init__.py
│   │   │   └── connection.py # Connection manager
│   │   ├── data/            # Market data handling
│   │   │   ├── __init__.py
│   │   │   ├── options_chain.py
│   │   │   ├── historical.py
│   │   │   └── cache.py
│   │   ├── analysis/        # Strategy analysis
│   │   │   ├── __init__.py
│   │   │   ├── probability.py
│   │   │   ├── greeks.py
│   │   │   └── backtesting.py
│   │   ├── strategies/      # Options strategies
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── verticals.py
│   │   │   ├── calendar.py
│   │   │   └── complex.py
│   │   ├── risk/           # Risk management
│   │   │   ├── __init__.py
│   │   │   ├── calculator.py
│   │   │   └── validator.py
│   │   └── execution/      # Order execution
│   │       ├── __init__.py
│   │       ├── orders.py
│   │       └── confirmation.py
│   ├── __init__.py
│   └── config.py             # Central configuration
│
├── docs/                      # Documentation
│   ├── ai-context/          # AI context files
│   │   ├── project-structure.md
│   │   ├── docs-overview.md
│   │   └── handoff.md
│   ├── open-issues/         # Issue tracking
│   └── specs/               # Feature specifications
│
├── config/                   # Configuration files
│   └── mcp_config.json      # MCP server config
│
├── cache/                    # Session data cache
│   └── session_data.db      # SQLite cache
│
├── logs/                     # Application logs
│   └── sump_pump.log        # Main log file
│
├── tests/                    # Test suite
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── CLAUDE.md                # Master AI context
├── README.md               # Project documentation
├── requirements.txt        # Python dependencies
├── pyproject.toml         # Project configuration
├── .env.example           # Environment template
└── .gitignore            # Git ignore rules
```

## Key Architecture Decisions

1. **Async-First**: All I/O operations use async/await
2. **MCP Protocol**: Standardized tool interface for Claude
3. **Safety Controls**: Mandatory confirmation for trades
4. **Session Isolation**: No data persistence between symbols
5. **Modular Design**: Clear separation of concerns

## Integration Points

- **TWS API**: Port 7497 (default TWS)
- **MCP Server**: Port 8765 (configurable)
- **Cache**: SQLite or Redis
- **Logs**: JSON format for structured logging
