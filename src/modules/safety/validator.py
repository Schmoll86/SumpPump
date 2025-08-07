#!/usr/bin/env python3
"""
Safety Validator for SumpPump MCP Server
Prevents accidental trade executions by validating parameters and requiring confirmation.
"""

from typing import Dict, Any, Optional, Tuple, Set, Union
from enum import Enum
from loguru import logger
from datetime import datetime


class ExecutionSafety:
    """
    Safety validator for SumpPump trade execution functions.
    Must be integrated into all trade execution endpoints.
    
    This class implements the safety requirements to prevent accidental
    trade executions by requiring explicit confirmation for immediate
    execution attempts while allowing conditional order setups.
    """
    
    # Functions that ALWAYS require explicit confirmation for immediate execution
    PROTECTED_FUNCTIONS: Set[str] = {
        'trade_execute',
        'trade_buy_to_close',
        'trade_sell_to_close',
        'trade_close_position', 
        'trade_create_conditional_order',
        'trade_modify_order',
        'trade_set_stop_loss',
        'trade_set_price_alert',
        'trade_roll_option'
    }
    
    # Parameters that trigger immediate execution (dangerous if no confirmation)
    IMMEDIATE_EXECUTION_PARAMS: Dict[str, Set[Union[str, bool, int]]] = {
        'trigger_condition': {'immediate', 'now', 'market', 'instant'},
        'order_type': {'MKT', 'MARKET', 'mkt', 'market'},
        'execute_now': {True, 'true', 'yes', '1', 1},
        'skip_confirmation': {True, 'true', 'yes', '1', 1}
    }
    
    # Parameters that indicate this is a setup, not execution (safe without confirmation)
    SETUP_INDICATORS: Dict[str, Union[str, Set[str]]] = {
        'trigger_condition': {'below', 'above', 'at', 'when', 'if', 'greater_than', 'less_than'},
        'trigger_price': 'any_value',  # Presence indicates conditional
        'condition': 'any_value',      # Presence indicates conditional  
        'when': 'any_value',          # Presence indicates conditional
        'conditions': 'any_value'      # Presence indicates conditional
    }
    
    # Required confirmation token
    REQUIRED_CONFIRMATION_TOKEN: str = 'USER_CONFIRMED'
    
    @staticmethod
    def validate_execution_request(
        function_name: str,
        params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if a trade execution request is safe to proceed.
        
        This is the main validation function that should be called before
        any trade execution function is executed.
        
        Args:
            function_name: Name of the function being called
            params: Parameters passed to the function
            
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if safe to proceed, False if blocked
            - error_message: None if valid, error description if blocked
        """
        try:
            # Log the validation attempt
            logger.info(f"[SAFETY] Validating execution request: {function_name}")
            logger.debug(f"[SAFETY] Parameters: {list(params.keys())}")
            
            # Check if this is a protected function
            if function_name not in ExecutionSafety.PROTECTED_FUNCTIONS:
                logger.debug(f"[SAFETY] Function {function_name} not protected, allowing")
                return True, None
                
            # Check if this appears to be a conditional setup (not immediate execution)
            if ExecutionSafety._is_conditional_setup(params):
                logger.info(f"[SAFETY] {function_name} appears to be conditional setup, allowing without confirmation")
                return True, None
                
            # Check for immediate execution indicators
            if ExecutionSafety._has_immediate_execution_params(params):
                # Requires explicit confirmation
                if params.get('confirm_token') != ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN:
                    dangerous_params = ExecutionSafety._identify_dangerous_params(params)
                    error_message = (
                        f"SAFETY CHECK FAILED: {function_name} with immediate execution "
                        f"parameters {dangerous_params} requires explicit confirmation. "
                        f"Add confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}' to proceed with execution."
                    )
                    logger.warning(f"[SAFETY] Blocking {function_name}: {error_message}")
                    return False, error_message
            
            # Check if ANY protected function is called without setup indicators
            # (might be an execution attempt)
            if function_name in {'trade_buy_to_close', 'trade_sell_to_close', 'trade_close_position'}:
                if not ExecutionSafety._is_conditional_setup(params):
                    if params.get('confirm_token') != ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN:
                        error_message = (
                            f"SAFETY CHECK FAILED: {function_name} appears to be an immediate "
                            f"execution attempt. Add confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}' to proceed, "
                            f"or add trigger conditions to make it conditional."
                        )
                        logger.warning(f"[SAFETY] Blocking {function_name}: {error_message}")
                        return False, error_message
            
            logger.info(f"[SAFETY] {function_name} validation passed")
            return True, None
            
        except Exception as e:
            logger.error(f"[SAFETY] Validation error for {function_name}: {e}")
            # Fail safe - block execution if validation fails
            return False, f"Safety validation error: {str(e)}"
    
    @staticmethod
    def _is_conditional_setup(params: Dict[str, Any]) -> bool:
        """
        Check if parameters indicate a conditional order setup (not immediate execution).
        
        Args:
            params: Function parameters to check
            
        Returns:
            True if this appears to be a conditional setup
        """
        # If trigger_condition exists and is NOT immediate
        if 'trigger_condition' in params:
            condition = str(params['trigger_condition']).lower()
            if condition not in {'immediate', 'now', 'market', 'instant'}:
                logger.debug(f"[SAFETY] Found non-immediate trigger_condition: {condition}")
                return True
                
        # If any conditional parameters are present
        conditional_params = {'trigger_price', 'condition', 'when', 'conditions'}
        found_conditional = [param for param in conditional_params if param in params]
        if found_conditional:
            logger.debug(f"[SAFETY] Found conditional parameters: {found_conditional}")
            return True
            
        return False
    
    @staticmethod
    def _has_immediate_execution_params(params: Dict[str, Any]) -> bool:
        """
        Check if parameters would cause immediate execution.
        
        Args:
            params: Function parameters to check
            
        Returns:
            True if parameters indicate immediate execution
        """
        for param_name, dangerous_values in ExecutionSafety.IMMEDIATE_EXECUTION_PARAMS.items():
            if param_name in params:
                param_value = params[param_name]
                if isinstance(param_value, str):
                    param_value = param_value.lower()
                if param_value in dangerous_values:
                    logger.debug(f"[SAFETY] Found dangerous parameter: {param_name}={param_value}")
                    return True
        return False
    
    @staticmethod
    def _identify_dangerous_params(params: Dict[str, Any]) -> list:
        """
        Identify which parameters are dangerous (cause immediate execution).
        
        Args:
            params: Function parameters to check
            
        Returns:
            List of dangerous parameter strings for error messages
        """
        dangerous = []
        for param_name, dangerous_values in ExecutionSafety.IMMEDIATE_EXECUTION_PARAMS.items():
            if param_name in params:
                param_value = params[param_name]
                if isinstance(param_value, str):
                    check_value = param_value.lower()
                else:
                    check_value = param_value
                if check_value in dangerous_values:
                    dangerous.append(f"{param_name}='{param_value}'")
        return dangerous
    
    @staticmethod
    def log_execution_attempt(
        function_name: str,
        params: Dict[str, Any],
        is_valid: bool,
        user_id: Optional[str] = None
    ) -> None:
        """
        Log trade execution attempt for audit trail.
        
        Args:
            function_name: Name of function called
            params: Parameters passed
            is_valid: Whether validation passed
            user_id: Optional user identifier
        """
        try:
            # Create audit entry
            audit_entry = {
                'timestamp': datetime.now().isoformat(),
                'function': function_name,
                'user_id': user_id or 'unknown',
                'validation_result': 'PASSED' if is_valid else 'BLOCKED',
                'has_confirmation': params.get('confirm_token') == ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN,
                'parameter_count': len(params),
                'dangerous_params': ExecutionSafety._identify_dangerous_params(params) if not is_valid else []
            }
            
            # Log based on result
            if is_valid:
                logger.info(f"[AUDIT] Trade execution attempt: {audit_entry}")
            else:
                logger.warning(f"[AUDIT] Blocked trade execution: {audit_entry}")
                
        except Exception as e:
            logger.error(f"[AUDIT] Failed to log execution attempt: {e}")


class ConfirmationRequiredError(Exception):
    """Exception raised when confirmation is required but not provided."""
    
    def __init__(self, function_name: str, dangerous_params: list):
        self.function_name = function_name
        self.dangerous_params = dangerous_params
        super().__init__(
            f"{function_name} requires confirmation due to parameters: {dangerous_params}"
        )


def require_confirmation(func):
    """
    Decorator to require confirmation for any function.
    Use on functions that should NEVER execute without explicit confirmation.
    
    Args:
        func: Function to decorate
        
    Returns:
        Wrapped function that checks for confirmation
    """
    def wrapper(*args, **kwargs):
        if kwargs.get('confirm_token') != ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN:
            return {
                "status": "blocked",
                "error": "CONFIRMATION_REQUIRED", 
                "message": f"{func.__name__} requires confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}'",
                "function": func.__name__,
                "action_required": f"Add confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}' to execute"
            }
        return func(*args, **kwargs)
    return wrapper


# Async version of the decorator
def require_confirmation_async(func):
    """
    Async decorator to require confirmation for any async function.
    
    Args:
        func: Async function to decorate
        
    Returns:
        Wrapped async function that checks for confirmation
    """
    async def wrapper(*args, **kwargs):
        if kwargs.get('confirm_token') != ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN:
            return {
                "status": "blocked",
                "error": "CONFIRMATION_REQUIRED",
                "message": f"{func.__name__} requires confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}'",
                "function": func.__name__,
                "action_required": f"Add confirm_token='{ExecutionSafety.REQUIRED_CONFIRMATION_TOKEN}' to execute"
            }
        return await func(*args, **kwargs)
    return wrapper


# Helper function for safe async sleep (per CLAUDE.md requirements)
async def _async_safe_sleep(seconds: float) -> None:
    """
    Safe async sleep that respects event loop requirements.
    Use this instead of asyncio.sleep() per project requirements.
    
    Args:
        seconds: Time to sleep in seconds
    """
    import asyncio
    # This could be enhanced with proper event loop safety measures
    # For now, use standard asyncio.sleep but log for monitoring
    logger.debug(f"[SAFETY] Safe async sleep for {seconds} seconds")
    await asyncio.sleep(seconds)