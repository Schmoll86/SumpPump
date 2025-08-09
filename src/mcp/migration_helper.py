"""
Migration Helper for Safe Tool Consolidation
Provides feature flags, monitoring, and rollback capabilities
"""

import os
import json
import logging
from typing import Dict, Any, Callable
from datetime import datetime
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)

class FeatureFlags:
    """Manage feature flags for gradual rollout."""
    
    # Feature flag configuration
    FLAGS = {
        'use_consolidated_quotes': os.getenv('CONSOLIDATED_QUOTES', 'false').lower() == 'true',
        'use_consolidated_portfolio': os.getenv('CONSOLIDATED_PORTFOLIO', 'false').lower() == 'true',
        'use_consolidated_close': os.getenv('CONSOLIDATED_CLOSE', 'false').lower() == 'true',
        'use_consolidated_orders': os.getenv('CONSOLIDATED_ORDERS', 'false').lower() == 'true',
        'log_consolidation_usage': os.getenv('LOG_CONSOLIDATION', 'true').lower() == 'true',
        'consolidation_dry_run': os.getenv('CONSOLIDATION_DRY_RUN', 'false').lower() == 'true'
    }
    
    @classmethod
    def is_enabled(cls, flag: str) -> bool:
        """Check if a feature flag is enabled."""
        return cls.FLAGS.get(flag, False)
    
    @classmethod
    def enable(cls, flag: str):
        """Enable a feature flag (for testing)."""
        cls.FLAGS[flag] = True
        logger.info(f"[FEATURE_FLAG] Enabled: {flag}")
    
    @classmethod
    def disable(cls, flag: str):
        """Disable a feature flag (for rollback)."""
        cls.FLAGS[flag] = False
        logger.warning(f"[FEATURE_FLAG] Disabled: {flag}")
    
    @classmethod
    def get_status(cls) -> Dict[str, bool]:
        """Get status of all feature flags."""
        return cls.FLAGS.copy()

