#!/usr/bin/env python3
"""
Test suite for SumpPump Safety System
Tests the ExecutionSafety validation to prevent accidental trade executions.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
import sys
from pathlib import Path

# Add src to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.modules.safety import ExecutionSafety, ConfirmationRequiredError


class TestExecutionSafety:
    """Test cases for ExecutionSafety validation system."""
    
    def test_immediate_execution_without_confirmation_blocked(self):
        """Test 1: Immediate execution without confirmation - MUST FAIL"""
        params = {
            'symbol': 'LLY',
            'strike': 645,
            'expiry': '20250815',
            'right': 'C',
            'quantity': 1,
            'trigger_condition': 'immediate'  # No confirm_token
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_buy_to_close',
            params
        )
        
        assert is_valid == False
        assert 'SAFETY_CHECK_FAILED' in error_message
        assert 'USER_CONFIRMED' in error_message
        print("✅ Test 1 PASSED: Immediate execution blocked without confirmation")
    
    def test_immediate_execution_with_confirmation_allowed(self):
        """Test 2: Immediate execution WITH confirmation - MUST SUCCEED"""
        params = {
            'symbol': 'LLY',
            'strike': 645,
            'expiry': '20250815',
            'right': 'C',
            'quantity': 1,
            'trigger_condition': 'immediate',
            'confirm_token': 'USER_CONFIRMED'  # Has confirmation
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_buy_to_close',
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 2 PASSED: Immediate execution allowed with confirmation")
    
    def test_conditional_setup_allowed_without_confirmation(self):
        """Test 3: Conditional setup - MUST SUCCEED without confirmation"""
        params = {
            'symbol': 'LLY',
            'strike': 645,
            'expiry': '20250815',
            'right': 'C',
            'quantity': 1,
            'trigger_condition': 'below',  # Conditional, not immediate
            'trigger_price': 635.5
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_buy_to_close',
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 3 PASSED: Conditional setup allowed without confirmation")
    
    def test_market_order_without_confirmation_blocked(self):
        """Test 4: Market order without confirmation - MUST FAIL"""
        params = {
            'strategy': {'type': 'bull_call_spread'},
            'order_type': 'MKT'  # Market order, no confirmation
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_execute',
            params
        )
        
        assert is_valid == False
        assert 'SAFETY_CHECK_FAILED' in error_message
        print("✅ Test 4 PASSED: Market order blocked without confirmation")
    
    def test_trade_execute_without_confirmation_blocked(self):
        """Test 5: trade_execute without confirmation - MUST FAIL"""
        params = {
            'strategy': {'type': 'bull_call_spread', 'symbol': 'SPY'},
            'confirm_token': 'WRONG_TOKEN'  # Wrong confirmation token
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_execute',
            params
        )
        
        assert is_valid == False
        assert 'USER_CONFIRMED' in error_message
        print("✅ Test 5 PASSED: trade_execute blocked with wrong token")
    
    def test_trade_execute_with_confirmation_allowed(self):
        """Test 6: trade_execute with confirmation - MUST SUCCEED"""
        params = {
            'strategy': {'type': 'bull_call_spread', 'symbol': 'SPY'},
            'confirm_token': 'USER_CONFIRMED'  # Correct confirmation
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_execute',
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 6 PASSED: trade_execute allowed with confirmation")
    
    def test_close_position_market_order_blocked(self):
        """Test 7: Close position with market order without confirmation - MUST FAIL"""
        params = {
            'symbol': 'AAPL',
            'position_type': 'call',
            'quantity': 1,
            'order_type': 'MKT'  # Market order without confirmation
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_close_position',
            params
        )
        
        assert is_valid == False
        assert 'SAFETY_CHECK_FAILED' in error_message
        print("✅ Test 7 PASSED: Close position blocked without confirmation")
    
    def test_conditional_order_with_conditions_allowed(self):
        """Test 8: Conditional order with proper conditions - MUST SUCCEED"""
        params = {
            'symbol': 'SPY',
            'action': 'BUY_TO_CLOSE',
            'conditions': [{'type': 'price', 'operator': 'above', 'value': 650}],
            'order_type': 'MKT'  # Market order but conditional
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_create_conditional_order',
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 8 PASSED: Conditional order allowed")
    
    def test_stop_loss_setup_allowed(self):
        """Test 9: Stop loss setup (usually conditional) - MUST SUCCEED"""
        params = {
            'position_id': 'ABC123',
            'stop_price': 100.0,
            'stop_type': 'trailing'  # Usually conditional
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_set_stop_loss',
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 9 PASSED: Stop loss setup allowed")
    
    def test_unprotected_function_always_allowed(self):
        """Test 10: Unprotected function - MUST SUCCEED"""
        params = {
            'symbol': 'AAPL',
            'dangerous_param': 'immediate'
        }
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            'trade_get_quote',  # Not in PROTECTED_FUNCTIONS
            params
        )
        
        assert is_valid == True
        assert error_message is None
        print("✅ Test 10 PASSED: Unprotected function allowed")
    
    def test_dangerous_param_identification(self):
        """Test 11: Dangerous parameter identification"""
        params = {
            'trigger_condition': 'immediate',
            'order_type': 'MKT',
            'execute_now': True
        }
        
        dangerous_params = ExecutionSafety._identify_dangerous_params(params)
        
        assert len(dangerous_params) == 3
        assert "trigger_condition='immediate'" in dangerous_params
        assert "order_type='MKT'" in dangerous_params
        assert "execute_now='True'" in dangerous_params
        print("✅ Test 11 PASSED: Dangerous parameters identified correctly")
    
    def test_conditional_setup_detection(self):
        """Test 12: Conditional setup detection"""
        # Test conditional parameters
        params_conditional = {
            'trigger_condition': 'above',
            'trigger_price': 100.0
        }
        assert ExecutionSafety._is_conditional_setup(params_conditional) == True
        
        # Test immediate parameters
        params_immediate = {
            'trigger_condition': 'immediate'
        }
        assert ExecutionSafety._is_conditional_setup(params_immediate) == False
        
        # Test no special parameters
        params_none = {
            'symbol': 'AAPL',
            'quantity': 1
        }
        assert ExecutionSafety._is_conditional_setup(params_none) == False
        
        print("✅ Test 12 PASSED: Conditional setup detection working")
    
    def test_audit_logging(self):
        """Test 13: Audit logging functionality"""
        import io
        import contextlib
        
        # Test that logging doesn't crash
        params = {
            'symbol': 'TEST',
            'confirm_token': 'USER_CONFIRMED'
        }
        
        try:
            ExecutionSafety.log_execution_attempt(
                'trade_execute',
                params,
                True,
                'test_user'
            )
            print("✅ Test 13 PASSED: Audit logging works")
        except Exception as e:
            print(f"❌ Test 13 FAILED: Audit logging error: {e}")
            assert False


def run_all_tests():
    """Run all safety system tests."""
    print("="*60)
    print("RUNNING SUMPPUMP SAFETY SYSTEM TESTS")
    print("="*60)
    
    test_instance = TestExecutionSafety()
    
    test_methods = [
        test_instance.test_immediate_execution_without_confirmation_blocked,
        test_instance.test_immediate_execution_with_confirmation_allowed,
        test_instance.test_conditional_setup_allowed_without_confirmation,
        test_instance.test_market_order_without_confirmation_blocked,
        test_instance.test_trade_execute_without_confirmation_blocked,
        test_instance.test_trade_execute_with_confirmation_allowed,
        test_instance.test_close_position_market_order_blocked,
        test_instance.test_conditional_order_with_conditions_allowed,
        test_instance.test_stop_loss_setup_allowed,
        test_instance.test_unprotected_function_always_allowed,
        test_instance.test_dangerous_param_identification,
        test_instance.test_conditional_setup_detection,
        test_instance.test_audit_logging
    ]
    
    passed = 0
    failed = 0
    
    for test_method in test_methods:
        try:
            test_method()
            passed += 1
        except Exception as e:
            print(f"❌ {test_method.__name__} FAILED: {e}")
            failed += 1
    
    print("="*60)
    print(f"TEST RESULTS: {passed} PASSED, {failed} FAILED")
    print("="*60)
    
    if failed == 0:
        print("🎉 ALL SAFETY TESTS PASSED - System is secure!")
        return True
    else:
        print("⚠️  SAFETY TESTS FAILED - System needs attention!")
        return False


# Example usage scenarios for manual testing
def demo_safety_scenarios():
    """Demonstrate various safety scenarios."""
    print("\n" + "="*60)
    print("SAFETY SYSTEM DEMO SCENARIOS")
    print("="*60)
    
    scenarios = [
        {
            'name': 'Accidental Immediate Buy-to-Close (BLOCKED)',
            'function': 'trade_buy_to_close',
            'params': {
                'symbol': 'LLY',
                'strike': 645,
                'expiry': '20250815',
                'right': 'C',
                'quantity': 1,
                'trigger_condition': 'immediate'
            },
            'expected': 'BLOCKED'
        },
        {
            'name': 'Intentional Buy-to-Close with Confirmation (ALLOWED)',
            'function': 'trade_buy_to_close',
            'params': {
                'symbol': 'LLY',
                'strike': 645,
                'expiry': '20250815',
                'right': 'C',
                'quantity': 1,
                'trigger_condition': 'immediate',
                'confirm_token': 'USER_CONFIRMED'
            },
            'expected': 'ALLOWED'
        },
        {
            'name': 'Conditional Buy-to-Close Setup (ALLOWED)',
            'function': 'trade_buy_to_close',
            'params': {
                'symbol': 'SPY',
                'strike': 645,
                'expiry': '20250117',
                'right': 'C',
                'quantity': 1,
                'trigger_condition': 'below',
                'trigger_price': 635.0
            },
            'expected': 'ALLOWED'
        }
    ]
    
    for scenario in scenarios:
        print(f"\nScenario: {scenario['name']}")
        print(f"Parameters: {scenario['params']}")
        
        is_valid, error_message = ExecutionSafety.validate_execution_request(
            scenario['function'],
            scenario['params']
        )
        
        result = 'ALLOWED' if is_valid else 'BLOCKED'
        status = '✅' if result == scenario['expected'] else '❌'
        
        print(f"Result: {result} {status}")
        if error_message:
            print(f"Message: {error_message}")
        print("-" * 40)


if __name__ == '__main__':
    # Run comprehensive tests
    success = run_all_tests()
    
    # Show demo scenarios
    demo_safety_scenarios()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)