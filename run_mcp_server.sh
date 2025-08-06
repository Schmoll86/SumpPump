#!/bin/bash
# Launch script for SumpPump MCP Server

# Navigate to project directory
cd /Users/schmoll/Desktop/SumpPump

# Activate virtual environment
source venv/bin/activate

# Run the MCP server
exec python src/mcp/server.py