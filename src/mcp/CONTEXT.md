# MCP Server Module Context

## Purpose
Provides the Model Context Protocol interface for Claude Desktop integration.

## Architecture
```
Claude Desktop ↔ MCP Protocol ↔ FastMCP Server ↔ Business Modules ↔ TWS API
```

## Available Tools
1. **get_options_chain**: Fetch options with Greeks
2. **calculate_strategy**: Analyze strategy P&L
3. **execute_trade**: Place orders (confirmation required)
4. **set_stop_loss**: Protective order management

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