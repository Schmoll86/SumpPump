#!/usr/bin/env python3
"""
Test script for TWS connection.
Verifies that the connection module works correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.tws.connection import tws_connection
from loguru import logger


async def test_connection():
    """Test basic TWS connection."""
    logger.info("Testing TWS connection...")
    
    try:
        # Test connection
        await tws_connection.connect()
        logger.success("✓ Connected to TWS successfully!")
        
        # Test account info
        logger.info("Fetching account information...")
        account_info = await tws_connection.get_account_info()
        
        if account_info:
            logger.success(f"✓ Account ID: {account_info.get('account_id', 'N/A')}")
            logger.success(f"✓ Net Liquidation: ${account_info.get('net_liquidation', 0):,.2f}")
            logger.success(f"✓ Available Funds: ${account_info.get('available_funds', 0):,.2f}")
            logger.success(f"✓ Positions: {len(account_info.get('positions', []))}")
            logger.success(f"✓ Open Orders: {len(account_info.get('open_orders', []))}")
        
        # Disconnect
        await tws_connection.disconnect()
        logger.success("✓ Disconnected successfully!")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Connection test failed: {e}")
        logger.error("Make sure TWS is running and API is enabled on port 7497")
        logger.error("Check that 127.0.0.1 is in Trusted IPs in TWS API settings")
        return False


async def test_options_chain():
    """Test options chain fetching."""
    logger.info("\nTesting options chain fetch...")
    
    try:
        async with tws_connection.session() as tws:
            # Test with a popular symbol
            symbol = "SPY"
            logger.info(f"Fetching options chain for {symbol}...")
            
            options = await tws.get_options_chain(symbol)
            
            if options:
                logger.success(f"✓ Fetched {len(options)} option contracts")
                
                # Show sample data
                if len(options) > 0:
                    sample = options[0]
                    logger.info(f"Sample option: {sample.symbol} {sample.expiry.strftime('%Y-%m-%d')} "
                              f"{sample.strike} {sample.right.value}")
                    logger.info(f"  Bid: ${sample.bid:.2f}, Ask: ${sample.ask:.2f}")
                    logger.info(f"  IV: {sample.iv:.2%}")
                    logger.info(f"  Delta: {sample.greeks.delta:.3f}")
            else:
                logger.warning("No options data returned")
                
        return True
        
    except Exception as e:
        logger.error(f"✗ Options chain test failed: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("SumpPump TWS Connection Test")
    logger.info("=" * 60)
    
    # Test basic connection
    connection_ok = await test_connection()
    
    if connection_ok:
        # Test options chain only if connection works
        await test_options_chain()
    
    logger.info("=" * 60)
    logger.info("Test complete!")
    

if __name__ == "__main__":
    asyncio.run(main())