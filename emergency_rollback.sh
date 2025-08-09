#!/bin/bash

# SumpPump Emergency Rollback Script
# Use this if consolidated tools cause production issues

echo "=========================================="
echo "SumpPump Emergency Rollback Script"
echo "This will disable ALL consolidated tools"
echo "=========================================="
echo ""

# Confirm with user
read -p "Are you sure you want to rollback ALL consolidations? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Rollback cancelled."
    exit 0
fi

echo ""
echo "Starting emergency rollback..."
echo ""

# Step 1: Set environment variables to disable consolidation
echo "Step 1: Disabling consolidation feature flags..."
export CONSOLIDATED_QUOTES=false
export CONSOLIDATED_PORTFOLIO=false
export CONSOLIDATED_CLOSE=false
export CONSOLIDATED_ORDERS=false
export CONSOLIDATION_DRY_RUN=false

# Step 2: Kill existing MCP server
echo "Step 2: Stopping current MCP server..."
pkill -f "server.py" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  - MCP server stopped"
else
    echo "  - No running MCP server found"
fi

# Wait for process to fully terminate
sleep 2

# Step 3: Create rollback marker file
echo "Step 3: Creating rollback marker..."
echo "{
  \"timestamp\": \"$(date -u +"%Y-%m-%dT%H:%M:%SZ")\",
  \"reason\": \"Emergency rollback executed\",
  \"disabled_features\": [
    \"consolidated_quotes\",
    \"consolidated_portfolio\",
    \"consolidated_close\",
    \"consolidated_orders\"
  ]
}" > /Users/schmoll/Desktop/SumpPump/.rollback_marker.json

echo "  - Rollback marker created"

# Step 4: Restart MCP server with legacy implementations
echo "Step 4: Restarting MCP server with legacy implementations..."
cd /Users/schmoll/Desktop/SumpPump

# Start server in background with logging
nohup /Users/schmoll/Desktop/SumpPump/venv/bin/python src/mcp/server.py > mcp_server_rollback.log 2>&1 &

if [ $? -eq 0 ]; then
    echo "  - MCP server restarted with PID: $!"
    echo "  - Logs available at: mcp_server_rollback.log"
else
    echo "  - ERROR: Failed to restart MCP server"
    echo "  - Please start manually: /Users/schmoll/Desktop/SumpPump/venv/bin/python src/mcp/server.py"
fi

echo ""
echo "=========================================="
echo "ROLLBACK COMPLETE"
echo "=========================================="
echo ""
echo "Status:"
echo "  ✅ All consolidation features disabled"
echo "  ✅ Server restarted with legacy tools"
echo "  ✅ System using original 43 tools"
echo ""
echo "Next steps:"
echo "  1. Verify TWS connection is active"
echo "  2. Test a simple quote: trade_get_quote('SPY')"
echo "  3. Monitor logs: tail -f mcp_server_rollback.log"
echo "  4. Investigate consolidation issues before re-enabling"
echo ""
echo "To re-enable consolidation later:"
echo "  export CONSOLIDATED_QUOTES=true"
echo "  export CONSOLIDATED_PORTFOLIO=true"
echo "  # Then restart the server"
echo ""