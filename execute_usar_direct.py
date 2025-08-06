#!/usr/bin/env python3
"""
Execute USAR stock purchase directly using TWS API.
Bypasses the async context issues.
"""

import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from ib_async import IB, Stock, LimitOrder
from src.config import config
from loguru import logger

def execute_usar_purchase_direct():
    """Execute the USAR stock purchase directly."""
    
    logger.info("=== USAR STOCK PURCHASE (DIRECT) ===")
    logger.info("Symbol: USAR")
    logger.info("Quantity: 1 share")
    logger.info("Action: BUY")
    logger.info("Order Type: LIMIT")
    logger.info("Limit Price: $13.56")
    logger.info("=" * 40)
    
    # Create IB instance
    ib = IB()
    
    try:
        # Connect
        logger.info("Connecting to TWS...")
        ib.connect(
            host=config.tws.host,
            port=config.tws.port,
            clientId=config.tws.client_id,
            timeout=config.tws.timeout,
            readonly=config.tws.readonly
        )
        
        if not ib.isConnected():
            logger.error("❌ Failed to connect to TWS")
            return
            
        logger.info("✅ Connected to TWS")
        
        # Get account summary for validation
        logger.info("Fetching account information...")
        ib.reqAccountSummary()
        time.sleep(2)  # Wait for data
        
        account_values = ib.accountSummary()
        net_liq = 0.0
        available_funds = 0.0
        
        for av in account_values:
            if av.currency == 'USD':
                if av.tag == 'NetLiquidation':
                    net_liq = float(av.value)
                elif av.tag == 'AvailableFunds':
                    available_funds = float(av.value)
        
        logger.info(f"Account Balance: ${net_liq:,.2f}")
        logger.info(f"Available Funds: ${available_funds:,.2f}")
        
        # Calculate trade cost
        trade_cost = 1 * 13.56
        logger.info(f"Trade Cost: ${trade_cost:.2f}")
        
        if available_funds < trade_cost:
            logger.error(f"❌ Insufficient funds: Need ${trade_cost:.2f}, have ${available_funds:,.2f}")
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
        print(f"Account Balance: ${net_liq:,.2f}")
        print(f"Available Funds: ${available_funds:,.2f}")
        print(f"{'='*50}")
        
        # For safety, require explicit confirmation
        confirm = input("Type 'CONFIRMED' to execute this trade: ").strip()
        if confirm != 'CONFIRMED':
            logger.info("Trade cancelled - confirmation not provided")
            return
            
        logger.info("🚀 Executing trade...")
        
        # Create USAR stock contract
        usar_stock = Stock('USAR', 'SMART', 'USD')
        ib.qualifyContracts(usar_stock)
        logger.info(f"✅ Contract qualified: {usar_stock}")
        
        # Create limit order
        order = LimitOrder('BUY', 1, 13.56)
        logger.info(f"✅ Order created: BUY 1 USAR @ $13.56 limit")
        
        # Place the order
        trade = ib.placeOrder(usar_stock, order)
        logger.info(f"✅ Order placed with ID: {trade.order.orderId}")
        
        # Wait for order acknowledgment
        time.sleep(3)
        
        # Get order status
        status = trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Unknown'
        
        logger.info("✅ Trade executed successfully!")
        logger.info(f"Order ID: {trade.order.orderId}")
        logger.info(f"Status: {status}")
        
        print(f"\n{'='*50}")
        print(f"TRADE EXECUTION COMPLETE")
        print(f"{'='*50}")
        print(f"Order ID: {trade.order.orderId}")
        print(f"Status: {status}")
        print(f"You placed a BUY order for 1 share of USAR at $13.56 limit price")
        print(f"Check your TWS or IBKR mobile app to monitor the order status")
        print(f"{'='*50}\n")
        
    except Exception as e:
        logger.error(f"❌ Trade execution failed: {e}")
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if ib.isConnected():
            ib.disconnect()
            logger.info("Disconnected from TWS")

if __name__ == "__main__":
    execute_usar_purchase_direct()