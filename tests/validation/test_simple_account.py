#!/usr/bin/env python3
"""
Simple synchronous test for TWS account info without event loop conflicts.
"""
import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from ib_async import IB
from src.config import config
from loguru import logger

def test_account_sync():
    """Test account info retrieval synchronously."""
    
    logger.info("=== SIMPLE ACCOUNT TEST ===")
    
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
        
        if ib.isConnected():
            logger.info("✅ Connected successfully")
            
            # Get managed accounts
            managed_accounts = ib.managedAccounts()
            logger.info(f"Managed accounts: {managed_accounts}")
            
            # Request account summary
            logger.info("Requesting account summary...")
            ib.reqAccountSummary()
            time.sleep(3)  # Wait for data
            
            account_values = ib.accountSummary()
            logger.info(f"Retrieved {len(account_values)} account summary items")
            
            # Parse values
            net_liq = 0.0
            available_funds = 0.0
            buying_power = 0.0
            
            for av in account_values:
                logger.info(f"Account value: {av.tag} = {av.value} ({av.currency})")
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    net_liq = float(av.value)
                elif av.tag == 'AvailableFunds' and av.currency == 'USD':
                    available_funds = float(av.value)
                elif av.tag == 'BuyingPower' and av.currency == 'USD':
                    buying_power = float(av.value)
            
            logger.info(f"ACCOUNT SUMMARY:")
            logger.info(f"  Net Liquidation: ${net_liq:,.2f}")
            logger.info(f"  Available Funds: ${available_funds:,.2f}")
            logger.info(f"  Buying Power: ${buying_power:,.2f}")
            
            if net_liq > 0:
                logger.info("✅ Account balance looks good!")
            else:
                logger.error("❌ Account balance is $0 - connection issue")
                
        else:
            logger.error("❌ Failed to connect")
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()
            logger.info("Disconnected")

if __name__ == "__main__":
    test_account_sync()