class ConsolidationMonitor:
    """Monitor consolidated tool usage and performance."""
    
    def __init__(self):
        self.metrics = {
            'calls': {},
            'errors': {},
            'performance': {},
            'rollbacks': []
        }
    
    def log_call(self, tool_name: str, consolidated: bool, duration: float, success: bool):
        """Log a tool call for monitoring."""
        key = f"{tool_name}_{'consolidated' if consolidated else 'legacy'}"
        
        if key not in self.metrics['calls']:
            self.metrics['calls'][key] = {'count': 0, 'success': 0, 'failed': 0}
        
        self.metrics['calls'][key]['count'] += 1
        if success:
            self.metrics['calls'][key]['success'] += 1
        else:
            self.metrics['calls'][key]['failed'] += 1
        
        # Track performance
        if key not in self.metrics['performance']:
            self.metrics['performance'][key] = []
        self.metrics['performance'][key].append(duration)
        
        # Log if enabled
        if FeatureFlags.is_enabled('log_consolidation_usage'):
            logger.info(f"[MONITOR] {key}: duration={duration:.3f}s, success={success}")
    
    def log_error(self, tool_name: str, consolidated: bool, error: str):
        """Log an error for analysis."""
        key = f"{tool_name}_{'consolidated' if consolidated else 'legacy'}"
        
        if key not in self.metrics['errors']:
            self.metrics['errors'][key] = []
        
        self.metrics['errors'][key].append({
            'timestamp': datetime.now().isoformat(),
            'error': error
        })
        
        logger.error(f"[MONITOR] Error in {key}: {error}")
    
    def log_rollback(self, tool_name: str, reason: str):
        """Log a rollback event."""
        self.metrics['rollbacks'].append({
            'tool': tool_name,
            'timestamp': datetime.now().isoformat(),
            'reason': reason
        })
        logger.warning(f"[ROLLBACK] {tool_name}: {reason}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        # Calculate average performance
        perf_summary = {}
        for key, times in self.metrics['performance'].items():
            if times:
                perf_summary[key] = {
                    'avg': sum(times) / len(times),
                    'min': min(times),
                    'max': max(times),
                    'calls': len(times)
                }
        
        return {
            'calls': self.metrics['calls'],
            'errors': self.metrics['errors'],
            'performance': perf_summary,
            'rollbacks': self.metrics['rollbacks']
        }
    
    def should_rollback(self, tool_name: str, threshold_error_rate: float = 0.1) -> bool:
        """Determine if a tool should be rolled back based on error rate."""
        consolidated_key = f"{tool_name}_consolidated"
        
        if consolidated_key in self.metrics['calls']:
            stats = self.metrics['calls'][consolidated_key]
            if stats['count'] > 10:  # Need minimum calls for decision
                error_rate = stats['failed'] / stats['count']
                if error_rate > threshold_error_rate:
                    return True
        
        return False

# Global monitor instance
monitor = ConsolidationMonitor()

def with_consolidation(tool_name: str, flag_name: str):
    """
    Decorator to wrap tools with consolidation logic.
    
    Usage:
        @with_consolidation('trade_get_quote', 'use_consolidated_quotes')
        async def get_quote(symbol: str, asset_type: str = 'STK'):
            # Original implementation
            pass
    """
    def decorator(legacy_func: Callable):
        @wraps(legacy_func)
        async def wrapper(*args, **kwargs):
            start_time = asyncio.get_event_loop().time()
            
            # Check if consolidation is enabled
            use_consolidated = FeatureFlags.is_enabled(flag_name)
            
            # Check if we should auto-rollback based on errors
            if use_consolidated and monitor.should_rollback(tool_name):
                logger.warning(f"[AUTO_ROLLBACK] Disabling consolidation for {tool_name}")
                FeatureFlags.disable(flag_name)
                monitor.log_rollback(tool_name, "Auto-rollback due to high error rate")
                use_consolidated = False
            
            try:
                if use_consolidated:
                    # Import consolidated implementation
                    from src.mcp.consolidated_tools import BackwardCompatibilityAliases
                    
                    # Get the consolidated function
                    consolidated_func = getattr(BackwardCompatibilityAliases, tool_name)
                    
                    # Dry run mode - call both and compare
                    if FeatureFlags.is_enabled('consolidation_dry_run'):
                        logger.info(f"[DRY_RUN] Running both implementations for {tool_name}")
                        
                        # Run both in parallel
                        legacy_task = asyncio.create_task(legacy_func(*args, **kwargs))
                        consolidated_task = asyncio.create_task(consolidated_func(*args, **kwargs))
                        
                        legacy_result = await legacy_task
                        consolidated_result = await consolidated_task
                        
                        # Compare results (simplified comparison)
                        if json.dumps(legacy_result, sort_keys=True) != json.dumps(consolidated_result, sort_keys=True):
                            logger.warning(f"[DRY_RUN] Results differ for {tool_name}")
                            logger.debug(f"Legacy: {legacy_result}")
                            logger.debug(f"Consolidated: {consolidated_result}")
                        
                        # Return legacy result in dry run
                        result = legacy_result
                    else:
                        # Normal consolidated execution
                        result = await consolidated_func(*args, **kwargs)
                    
                    # Log success
                    duration = asyncio.get_event_loop().time() - start_time
                    monitor.log_call(tool_name, True, duration, True)
                    
                else:
                    # Use legacy implementation
                    result = await legacy_func(*args, **kwargs)
                    
                    # Log success
                    duration = asyncio.get_event_loop().time() - start_time
                    monitor.log_call(tool_name, False, duration, True)
                
                return result
                
            except Exception as e:
                # Log error
                duration = asyncio.get_event_loop().time() - start_time
                monitor.log_call(tool_name, use_consolidated, duration, False)
                monitor.log_error(tool_name, use_consolidated, str(e))
                
                # If consolidated failed, try legacy as fallback
                if use_consolidated and not FeatureFlags.is_enabled('consolidation_dry_run'):
                    logger.warning(f"[FALLBACK] Consolidated {tool_name} failed, trying legacy")
                    try:
                        result = await legacy_func(*args, **kwargs)
                        logger.info(f"[FALLBACK] Legacy {tool_name} succeeded")
                        return result
                    except Exception as legacy_error:
                        logger.error(f"[FALLBACK] Legacy also failed: {legacy_error}")
                        raise
                
                raise
        
        return wrapper
    return decorator

class RollbackManager:
    """Manage rollback procedures for consolidated tools."""
    
    @staticmethod
    async def rollback_tool(tool_name: str, reason: str = "Manual rollback"):
        """Rollback a specific tool to legacy implementation."""
        flag_map = {
            'trade_get_quote': 'use_consolidated_quotes',
            'trade_get_watchlist_quotes': 'use_consolidated_quotes',
            'trade_get_index_quote': 'use_consolidated_quotes',
            'trade_get_crypto_quote': 'use_consolidated_quotes',
            'trade_get_fx_quote': 'use_consolidated_quotes',
            'trade_get_positions': 'use_consolidated_portfolio',
            'trade_get_account_summary': 'use_consolidated_portfolio',
            'trade_get_portfolio_summary': 'use_consolidated_portfolio',
            'trade_close_position': 'use_consolidated_close',
            'trade_buy_to_close': 'use_consolidated_close',
            'trade_direct_close': 'use_consolidated_close',
            'trade_emergency_close': 'use_consolidated_close'
        }
        
        if tool_name in flag_map:
            flag = flag_map[tool_name]
            FeatureFlags.disable(flag)
            monitor.log_rollback(tool_name, reason)
            logger.info(f"[ROLLBACK] Successfully rolled back {tool_name}")
            return True
        else:
            logger.error(f"[ROLLBACK] Unknown tool: {tool_name}")
            return False
    
    @staticmethod
    async def rollback_all(reason: str = "Emergency rollback"):
        """Rollback all consolidated tools."""
        flags_to_disable = [
            'use_consolidated_quotes',
            'use_consolidated_portfolio',
            'use_consolidated_close',
            'use_consolidated_orders'
        ]
        
        for flag in flags_to_disable:
            FeatureFlags.disable(flag)
        
        monitor.log_rollback("ALL_TOOLS", reason)
        logger.warning(f"[ROLLBACK] All consolidations disabled: {reason}")
        return True
    
    @staticmethod
    def get_rollback_script() -> str:
        """Generate shell script for emergency rollback."""
        return """#!/bin/bash
# Emergency Rollback Script for SumpPump Consolidation

echo "Starting emergency rollback..."

# Disable all consolidation flags
export CONSOLIDATED_QUOTES=false
export CONSOLIDATED_PORTFOLIO=false
export CONSOLIDATED_CLOSE=false
export CONSOLIDATED_ORDERS=false

# Kill existing server
pkill -f "server.py"
sleep 2

# Restart with legacy implementations
echo "Restarting MCP server with legacy implementations..."
/Users/schmoll/Desktop/SumpPump/venv/bin/python src/mcp/server.py &

echo "Rollback complete. All tools using legacy implementations."
"""

class ConsolidationTester:
    """Test consolidated tools before deployment."""
    
    @staticmethod
    async def test_quote_consolidation():
        """Test quote tool consolidation."""
        from src.mcp.consolidated_tools import MarketDataConsolidator
        
        test_cases = [
            # Single stock quote
            {'symbols': 'AAPL', 'asset_type': 'STK'},
            # Multiple stocks
            {'symbols': ['AAPL', 'GOOGL', 'MSFT'], 'asset_type': 'STK'},
            # Index quote
            {'symbols': 'SPX', 'asset_type': 'IND'},
            # With depth data
            {'symbols': 'AAPL', 'asset_type': 'STK', 'include_depth': True}
        ]
        
        results = []
        for test in test_cases:
            try:
                result = await MarketDataConsolidator.get_market_data(**test)
                results.append({
                    'test': test,
                    'success': result.get('status') != 'error',
                    'result': result
                })
            except Exception as e:
                results.append({
                    'test': test,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    @staticmethod
    async def test_portfolio_consolidation():
        """Test portfolio tool consolidation."""
        from src.mcp.consolidated_tools import PortfolioConsolidator
        
        test_cases = [
            {'view': 'positions'},
            {'view': 'account'},
            {'view': 'summary', 'include_greeks': True},
            {'view': 'complete'}
        ]
        
        results = []
        for test in test_cases:
            try:
                result = await PortfolioConsolidator.get_portfolio(**test)
                results.append({
                    'test': test,
                    'success': result.get('status') != 'error',
                    'result': result
                })
            except Exception as e:
                results.append({
                    'test': test,
                    'success': False,
                    'error': str(e)
                })
        
        return results

# Usage Example in server.py:
"""
from src.mcp.migration_helper import with_consolidation, FeatureFlags, monitor

# Apply consolidation decorator to existing tools
@mcp.tool(name="trade_get_quote")
@with_consolidation('trade_get_quote', 'use_consolidated_quotes')
async def get_quote(symbol: str, asset_type: str = 'STK'):
    # Original implementation
    ...

# Check metrics endpoint
@mcp.tool(name="consolidation_metrics")
async def get_consolidation_metrics():
    return {
        'feature_flags': FeatureFlags.get_status(),
        'metrics': monitor.get_metrics()
    }

# Rollback endpoint
@mcp.tool(name="consolidation_rollback")
async def rollback_consolidation(tool_name: Optional[str] = None):
    if tool_name:
        return await RollbackManager.rollback_tool(tool_name)
    else:
        return await RollbackManager.rollback_all()
"""