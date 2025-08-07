# SumpPump Quick Start Guide

## Prerequisites Checklist

- [ ] Interactive Brokers account with Level 2 options permissions
- [ ] TWS installed (not IB Gateway)
- [ ] Python 3.10 or higher
- [ ] Claude Desktop with MCP support

## Step 1: Clone and Install

```bash
git clone https://github.com/yourusername/SumpPump.git
cd SumpPump
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 2: Configure TWS

1. **Start TWS** and log in with LIVE account
2. Go to **File → Global Configuration → API → Settings**
3. Apply these settings:
   ```
   ✅ Enable ActiveX and Socket Clients
   ✅ Download open orders on connection
   ❌ Read-Only API (must be OFF)
   Socket port: 7497
   Trusted IPs: 127.0.0.1
   ```
4. Click **Apply** then **OK**
5. **Restart TWS**

## Step 3: Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sump-pump": {
      "command": "/full/path/to/SumpPump/venv/bin/python",
      "args": ["/full/path/to/SumpPump/src/mcp/server.py"]
    }
  }
}
```

## Step 4: Create .env File

Create `.env` in SumpPump root:

```bash
TWS_HOST=127.0.0.1
TWS_PORT=7497
TWS_CLIENT_ID=5
REQUIRE_CONFIRMATION=true
```

## Step 5: Test Connection

```bash
# Test TWS connection
python -c "from ib_async import IB; ib=IB(); ib.connect('127.0.0.1', 7497, 5); print('✅ Connected'); ib.disconnect()"
```

## Step 6: Start Trading

1. Restart Claude Desktop
2. In Claude Desktop, try: "Fetch SPY options"

## Troubleshooting

### "Cannot connect to TWS"
- Ensure TWS is running and logged in
- Check API settings were applied
- Restart TWS after configuration

### "MCP server not found"
- Check paths in claude_desktop_config.json
- Restart Claude Desktop

### "No data during market hours"
- Options data requires market hours (9:30 AM - 4:00 PM ET)
- Ensure you have market data subscriptions

## Safety Reminders

⚠️ **This executes REAL trades**
- All trades require confirmation
- Start with small positions
- Monitor your risk limits