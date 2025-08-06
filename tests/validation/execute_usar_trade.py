#!/usr/bin/env python3
"""
Execute USAR stock purchase: 1 share at $13.56 limit price.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.tws.connection import tws_connection
from loguru import logger

async def execute_usar_purchase():
    """Execute the USAR stock purchase."""
    
    logger.info("=== USAR STOCK PURCHASE ===")
    logger.info("Symbol: USAR")
    logger.info("Quantity: 1 share")
    logger.info("Action: BUY")
    logger.info("Order Type: LIMIT")
    logger.info("Limit Price: $13.56")
    logger.info("=" * 40)
    
    try:
        # Connect to TWS
        await tws_connection.connect()
        logger.info("✅ Connected to TWS")
        
        # Get account info first for validation
        account_info = tws_connection.get_account_info_sync()
        logger.info(f"Account Balance: ${account_info['net_liquidation']:,.2f}")
        logger.info(f"Available Funds: ${account_info['available_funds']:,.2f}")
        
        # Calculate trade cost
        trade_cost = 1 * 13.56  # 1 share * $13.56
        logger.info(f"Trade Cost: ${trade_cost:.2f}")
        
        if account_info['available_funds'] < trade_cost:
            logger.error(f"❌ Insufficient funds: Need ${trade_cost:.2f}, have ${account_info['available_funds']:,.2f}")
            return
            
        logger.info("✅ Sufficient funds available")
        
        # Confirmation prompt
        print(f"\n{'='*50}")
        print(f"TRADE CONFIRMATION REQUIRED")
        print(f"{'='*50}")
        print(f"Symbol: USAR")
        print(f"Action: BUY 1 share")
        print(f"Order Type: LIMIT")
        print(f"Limit Price: $13.56")
        print(f"Estimated Cost: ${trade_cost:.2f}")
        print(f"Account Balance: ${account_info['net_liquidation']:,.2f}")
        print(f"{'='*50}")
        
        # For safety, require explicit confirmation
        confirm = input("Type 'CONFIRMED' to execute this trade: ").strip()
        if confirm != 'CONFIRMED':
            logger.info("Trade cancelled - confirmation not provided")
            return
            
        logger.info("🚀 Executing trade...")
        
        # Place the order
        result = await tws_connection.place_stock_order(
            symbol='USAR',
            quantity=1,
            action='BUY',
            order_type='LMT',
            limit_price=13.56
        )
        
        logger.info("✅ Trade executed successfully!")
        logger.info(f"Order ID: {result['order_id']}")
        logger.info(f"Status: {result['status']}")
        logger.info(f"Symbol: {result['symbol']}")
        logger.info(f"Quantity: {result['quantity']}")
        logger.info(f"Action: {result['action']}")
        logger.info(f"Limit Price: ${result['limit_price']}")
        
        print(f"\n{'='*50}")
        print(f"TRADE EXECUTION COMPLETE")
        print(f"{'='*50}")
        print(f"Order ID: {result['order_id']}")
        print(f"Status: {result['status']}")
        print(f"You bought 1 share of USAR at $13.56 limit price")
        print(f"{'='*50}\n")
        
    except Exception as e:
        logger.error(f"❌ Trade execution failed: {e}")
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await tws_connection.disconnect()
        logger.info("Disconnected from TWS")

if __name__ == "__main__":
    asyncio.run(execute_usar_purchase())