#!/bin/bash
# SumpPump Trading Assistant Quick Launcher
# Save this as ~/.sumppump/launch.sh and run: chmod +x ~/.sumppump/launch.sh
# Then you can start trading with: ~/.sumppump/launch.sh

echo "╔════════════════════════════════════════════════════════╗"
echo "║           Starting SumpPump Trading Assistant           ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check if TWS is running
if ! pgrep -x "Trader Workstation" > /dev/null && ! pgrep -x "java" > /dev/null
then
    echo "⚠️  WARNING: TWS doesn't appear to be running!"
    echo "Please start TWS first and enable API access."
    echo ""
fi

# Navigate to project
cd /Users/schmoll/Desktop/SumpPump

# Activate virtual environment
source venv/bin/activate

# Start the MCP server in background
echo "🚀 Starting MCP server..."
python src/mcp/server.py &
MCP_PID=$!

echo "✅ MCP Server running (PID: $MCP_PID)"
echo ""

# Display the trading prompt
echo "═══════════════════════════════════════════════════════════"
echo "📋 COPY THIS PROMPT INTO CLAUDE DESKTOP:"
echo "═══════════════════════════════════════════════════════════"
echo ""
cat TRADING_START.txt
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# Show safety reminder
echo "⚠️  SAFETY REMINDERS:"
echo "  • This is LIVE TRADING (real money)"
echo "  • Always check max loss before trading"
echo "  • Confirm with 'USER_CONFIRMED' only when ready"
echo "  • Set stop losses after every fill"
echo ""

echo "📊 Claude Desktop is ready for trading!"
echo "💡 To stop: Press Ctrl+C or run: kill $MCP_PID"
echo ""

# Keep script running
wait $MCP_PID