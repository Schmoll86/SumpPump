#!/usr/bin/env python3
"""
Test script to validate calculate_strategy function fixes.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.tws.connection import tws_connection
from src.modules.strategies.level2_strategies import create_bull_call_spread
from src.models import OptionContract, OptionRight, Greeks, OptionLeg, OrderAction
from datetime import datetime, timedelta
from loguru import logger

def create_test_option_contract(symbol: str, strike: float, right: OptionRight, price: float) -> OptionContract:
    """Create a test option contract."""
    return OptionContract(
        symbol=symbol,
        strike=strike,
        expiry=datetime.now() + timedelta(days=30),  # 30 days out
        right=right,
        bid=price - 0.05,
        ask=price + 0.05,
        last=price,
        volume=100,
        open_interest=1000,
        iv=0.25,
        greeks=Greeks(delta=0.5, gamma=0.05, theta=-0.02, vega=0.15),
        underlying_price=100.0
    )

async def test_strategy_calculation():
    """Test the strategy calculation workflow."""
    
    logger.info("=== STRATEGY CALCULATION TEST ===")
    
    try:
        # Create test option contracts for SPY bull call spread
        long_call = create_test_option_contract("SPY", 630, OptionRight.CALL, 5.00)
        short_call = create_test_option_contract("SPY", 635, OptionRight.CALL, 3.00)
        
        logger.info("Created test option contracts:")
        logger.info(f"Long Call: SPY {long_call.strike}C @ ${long_call.last}")
        logger.info(f"Short Call: SPY {short_call.strike}C @ ${short_call.last}")
        
        # Create bull call spread strategy
        logger.info("Creating bull call spread strategy...")
        strategy = await create_bull_call_spread(long_call, short_call, 1)
        
        logger.info(f"Strategy created: {strategy.name}")
        logger.info(f"Strategy type: {strategy.strategy_type}")
        logger.info(f"Number of legs: {len(strategy.legs)}")
        
        # Test all the methods that were causing issues
        logger.info("Testing strategy calculation methods...")
        
        max_profit = await strategy.calculate_max_profit()
        logger.info(f"✅ Max profit: ${max_profit:.2f}")
        
        max_loss = await strategy.calculate_max_loss()
        logger.info(f"✅ Max loss: ${max_loss:.2f}")
        
        breakevens = await strategy.get_breakeven_points()
        logger.info(f"✅ Breakeven points: {breakevens}")
        
        probability = await strategy.calculate_probability_of_profit()
        logger.info(f"✅ Probability of profit: {probability:.1%}")
        
        net_debit_credit = await strategy.calculate_net_debit_credit()
        logger.info(f"✅ Net debit/credit: ${net_debit_credit:.2f}")
        
        greeks = await strategy.aggregate_greeks()
        logger.info(f"✅ Aggregated Greeks: Delta={greeks.delta:.3f}, Gamma={greeks.gamma:.3f}")
        
        # Test creating a complete strategy object
        strategy_obj = await strategy.create_strategy_object()
        logger.info(f"✅ Strategy object created: {strategy_obj.name}")
        
        logger.info("🎉 All strategy calculation methods working correctly!")
        
        return {
            'success': True,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'breakevens': breakevens,
            'probability': probability,
            'net_debit_credit': net_debit_credit,
            'greeks': greeks
        }
        
    except Exception as e:
        logger.error(f"❌ Strategy calculation test failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }

if __name__ == "__main__":
    result = asyncio.run(test_strategy_calculation())
    if result['success']:
        print("\n✅ STRATEGY CALCULATION TEST PASSED")
        print(f"Net debit: ${abs(result['net_debit_credit']):.2f}")
        print(f"Max profit: ${result['max_profit']:.2f}")
        print(f"Max loss: ${result['max_loss']:.2f}")
        print(f"Breakeven: {result['breakevens']}")
    else:
        print(f"\n❌ TEST FAILED: {result['error']}")
        sys.exit(1)