#!/usr/bin/env python3
"""
Diagnostic tool for TWS connection and account issues.
Run this to test the connection and identify account problems.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.tws.connection import tws_connection
from src.config import config
from loguru import logger


async def diagnose_tws():
    """Comprehensive TWS connection diagnostics."""
    
    logger.info("=" * 60)
    logger.info("TWS CONNECTION DIAGNOSTICS")
    logger.info("=" * 60)
    
    try:
        # 1. Test basic connection
        logger.info("1. Testing basic TWS connection...")
        await tws_connection.connect()
        
        if tws_connection.ib.isConnected():
            logger.info("✅ TWS connected successfully")
            logger.info(f"   Host: {config.tws.host}:{config.tws.port}")
            logger.info(f"   Client ID: {config.tws.client_id}")
        else:
            logger.error("❌ TWS not connected")
            return
            
        # 2. Test managed accounts
        logger.info("\n2. Checking managed accounts...")
        try:
            managed_accounts = tws_connection.ib.managedAccounts()
            logger.info(f"✅ Managed accounts: {managed_accounts}")
            if not managed_accounts:
                logger.warning("⚠️  No managed accounts found")
        except Exception as e:
            logger.error(f"❌ Error getting managed accounts: {e}")
            
        # 3. Test account configuration
        logger.info("\n3. Checking account configuration...")
        logger.info(f"   Configured account: '{config.tws.account}'")
        if not config.tws.account or config.tws.account.strip() == "":
            logger.warning("⚠️  No account ID configured in .env")
        else:
            logger.info(f"✅ Account ID configured: {config.tws.account}")
            
        # 4. Test account summary
        logger.info("\n4. Testing account summary retrieval...")
        try:
            account_info = tws_connection.get_account_info_sync()
            logger.info("Account Information Retrieved:")
            logger.info(f"   Account ID: {account_info.get('account_id', 'Unknown')}")
            logger.info(f"   Net Liquidation: ${account_info.get('net_liquidation', 0):,.2f}")
            logger.info(f"   Available Funds: ${account_info.get('available_funds', 0):,.2f}")
            logger.info(f"   Buying Power: ${account_info.get('buying_power', 0):,.2f}")
            logger.info(f"   Positions: {len(account_info.get('positions', []))}")
            logger.info(f"   Open Orders: {len(account_info.get('open_orders', []))}")
            
            if account_info.get('net_liquidation', 0) > 0:
                logger.info("✅ Account data looks good")
            else:
                logger.error("❌ Account balance is $0 - this indicates a connection issue")
                
        except Exception as e:
            logger.error(f"❌ Error getting account info: {e}")
            
        # 5. Test simple market data
        logger.info("\n5. Testing market data access...")
        try:
            from ib_async import Stock
            spy = Stock('SPY', 'SMART', 'USD')
            await tws_connection.ib.qualifyContractsAsync(spy)
            ticker = tws_connection.ib.reqMktData(spy, '', False, False)
            await asyncio.sleep(2)
            
            if ticker.last and ticker.last > 0:
                logger.info(f"✅ Market data working: SPY = ${ticker.last}")
            else:
                logger.warning("⚠️  Market data may not be working")
                
            tws_connection.ib.cancelMktData(spy)
            
        except Exception as e:
            logger.error(f"❌ Error testing market data: {e}")
            
        # 6. Recommendations
        logger.info("\n" + "=" * 60)
        logger.info("RECOMMENDATIONS")
        logger.info("=" * 60)
        
        if not managed_accounts:
            logger.info("🔧 No managed accounts found:")
            logger.info("   - Make sure you're logged into TWS")
            logger.info("   - Check TWS API settings (Enable ActiveX and Socket Clients)")
            logger.info("   - Verify TWS is running and connected to IBKR")
            
        elif account_info.get('net_liquidation', 0) == 0:
            logger.info("🔧 Account balance is $0:")
            logger.info("   - Try changing TWS_CLIENT_ID in .env to a different number")
            logger.info("   - Make sure no other applications are using the same client ID")
            logger.info("   - Check TWS Global Configuration → API → Settings")
            logger.info("   - Verify 'Download open orders on connection' is enabled")
            
        else:
            logger.info("🎉 Everything looks good! SumpPump should work properly.")
            
    except Exception as e:
        logger.error(f"❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await tws_connection.disconnect()
        logger.info("\n✅ Disconnected from TWS")


if __name__ == "__main__":
    logger.info("SumpPump TWS Diagnostics Tool")
    logger.info(f"Config: {config.tws.host}:{config.tws.port} (Client ID: {config.tws.client_id})")
    
    asyncio.run(diagnose_tws())