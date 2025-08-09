#!/usr/bin/env python3
"""
Comprehensive Testing Script for Tool Consolidation
Run this before deploying consolidated tools to production
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ConsolidationValidator:
    """Validate consolidated tools match legacy behavior."""
    
    def __init__(self):
        self.results = {
            'passed': [],
            'failed': [],
            'warnings': [],
            'timestamp': datetime.now().isoformat()
        }
    
    async def validate_quote_tools(self) -> Dict[str, Any]:
        """Validate quote tool consolidation."""
        logger.info("=" * 60)
        logger.info("VALIDATING QUOTE TOOL CONSOLIDATION")
        logger.info("=" * 60)
        
        test_results = []
        
        # Test 1: Single stock quote
        logger.info("\nTest 1: Single stock quote (SPY)")
        try:
            # Import both implementations
            from src.mcp.server import get_quote as legacy_get_quote
            from src.mcp.consolidated_tools import BackwardCompatibilityAliases
            
            # Get legacy result
            legacy_result = await legacy_get_quote('SPY', 'STK')
            
            # Get consolidated result
            consolidated_result = await BackwardCompatibilityAliases.trade_get_quote('SPY', 'STK')
            
            # Compare key fields
            match = self._compare_quotes(legacy_result, consolidated_result)
            
            test_results.append({
                'test': 'Single stock quote',
                'passed': match,
                'legacy_keys': list(legacy_result.keys()) if isinstance(legacy_result, dict) else None,
                'consolidated_keys': list(consolidated_result.keys()) if isinstance(consolidated_result, dict) else None
            })
            
            if match:
                logger.info("✅ Single stock quote test PASSED")
                self.results['passed'].append('quote_single_stock')
            else:
                logger.error("❌ Single stock quote test FAILED")
                self.results['failed'].append('quote_single_stock')
                
        except Exception as e:
            logger.error(f"❌ Single stock quote test ERROR: {e}")
            self.results['failed'].append('quote_single_stock')
            test_results.append({
                'test': 'Single stock quote',
                'passed': False,
                'error': str(e)
            })
        
        # Test 2: Multiple stock quotes (watchlist)
        logger.info("\nTest 2: Multiple stock quotes (watchlist)")
        try:
            from src.mcp.server import get_watchlist_quotes as legacy_watchlist
            
            symbols = ['SPY', 'QQQ', 'IWM']
            
            # Get legacy result
            legacy_result = await legacy_watchlist(symbols)
            
            # Get consolidated result
            consolidated_result = await BackwardCompatibilityAliases.trade_get_watchlist_quotes(symbols)
            
            # Compare structures
            match = (
                legacy_result.get('status') == consolidated_result.get('status') and
                len(legacy_result.get('quotes', [])) == len(consolidated_result.get('quotes', []))
            )
            
            test_results.append({
                'test': 'Multiple stock quotes',
                'passed': match,
                'symbols_count': len(symbols),
                'legacy_quotes': len(legacy_result.get('quotes', [])),
                'consolidated_quotes': len(consolidated_result.get('quotes', []))
            })
            
            if match:
                logger.info("✅ Multiple stock quotes test PASSED")
                self.results['passed'].append('quote_watchlist')
            else:
                logger.error("❌ Multiple stock quotes test FAILED")
                self.results['failed'].append('quote_watchlist')
                
        except Exception as e:
            logger.error(f"❌ Multiple stock quotes test ERROR: {e}")
            self.results['failed'].append('quote_watchlist')
            test_results.append({
                'test': 'Multiple stock quotes',
                'passed': False,
                'error': str(e)
            })
        
        return {
            'category': 'Quote Tools',
            'tests': test_results,
            'summary': {
                'total': len(test_results),
                'passed': sum(1 for t in test_results if t.get('passed')),
                'failed': sum(1 for t in test_results if not t.get('passed'))
            }
        }
    
    async def validate_portfolio_tools(self) -> Dict[str, Any]:
        """Validate portfolio tool consolidation."""
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATING PORTFOLIO TOOL CONSOLIDATION")
        logger.info("=" * 60)
        
        test_results = []
        
        # Test 1: Get positions
        logger.info("\nTest 1: Get positions")
        try:
            from src.mcp.server import get_positions as legacy_positions
            from src.mcp.consolidated_tools import BackwardCompatibilityAliases
            
            # Get legacy result
            legacy_result = await legacy_positions()
            
            # Get consolidated result
            consolidated_result = await BackwardCompatibilityAliases.trade_get_positions()
            
            # Compare structures
            match = (
                legacy_result.get('status') == consolidated_result.get('status') and
                isinstance(legacy_result.get('positions'), list) == isinstance(consolidated_result.get('positions'), list)
            )
            
            test_results.append({
                'test': 'Get positions',
                'passed': match,
                'has_positions': len(legacy_result.get('positions', [])) > 0
            })
            
            if match:
                logger.info("✅ Get positions test PASSED")
                self.results['passed'].append('portfolio_positions')
            else:
                logger.error("❌ Get positions test FAILED")
                self.results['failed'].append('portfolio_positions')
                
        except Exception as e:
            logger.error(f"❌ Get positions test ERROR: {e}")
            self.results['failed'].append('portfolio_positions')
            test_results.append({
                'test': 'Get positions',
                'passed': False,
                'error': str(e)
            })
        
        # Test 2: Account summary
        logger.info("\nTest 2: Account summary")
        try:
            from src.mcp.server import get_account_summary as legacy_account
            
            # Get legacy result
            legacy_result = await legacy_account()
            
            # Get consolidated result
            consolidated_result = await BackwardCompatibilityAliases.trade_get_account_summary()
            
            # Check key fields exist
            required_fields = ['net_liquidation', 'total_cash', 'buying_power']
            match = all(
                field in consolidated_result 
                for field in required_fields 
                if field in legacy_result
            )
            
            test_results.append({
                'test': 'Account summary',
                'passed': match,
                'has_required_fields': match
            })
            
            if match:
                logger.info("✅ Account summary test PASSED")
                self.results['passed'].append('portfolio_account')
            else:
                logger.error("❌ Account summary test FAILED")
                self.results['failed'].append('portfolio_account')
                
        except Exception as e:
            logger.error(f"❌ Account summary test ERROR: {e}")
            self.results['failed'].append('portfolio_account')
            test_results.append({
                'test': 'Account summary',
                'passed': False,
                'error': str(e)
            })
        
        return {
            'category': 'Portfolio Tools',
            'tests': test_results,
            'summary': {
                'total': len(test_results),
                'passed': sum(1 for t in test_results if t.get('passed')),
                'failed': sum(1 for t in test_results if not t.get('passed'))
            }
        }
    
    async def validate_close_tools(self) -> Dict[str, Any]:
        """Validate close tool consolidation (DRY RUN ONLY)."""
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATING CLOSE TOOL CONSOLIDATION (DRY RUN)")
        logger.info("=" * 60)
        
        test_results = []
        
        # Test 1: Parameter validation for standard close
        logger.info("\nTest 1: Parameter validation for standard close")
        try:
            from src.mcp.consolidated_tools import ConsolidationSafety
            
            # Test valid parameters
            valid_params = {
                'close_type': 'standard',
                'confirm_token': 'USER_CONFIRMED'
            }
            is_valid, msg = ConsolidationSafety.validate_close_params(valid_params)
            
            # Test invalid parameters (missing confirmation)
            invalid_params = {
                'close_type': 'standard',
                'confirm_token': None
            }
            is_invalid, invalid_msg = ConsolidationSafety.validate_close_params(invalid_params)
            
            match = is_valid and not is_invalid
            
            test_results.append({
                'test': 'Standard close validation',
                'passed': match,
                'valid_check': is_valid,
                'invalid_check': not is_invalid
            })
            
            if match:
                logger.info("✅ Standard close validation PASSED")
                self.results['passed'].append('close_standard_validation')
            else:
                logger.error("❌ Standard close validation FAILED")
                self.results['failed'].append('close_standard_validation')
                
        except Exception as e:
            logger.error(f"❌ Standard close validation ERROR: {e}")
            self.results['failed'].append('close_standard_validation')
            test_results.append({
                'test': 'Standard close validation',
                'passed': False,
                'error': str(e)
            })
        
        # Test 2: Emergency close double confirmation
        logger.info("\nTest 2: Emergency close double confirmation")
        try:
            # Test valid emergency close params
            valid_emergency = {
                'close_type': 'emergency',
                'confirm_token': 'USER_CONFIRMED',
                'second_confirmation': 'YES_CLOSE_ALL'
            }
            is_valid, msg = ConsolidationSafety.validate_close_params(valid_emergency)
            
            # Test invalid emergency close (missing second confirmation)
            invalid_emergency = {
                'close_type': 'emergency',
                'confirm_token': 'USER_CONFIRMED',
                'second_confirmation': None
            }
            is_invalid, invalid_msg = ConsolidationSafety.validate_close_params(invalid_emergency)
            
            match = is_valid and not is_invalid
            
            test_results.append({
                'test': 'Emergency close validation',
                'passed': match,
                'double_confirm_works': is_valid,
                'single_confirm_blocked': not is_invalid
            })
            
            if match:
                logger.info("✅ Emergency close validation PASSED")
                self.results['passed'].append('close_emergency_validation')
            else:
                logger.error("❌ Emergency close validation FAILED")
                self.results['failed'].append('close_emergency_validation')
                
        except Exception as e:
            logger.error(f"❌ Emergency close validation ERROR: {e}")
            self.results['failed'].append('close_emergency_validation')
            test_results.append({
                'test': 'Emergency close validation',
                'passed': False,
                'error': str(e)
            })
        
        return {
            'category': 'Close Tools',
            'tests': test_results,
            'summary': {
                'total': len(test_results),
                'passed': sum(1 for t in test_results if t.get('passed')),
                'failed': sum(1 for t in test_results if not t.get('passed'))
            }
        }
    
    def _compare_quotes(self, legacy: Dict, consolidated: Dict) -> bool:
        """Compare quote results for key fields."""
        # Key fields that must match
        key_fields = ['symbol', 'status']
        
        # Check if both have the key fields
        for field in key_fields:
            if legacy.get(field) != consolidated.get(field):
                logger.warning(f"Field mismatch: {field} - Legacy: {legacy.get(field)}, Consolidated: {consolidated.get(field)}")
                return False
        
        # Check if numeric fields are close (allow small differences)
        numeric_fields = ['last', 'bid', 'ask']
        for field in numeric_fields:
            if field in legacy and field in consolidated:
                if legacy[field] and consolidated[field]:
                    # Allow 0.01% difference for floating point
                    if abs(legacy[field] - consolidated[field]) > (legacy[field] * 0.0001):
                        logger.warning(f"Numeric mismatch: {field} - Legacy: {legacy[field]}, Consolidated: {consolidated[field]}")
                        return False
        
        return True
    
    async def run_all_validations(self) -> Dict[str, Any]:
        """Run all validation tests."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING COMPREHENSIVE CONSOLIDATION VALIDATION")
        logger.info("=" * 60)
        
        all_results = []
        
        # Validate quote tools
        quote_results = await self.validate_quote_tools()
        all_results.append(quote_results)
        
        # Validate portfolio tools
        portfolio_results = await self.validate_portfolio_tools()
        all_results.append(portfolio_results)
        
        # Validate close tools (dry run)
        close_results = await self.validate_close_tools()
        all_results.append(close_results)
        
        # Generate summary
        total_tests = sum(r['summary']['total'] for r in all_results)
        total_passed = sum(r['summary']['passed'] for r in all_results)
        total_failed = sum(r['summary']['failed'] for r in all_results)
        
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {total_passed} ✅")
        logger.info(f"Failed: {total_failed} ❌")
        logger.info(f"Success Rate: {(total_passed/total_tests)*100:.1f}%")
        
        return {
            'timestamp': self.results['timestamp'],
            'categories': all_results,
            'summary': {
                'total_tests': total_tests,
                'passed': total_passed,
                'failed': total_failed,
                'success_rate': (total_passed/total_tests)*100 if total_tests > 0 else 0,
                'passed_tests': self.results['passed'],
                'failed_tests': self.results['failed'],
                'warnings': self.results['warnings']
            },
            'recommendation': self._get_recommendation(total_passed, total_failed)
        }
    
    def _get_recommendation(self, passed: int, failed: int) -> str:
        """Get deployment recommendation based on test results."""
        if failed == 0:
            return "✅ SAFE TO DEPLOY - All tests passed"
        elif failed <= 2 and passed > 5:
            return "⚠️ DEPLOY WITH CAUTION - Minor issues detected, monitor closely"
        else:
            return "❌ DO NOT DEPLOY - Significant issues detected, fix before deployment"

