"""
Type coercion utilities for MCP parameter handling.
Fixes schema validation issues with numeric types.
"""

from typing import Any, Optional, Union, Dict
from decimal import Decimal
from loguru import logger


def coerce_numeric(value: Any, param_name: str = "value") -> Optional[float]:
    """
    Coerce various numeric representations to float.
    Handles strings, integers, Decimals, and already-float values.
    
    Args:
        value: The value to coerce
        param_name: Name of the parameter for logging
    
    Returns:
        Float value or None if coercion fails
    """
    if value is None:
        return None
    
    # Already a float
    if isinstance(value, float):
        return value
    
    # Integer - convert to float
    if isinstance(value, int):
        return float(value)
    
    # String - try to parse
    if isinstance(value, str):
        try:
            # Remove any whitespace
            cleaned = value.strip()
            # Handle empty strings
            if not cleaned:
                return None
            # Try to convert
            return float(cleaned)
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not convert string '{value}' to float for {param_name}: {e}")
            return None
    
    # Decimal - convert to float
    if isinstance(value, Decimal):
        return float(value)
    
    # Try direct conversion as last resort
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        logger.error(f"Could not coerce {type(value).__name__} to float for {param_name}: {e}")
        return None


def coerce_integer(value: Any, param_name: str = "value") -> Optional[int]:
    """
    Coerce various numeric representations to integer.
    
    Args:
        value: The value to coerce
        param_name: Name of the parameter for logging
    
    Returns:
        Integer value or None if coercion fails
    """
    if value is None:
        return None
    
    # Already an integer
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    
    # Float - convert to int (with warning if fractional part exists)
    if isinstance(value, float):
        if value != int(value):
            logger.warning(f"Converting float {value} to int loses fractional part for {param_name}")
        return int(value)
    
    # String - try to parse
    if isinstance(value, str):
        try:
            cleaned = value.strip()
            if not cleaned:
                return None
            # First try direct int conversion
            return int(cleaned)
        except ValueError:
            # Try float then int (for strings like "10.0")
            try:
                float_val = float(cleaned)
                if float_val != int(float_val):
                    logger.warning(f"Converting string '{value}' to int loses fractional part for {param_name}")
                return int(float_val)
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not convert string '{value}' to int for {param_name}: {e}")
                return None
    
    # Try direct conversion as last resort
    try:
        return int(value)
    except (ValueError, TypeError) as e:
        logger.error(f"Could not coerce {type(value).__name__} to int for {param_name}: {e}")
        return None


def sanitize_mcp_params(params: Dict[str, Any], numeric_fields: Dict[str, type]) -> Dict[str, Any]:
    """
    Sanitize MCP parameters to ensure proper types.
    
    Args:
        params: Raw parameters from MCP
        numeric_fields: Dict mapping field names to expected types (float or int)
    
    Returns:
        Sanitized parameters dict
    """
    sanitized = params.copy()
    
    for field_name, expected_type in numeric_fields.items():
        if field_name in sanitized and sanitized[field_name] is not None:
            if expected_type == float:
                sanitized[field_name] = coerce_numeric(sanitized[field_name], field_name)
            elif expected_type == int:
                sanitized[field_name] = coerce_integer(sanitized[field_name], field_name)
    
    return sanitized


# Predefined field type mappings for common trading parameters
TRADING_NUMERIC_FIELDS = {
    'limit_price': float,
    'stop_price': float,
    'strike': float,
    'trigger_price': float,
    'new_limit_price': float,
    'new_stop_price': float,
    'trailing_amount': float,
    'quantity': int,
    'new_quantity': int,
    'max_contracts': int,
    'volume': int,
}


def sanitize_trading_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to sanitize common trading parameters.
    
    Args:
        params: Raw parameters from MCP
    
    Returns:
        Sanitized parameters with proper numeric types
    """
    return sanitize_mcp_params(params, TRADING_NUMERIC_FIELDS)