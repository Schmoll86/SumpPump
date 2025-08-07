#!/usr/bin/env python3
"""
Quick test runner for safety system validation
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.modules.safety import ExecutionSafety

def test_basic_safety():
    """Test basic safety functionality"""
    print("Testing SumpPump Safety System...")
    
    # Test 1: Immediate execution blocked
    params1 = {
        'symbol': 'LLY',
        'trigger_condition': 'immediate',
        'order_type': 'MKT'
    }
    
    is_valid1, error1 = ExecutionSafety.validate_execution_request('trade_buy_to_close', params1)
    print(f"Test 1 - Immediate execution without confirmation: {'BLOCKED' if not is_valid1 else 'ALLOWED'} ✅" if not is_valid1 else "❌")
    
    # Test 2: With confirmation allowed
    params2 = {
        'symbol': 'LLY',
        'trigger_condition': 'immediate',
        'confirm_token': 'USER_CONFIRMED'
    }
    
    is_valid2, error2 = ExecutionSafety.validate_execution_request('trade_buy_to_close', params2)
    print(f"Test 2 - Immediate execution with confirmation: {'ALLOWED' if is_valid2 else 'BLOCKED'} ✅" if is_valid2 else "❌")
    
    # Test 3: Conditional setup allowed
    params3 = {
        'symbol': 'SPY',
        'trigger_condition': 'below',
        'trigger_price': 635.0
    }
    
    is_valid3, error3 = ExecutionSafety.validate_execution_request('trade_buy_to_close', params3)
    print(f"Test 3 - Conditional setup: {'ALLOWED' if is_valid3 else 'BLOCKED'} ✅" if is_valid3 else "❌")
    
    # Test 4: Protected functions
    protected_functions = ExecutionSafety.PROTECTED_FUNCTIONS
    print(f"Test 4 - Protected functions count: {len(protected_functions)} ✅")
    
    print("\nSafety system validation complete!")
    return True

if __name__ == '__main__':
    test_basic_safety()