async def test_performance():
    """Test performance of consolidated vs legacy tools."""
    logger.info("\n" + "=" * 60)
    logger.info("PERFORMANCE TESTING")
    logger.info("=" * 60)
    
    import time
    
    # Test quote performance
    logger.info("\nTesting quote tool performance...")
    
    from src.mcp.server import get_quote as legacy_quote
    from src.mcp.consolidated_tools import BackwardCompatibilityAliases
    
    # Legacy timing
    start = time.time()
    for _ in range(10):
        await legacy_quote('SPY', 'STK')
    legacy_time = time.time() - start
    
    # Consolidated timing
    start = time.time()
    for _ in range(10):
        await BackwardCompatibilityAliases.trade_get_quote('SPY', 'STK')
    consolidated_time = time.time() - start
    
    logger.info(f"Legacy: {legacy_time:.3f}s for 10 calls")
    logger.info(f"Consolidated: {consolidated_time:.3f}s for 10 calls")
    logger.info(f"Difference: {abs(legacy_time - consolidated_time):.3f}s")
    
    if consolidated_time < legacy_time * 1.1:  # Allow 10% slower
        logger.info("✅ Performance acceptable")
        return True
    else:
        logger.warning("⚠️ Performance degradation detected")
        return False

async def main():
    """Main test execution."""
    # Initialize validator
    validator = ConsolidationValidator()
    
    # Run all validations
    results = await validator.run_all_validations()
    
    # Run performance tests
    perf_ok = await test_performance()
    results['performance_ok'] = perf_ok
    
    # Save results to file
    with open('consolidation_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"\nResults saved to consolidation_test_results.json")
    
    # Print final recommendation
    logger.info("\n" + "=" * 60)
    logger.info("FINAL RECOMMENDATION")
    logger.info("=" * 60)
    logger.info(results['recommendation'])
    
    # Exit with appropriate code
    if results['summary']['failed'] == 0:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Failure

if __name__ == "__main__":
    # Ensure TWS is connected
    logger.info("Starting consolidation validation tests...")
    logger.info("Ensure TWS is running and connected on port 7497")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        sys.exit(1)