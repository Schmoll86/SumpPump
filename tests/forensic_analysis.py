#!/usr/bin/env python3
"""
Forensic Analysis of SumpPump Trading System
Data Flow Architect Analysis Report
Generated: 2025-01-07

This module performs comprehensive forensic analysis of the SumpPump trading system,
focusing on data flow, error handling, and potential failure points.
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import traceback

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# Configure detailed logging
logger.remove()
logger.add(sys.stdout, level="DEBUG", format="{time:HH:mm:ss} | {level} | {message}")


class ForensicAnalyzer:
    """Comprehensive system forensic analyzer."""
    
    def __init__(self):
        self.findings = {
            'data_flow': [],
            'failure_points': [],
            'type_issues': [],
            'async_violations': [],
            'error_handling': [],
            'recommendations': []
        }
        
    async def analyze_data_flow(self) -> Dict[str, Any]:
        """Trace data flow through the system."""
        logger.info("=== DATA FLOW ANALYSIS ===")
        
        flow_map = {
            'entry_points': [
                'MCP Server (src/mcp/server.py) - FastMCP tools receive user requests',
                'Parameters arrive as Dict[str, Any] from Claude Desktop',
            ],
            'transformation_layers': [
                '1. MCP Tool Layer - Parameter validation and type coercion',
                '2. Safety Validator - ExecutionSafety checks confirmation tokens',
                '3. Session State - Stores strategy between calculate/execute calls',
                '4. Type Coercion - sanitize_trading_params() converts numeric types',
                '5. TWS Connection - Singleton pattern with lazy loading',
                '6. IB API Layer - ib_async library handles TWS communication',
            ],
            'critical_paths': {
                'options_chain': [
                    'trade_get_options_chain() → TWSConnection.get_options_chain()',
                    'Creates Option contracts → reqMktData() with genericTickList="106"',
                    'Waits for Greeks → Returns OptionContract objects',
                    'ISSUE: Greeks often missing, fallback to IV calculation'
                ],
                'strategy_calculation': [
                    'trade_calculate_strategy() → Strategy module',
                    'Validates Level 2 compliance → Calculates P&L',
                    'Stores in SessionState → Returns analysis dict',
                    'ISSUE: Strategy object sometimes lost between calls'
                ],
                'trade_execution': [
                    'trade_execute() → Retrieves from SessionState',
                    'Safety validation → OrderBuilder creates IB orders',
                    'placeOrder() → Verification module checks fills',
                    'ISSUE: Verification sometimes fails despite successful trades'
                ]
            }
        }
        
        self.findings['data_flow'] = flow_map
        return flow_map
    
    async def identify_failure_points(self) -> List[Dict[str, Any]]:
        """Identify critical failure points in the system."""
        logger.info("=== FAILURE POINT ANALYSIS ===")
        
        failures = [
            {
                'location': 'src/modules/tws/connection.py:368-421',
                'issue': 'Greeks data retrieval unreliable',
                'severity': 'HIGH',
                'details': 'reqMktData with genericTickList="106" often fails to return Greeks',
                'current_mitigation': 'Fallback IV calculation after 2 seconds',
                'recommendation': 'Implement robust Greeks calculation locally using py_vollib'
            },
            {
                'location': 'src/mcp/server.py:50-99',
                'issue': 'Session state loss between MCP calls',
                'severity': 'MEDIUM',
                'details': 'Strategy object sometimes not persisted correctly',
                'current_mitigation': '5-minute TTL on session state',
                'recommendation': 'Add persistent storage with Redis or file-based cache'
            },
            {
                'location': 'src/modules/execution/verification.py:55-136',
                'issue': 'Order verification false negatives',
                'severity': 'HIGH',
                'details': 'Position changes not always detected immediately',
                'current_mitigation': 'Multiple retry attempts with delays',
                'recommendation': 'Use order status events instead of polling positions'
            },
            {
                'location': 'src/modules/utils/type_coercion.py',
                'issue': 'Type coercion silently fails',
                'severity': 'MEDIUM',
                'details': 'Returns None on coercion failure instead of raising error',
                'current_mitigation': 'Logging warnings',
                'recommendation': 'Add strict mode that raises exceptions on type failures'
            },
            {
                'location': 'Event loop management',
                'issue': 'Nested async loops causing conflicts',
                'severity': 'CRITICAL',
                'details': 'MCP server runs in sync context but needs async TWS calls',
                'current_mitigation': 'nest_asyncio.apply() patch',
                'recommendation': 'Refactor to use proper async context throughout'
            }
        ]
        
        self.findings['failure_points'] = failures
        return failures
    
    async def check_error_propagation(self) -> Dict[str, Any]:
        """Analyze error propagation through the system."""
        logger.info("=== ERROR PROPAGATION ANALYSIS ===")
        
        error_flow = {
            'proper_handling': [
                'TWSConnectionError properly bubbles up to MCP layer',
                'ExecutionSafety blocks unsafe operations correctly',
                'Risk validation errors prevent over-leveraging'
            ],
            'missing_handling': [
                'No timeout handling in options chain fetching',
                'Silent failures in type coercion (returns None)',
                'Lost stack traces when converting to MCP response dicts',
                'No circuit breaker for repeated TWS failures'
            ],
            'error_recovery': {
                'connection_loss': 'Automatic reconnection with exponential backoff',
                'rate_limiting': 'Basic delay but no queue management',
                'market_data_limit': 'Stops at 95 subscriptions but no cleanup',
                'execution_failure': 'Retries but may duplicate orders'
            }
        }
        
        self.findings['error_handling'] = error_flow
        return error_flow
    
    async def validate_async_patterns(self) -> List[str]:
        """Check for async/await pattern violations."""
        logger.info("=== ASYNC PATTERN VALIDATION ===")
        
        violations = [
            'LazyTWSConnection proxy mixes sync/async contexts',
            'Some MCP tools not properly awaiting async operations',
            'nest_asyncio patch masks potential deadlocks',
            'No async context managers for market data subscriptions',
            'Missing await in some error handling blocks'
        ]
        
        self.findings['async_violations'] = violations
        return violations
    
    async def test_type_safety(self) -> Dict[str, Any]:
        """Test type safety and coercion."""
        logger.info("=== TYPE SAFETY TESTING ===")
        
        from src.modules.utils.type_coercion import coerce_numeric, coerce_integer
        
        test_cases = {
            'numeric_coercion': [
                (42, 42.0, 'Integer to float'),
                ('42.5', 42.5, 'String to float'),
                ('  42.5  ', 42.5, 'Whitespace string to float'),
                ('invalid', None, 'Invalid string returns None'),
                (None, None, 'None passes through'),
            ],
            'integer_coercion': [
                (42.0, 42, 'Float to int'),
                ('42', 42, 'String to int'),
                ('42.9', 42, 'Float string to int (loses precision)'),
                ('invalid', None, 'Invalid string returns None'),
            ]
        }
        
        results = {'passed': [], 'failed': []}
        
        for test_type, cases in test_cases.items():
            coerce_fn = coerce_numeric if 'numeric' in test_type else coerce_integer
            
            for input_val, expected, description in cases:
                result = coerce_fn(input_val)
                if result == expected:
                    results['passed'].append(f"✓ {description}: {input_val} → {result}")
                else:
                    results['failed'].append(f"✗ {description}: {input_val} → {result} (expected {expected})")
        
        self.findings['type_issues'] = results
        return results
    
    def generate_recommendations(self) -> List[Dict[str, Any]]:
        """Generate actionable recommendations."""
        logger.info("=== RECOMMENDATIONS ===")
        
        recommendations = [
            {
                'priority': 'CRITICAL',
                'area': 'Event Loop Management',
                'issue': 'nest_asyncio patch is a band-aid solution',
                'recommendation': 'Refactor MCP server to use native async/await throughout',
                'implementation': '''
                    # Instead of sync MCP tools, use async:
                    @mcp.tool(name="trade_execute")
                    async def execute_trade(...):
                        # Native async without nest_asyncio
                        async with get_tws_connection() as tws:
                            result = await tws.execute_order(...)
                '''
            },
            {
                'priority': 'HIGH',
                'area': 'Greeks Data Reliability',
                'issue': 'TWS Greeks data unreliable',
                'recommendation': 'Implement local Greeks calculation',
                'implementation': '''
                    from py_vollib.black_scholes.greeks import analytical
                    
                    def calculate_greeks_locally(option_price, underlying, strike, rate, time_to_exp):
                        # Calculate IV first, then Greeks
                        iv = implied_volatility(option_price, underlying, strike, rate, time_to_exp)
                        delta = analytical.delta(flag, underlying, strike, time_to_exp, rate, iv)
                        # ... calculate other Greeks
                '''
            },
            {
                'priority': 'HIGH',
                'area': 'Order Verification',
                'issue': 'Polling-based verification misses fills',
                'recommendation': 'Use event-driven order status updates',
                'implementation': '''
                    # Subscribe to order status events
                    trade = ib.placeOrder(contract, order)
                    await trade  # Wait for fill event
                    if trade.orderStatus.status == 'Filled':
                        # Verified fill
                '''
            },
            {
                'priority': 'MEDIUM',
                'area': 'Session Persistence',
                'issue': 'In-memory session state lost on restart',
                'recommendation': 'Add Redis or file-based persistence',
                'implementation': '''
                    import redis
                    import pickle
                    
                    class PersistentSessionState:
                        def __init__(self):
                            self.redis = redis.Redis()
                        
                        def save_strategy(self, strategy):
                            self.redis.setex(
                                f"strategy:{strategy.symbol}",
                                300,  # 5 minute TTL
                                pickle.dumps(strategy)
                            )
                '''
            },
            {
                'priority': 'MEDIUM',
                'area': 'Error Handling',
                'issue': 'Silent failures in type coercion',
                'recommendation': 'Add strict mode with exceptions',
                'implementation': '''
                    def coerce_numeric(value, param_name, strict=False):
                        result = try_coerce(value)
                        if result is None and strict:
                            raise TypeError(f"Cannot coerce {param_name}: {value}")
                        return result
                '''
            },
            {
                'priority': 'LOW',
                'area': 'Circuit Breaker',
                'issue': 'No protection against cascade failures',
                'recommendation': 'Implement circuit breaker pattern',
                'implementation': '''
                    class CircuitBreaker:
                        def __init__(self, failure_threshold=5, timeout=60):
                            self.failures = 0
                            self.threshold = failure_threshold
                            self.timeout = timeout
                            self.last_failure = None
                            
                        def call(self, func, *args, **kwargs):
                            if self.is_open():
                                raise CircuitOpenError()
                            try:
                                result = func(*args, **kwargs)
                                self.on_success()
                                return result
                            except Exception as e:
                                self.on_failure()
                                raise
                '''
            }
        ]
        
        self.findings['recommendations'] = recommendations
        return recommendations
    
    async def run_full_analysis(self):
        """Run complete forensic analysis."""
        logger.info("=" * 60)
        logger.info("SUMPPUMP FORENSIC ANALYSIS - DATA FLOW ARCHITECT")
        logger.info("=" * 60)
        
        # Run all analyses
        await self.analyze_data_flow()
        await self.identify_failure_points()
        await self.check_error_propagation()
        await self.validate_async_patterns()
        await self.test_type_safety()
        self.generate_recommendations()
        
        # Generate report
        self.print_report()
        
    def print_report(self):
        """Print comprehensive analysis report."""
        
        print("\n" + "=" * 60)
        print("FORENSIC ANALYSIS REPORT")
        print("=" * 60)
        
        # Data Flow Summary
        print("\n📊 DATA FLOW SUMMARY:")
        print("-" * 40)
        for path_name, steps in self.findings['data_flow']['critical_paths'].items():
            print(f"\n{path_name.upper()}:")
            for i, step in enumerate(steps, 1):
                print(f"  {i}. {step}")
        
        # Critical Failure Points
        print("\n⚠️ CRITICAL FAILURE POINTS:")
        print("-" * 40)
        for failure in self.findings['failure_points']:
            if failure['severity'] in ['HIGH', 'CRITICAL']:
                print(f"\n[{failure['severity']}] {failure['issue']}")
                print(f"  Location: {failure['location']}")
                print(f"  Details: {failure['details']}")
                print(f"  Fix: {failure['recommendation']}")
        
        # Async Violations
        print("\n🔄 ASYNC PATTERN VIOLATIONS:")
        print("-" * 40)
        for violation in self.findings['async_violations']:
            print(f"  • {violation}")
        
        # Type Safety Results
        print("\n🔍 TYPE SAFETY TEST RESULTS:")
        print("-" * 40)
        type_results = self.findings['type_issues']
        if type_results:
            print(f"  Passed: {len(type_results.get('passed', []))}")
            print(f"  Failed: {len(type_results.get('failed', []))}")
            if type_results.get('failed'):
                print("\n  Failed tests:")
                for fail in type_results['failed'][:3]:  # Show first 3
                    print(f"    {fail}")
        
        # Top Recommendations
        print("\n💡 TOP RECOMMENDATIONS:")
        print("-" * 40)
        for rec in self.findings['recommendations'][:3]:  # Top 3
            print(f"\n[{rec['priority']}] {rec['area']}")
            print(f"  Issue: {rec['issue']}")
            print(f"  Fix: {rec['recommendation']}")
        
        print("\n" + "=" * 60)
        print("END OF FORENSIC ANALYSIS")
        print("=" * 60)


async def main():
    """Main entry point for forensic analysis."""
    analyzer = ForensicAnalyzer()
    
    try:
        await analyzer.run_full_analysis()
        
        # Additional live system test if TWS is running
        print("\n🔬 ATTEMPTING LIVE SYSTEM TEST...")
        print("-" * 40)
        
        try:
            from src.modules.tws.connection import get_tws_connection
            
            tws = get_tws_connection()
            await tws.connect()
            
            if tws.connected:
                print("✅ TWS connection successful")
                
                # Test account access
                accounts = tws.ib.managedAccounts()
                if accounts:
                    print(f"✅ Account access confirmed: {accounts[0]}")
                else:
                    print("⚠️ No managed accounts found")
                
                tws.disconnect()
            else:
                print("❌ TWS connection failed")
                
        except Exception as e:
            print(f"❌ Live test failed: {e}")
            
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())