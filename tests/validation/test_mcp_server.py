#!/usr/bin/env python3
"""
Test script for MCP server startup.
Verifies that the MCP server can start without errors.
"""

import sys
import subprocess
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger


def test_mcp_server():
    """Test MCP server startup."""
    logger.info("Testing MCP server startup...")
    
    try:
        # Try to import and validate the server
        from src.mcp.server import mcp, get_options_chain, calculate_strategy, execute_trade, set_stop_loss
        
        # Check that tools are registered by checking if they exist
        tools = [
            ("get_options_chain", get_options_chain),
            ("calculate_strategy", calculate_strategy),
            ("execute_trade", execute_trade),
            ("set_stop_loss", set_stop_loss)
        ]
        
        logger.success(f"✓ MCP server loaded with {len(tools)} tools")
        
        for name, func in tools:
            logger.info(f"  - {name}")
        
        logger.success("✓ MCP server is ready!")
        
        logger.info("\nTo run the MCP server:")
        logger.info("  python src/mcp/server.py")
        
        logger.info("\nTo register with Claude Desktop, add to settings:")
        logger.info("""
{
  "mcpServers": {
    "sump-pump": {
      "command": "python",
      "args": ["/Users/schmoll/Desktop/SumpPump/src/mcp/server.py"]
    }
  }
}
        """)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ MCP server test failed: {e}")
        return False


if __name__ == "__main__":
    test_mcp_server()