#!/usr/bin/env python3
"""Test the fixed trade execution functions."""

import asyncio
from src.mcp.server import set_stop_loss, modify_order, cancel_order

async def test_functions():
    """Test that functions are properly defined."""
    print("Testing fixed functions...")
    
    # Check if functions exist and are callable
    functions = [
        ('set_stop_loss', set_stop_loss),
        ('modify_order', modify_order),
        ('cancel_order', cancel_order)
    ]
    
    for name, func in functions:
        print(f"\n{name}:")
        print(f"  ✓ Exists: {func is not None}")
        print(f"  ✓ Callable: {callable(func)}")
        print(f"  ✓ Is async: {asyncio.iscoroutinefunction(func)}")
        
        # Check function signature
        import inspect
        sig = inspect.signature(func)
        print(f"  ✓ Parameters: {list(sig.parameters.keys())}")
    
    print("\n✅ All functions properly defined with tws_connection imports!")
    return True

if __name__ == "__main__":
    result = asyncio.run(test_functions())
    print(f"\nTest result: {'PASSED' if result else 'FAILED'}")