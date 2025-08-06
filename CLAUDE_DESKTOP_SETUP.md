# Claude Desktop Setup for SumpPump

## Quick Setup Instructions

### 1. Open Claude Desktop Settings
- Open Claude Desktop
- Go to Settings (gear icon)
- Navigate to "Developer" or "MCP Servers" section

### 2. Add SumpPump MCP Server

Add this configuration to your Claude Desktop settings:

```json
{
  "mcpServers": {
    "sump-pump": {
      "command": "/Users/schmoll/Desktop/SumpPump/run_mcp_server.sh",
      "args": []
    }
  }
}
```

Or if you need to specify the Python path directly:

```json
{
  "mcpServers": {
    "sump-pump": {
      "command": "/Users/schmoll/Desktop/SumpPump/venv/bin/python",
      "args": ["/Users/schmoll/Desktop/SumpPump/src/mcp/server.py"]
    }
  }
}
```

### 3. Restart Claude Desktop
After adding the configuration, restart Claude Desktop for the changes to take effect.

### 4. Verify Connection
Once restarted, you should see "sump-pump" in the MCP servers list. 
Test by asking Claude: "Can you fetch the options chain for SPY?"

## Testing the Integration

### Basic Test Commands

1. **Test Connection**:
   "Check if you can connect to my trading system"

2. **Fetch Options Chain**:
   "Get the options chain for AAPL"

3. **Calculate Strategy** (Level 2 compliant):
   "Calculate a bull call spread for SPY with strikes 630/635"

4. **Check Account** (if needed):
   "What's my current account balance?"

## Important Safety Notes

- **Client ID**: Currently using Client ID 1. If you get connection errors, make sure no other app is using ID 1
- **TWS Must Be Running**: Make sure TWS is logged in and running
- **Port 7497**: This is the live trading port
- **Confirmation Required**: All trades require "USER_CONFIRMED" token

## Troubleshooting

### If MCP Server Doesn't Connect:
1. Check TWS is running and logged in
2. Verify API is enabled in TWS (File → Global Configuration → API → Settings)
3. Check "Enable ActiveX and Socket Clients" is checked
4. Add 127.0.0.1 to Trusted IPs
5. Make sure port 7497 is the configured port

### If Claude Can't See the Server:
1. Restart Claude Desktop after adding configuration
2. Check the logs in Claude Desktop developer console
3. Try running the server manually first:
   ```bash
   cd /Users/schmoll/Desktop/SumpPump
   source venv/bin/activate
   python src/mcp/server.py
   ```

### Client ID Conflict:
If you get "Client ID already in use" error, you can change it in `.env`:
```
TWS_CLIENT_ID=2  # or any unused number
```

## Your Level 2 Trading Commands

### Allowed Strategies:
- "Buy 10 AAPL calls at 170 strike"
- "Create a bull call spread for SPY 630/635"
- "Buy a bear put spread for QQQ 480/475"
- "Calculate a long straddle for TSLA at 250"

### NOT Allowed (Level 3+ Required):
- ❌ "Sell cash-secured puts"
- ❌ "Create a bull put spread" (credit spread)
- ❌ "Set up an iron condor" (credit version)
- ❌ "Create a calendar spread"

## Live Trading Checklist

✅ TWS is logged in and running
✅ MCP server is registered in Claude Desktop
✅ You understand Level 2 restrictions
✅ You know confirmation is required for all trades
✅ Stop losses will be prompted after fills

Ready to trade! Ask Claude to fetch an options chain to start.