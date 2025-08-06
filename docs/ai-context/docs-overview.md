# Documentation Overview - SumpPump

## Documentation Structure

### Tier 1: Foundation (Always Loaded)
- **CLAUDE.md**: Master AI context, coding standards, safety protocols
- **project-structure.md**: Technology stack, directory layout
- **docs-overview.md**: This file - documentation routing map

### Tier 2: Component Level
- **src/modules/tws/CONTEXT.md**: TWS connection patterns
- **src/modules/data/CONTEXT.md**: Data fetching and caching strategies
- **src/modules/strategies/CONTEXT.md**: Strategy implementation patterns
- **src/modules/risk/CONTEXT.md**: Risk management protocols
- **src/modules/execution/CONTEXT.md**: Order execution workflows

### Tier 3: Feature Level
- **src/mcp/tools/CONTEXT.md**: MCP tool specifications
- **src/modules/data/cache/CONTEXT.md**: Caching implementation
- **src/modules/strategies/verticals/CONTEXT.md**: Vertical spread specifics

## Documentation Routing

### For TWS Connection Issues
→ Load: `src/modules/tws/CONTEXT.md`
→ Topics: Connection, reconnection, market data subscriptions

### For Options Data
→ Load: `src/modules/data/CONTEXT.md`
→ Topics: Chain fetching, Greeks calculation, caching

### For Strategy Implementation
→ Load: `src/modules/strategies/CONTEXT.md`
→ Topics: Strategy patterns, P&L calculations, optimization

### For Risk Management
→ Load: `src/modules/risk/CONTEXT.md`
→ Topics: Position sizing, stop loss, margin validation

### For Trade Execution
→ Load: `src/modules/execution/CONTEXT.md`
→ Topics: Order building, confirmation flow, fill handling

## Quick Reference

| Task | Primary Docs | Secondary Docs |
|------|-------------|----------------|
| Add new MCP tool | `src/mcp/CONTEXT.md` | `CLAUDE.md` |
| Implement strategy | `src/modules/strategies/CONTEXT.md` | Strategy-specific tier 3 |
| Fix TWS connection | `src/modules/tws/CONTEXT.md` | `config.py` |
| Optimize caching | `src/modules/data/cache/CONTEXT.md` | `src/modules/data/CONTEXT.md` |

## Update Protocol

When modifying code:
1. Update relevant CONTEXT.md files immediately
2. Keep this overview synchronized
3. Ensure CLAUDE.md reflects any architectural changes
