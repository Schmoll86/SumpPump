#!/usr/bin/env python3
"""
SumpPump MCP Server - Main entry point.
Provides MCP tools for IBKR options trading through Claude Desktop.
VERSION: 2.0 - With Session State Management
"""

# Apply nest_asyncio immediately to prevent event loop conflicts
import nest_asyncio
nest_asyncio.apply()

import asyncio
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from src.config import config
from src.modules.safety import ExecutionSafety, _async_safe_sleep

# Import new trading architecture
from src.modules.trading.session import TradingSession, SessionState as TradingSessionState
from src.modules.trading.strategy_manager import get_strategy_manager
from src.modules.trading.analysis_pipeline import PreTradeAnalysisPipeline, AnalysisRequirements
from src.modules.trading.risk_framework import RiskValidationFramework, RiskProfile

# Configure logging
if config.log.log_format == "json":
    logger.add(
        config.log.log_file_path,
        rotation=config.log.log_rotation,
        retention=config.log.log_retention,
        serialize=True,
        level=config.mcp.log_level
    )
else:
    logger.add(
        config.log.log_file_path,
        rotation=config.log.log_rotation,
        retention=config.log.log_retention,
        format="{time} {level} {message}",
        level=config.mcp.log_level
    )

# Initialize MCP server
mcp = FastMCP("sump-pump")

# Session state management for strategies (enhanced with new architecture)
class SessionState:
    """Manages state between MCP tool calls - enhanced with new trading architecture."""
    def __init__(self):
        # Legacy state (for backward compatibility)
        self.current_strategy = None  # BaseStrategy object
        self.current_strategy_dict = None  # Dict representation
        self.current_symbol = None
        self.last_calculated = None
        
        # New architecture components
        self.trading_session: Optional[TradingSession] = None
        self.strategy_manager = get_strategy_manager()
        self.risk_framework = RiskValidationFramework()
        self.active_pipelines: Dict[str, PreTradeAnalysisPipeline] = {}
        
    def save_strategy(self, strategy_obj, strategy_dict, symbol):
        """Save calculated strategy for execution."""
        self.current_strategy = strategy_obj
        self.current_strategy_dict = strategy_dict
        self.current_symbol = symbol
        self.last_calculated = datetime.now()
        
        # Also save to strategy manager if we have a strategy_id
        if 'strategy_id' in strategy_dict and self.strategy_manager:
            try:
                self.strategy_manager.create_strategy(
                    symbol=symbol,
                    strategy_type=strategy_dict.get('strategy_type'),
                    legs=strategy_dict.get('legs', []),
                    strikes=strategy_dict.get('strikes', []),
                    expiry=strategy_dict.get('expiry'),
                    quantity=strategy_dict.get('quantity', 1),
                    max_loss=strategy_dict.get('max_loss_raw', 0),
                    max_profit=strategy_dict.get('max_profit_raw', 0),
                    breakeven=strategy_dict.get('analysis', {}).get('breakeven_points', [])
                )
                logger.info(f"[SESSION] Strategy {strategy_dict['strategy_id']} saved to manager")
            except Exception as e:
                logger.error(f"[SESSION] Failed to save to strategy manager: {e}")
        
        # Detailed logging for debugging
        logger.info(f"[SESSION] Saving strategy for {symbol}")
        logger.info(f"[SESSION] Strategy ID: {strategy_dict.get('strategy_id', 'NO_ID')}")
        logger.info(f"[SESSION] Strategy type: {strategy_dict.get('strategy_type')}")
        logger.info(f"[SESSION] Has legs in dict: {len(strategy_dict.get('legs', [])) > 0}")
        logger.info(f"[SESSION] Strategy object type: {type(strategy_obj).__name__}")
        if hasattr(strategy_obj, 'legs'):
            logger.info(f"[SESSION] Strategy object has {len(strategy_obj.legs)} legs")
        logger.info(f"[SESSION] Max loss: {strategy_dict.get('max_loss_raw')}")
        logger.info(f"[SESSION] Session ID: {id(self)}")
        
    def get_strategy(self):
        """Get saved strategy if available."""
        logger.info(f"[SESSION] Getting strategy from session (ID: {id(self)})")
        
        # Check if we have at least the strategy dict and timestamp
        if self.current_strategy_dict and self.last_calculated:
            # Check if strategy is still fresh (within 5 minutes)
            age = (datetime.now() - self.last_calculated).total_seconds()
            if age < 300:  # 5 minutes
                logger.info(f"[SESSION] Found valid strategy for {self.current_symbol} (age: {age:.1f}s)")
                logger.info(f"[SESSION] Strategy dict has legs: {len(self.current_strategy_dict.get('legs', [])) > 0}")
                # Return the strategy object (may be None) and dict
                return self.current_strategy, self.current_strategy_dict
            else:
                logger.warning(f"[SESSION] Strategy expired (age: {age}s)")
        else:
            logger.warning(f"[SESSION] No strategy in session - dict: {self.current_strategy_dict is not None}, timestamp: {self.last_calculated is not None}")
        return None, None
        
    def clear(self):
        """Clear session state."""
        self.current_strategy = None
        self.current_strategy_dict = None
        self.current_symbol = None
        self.last_calculated = None
        # Don't clear new components - they persist
    
    def get_or_create_trading_session(self, symbol: str) -> TradingSession:
        """Get or create a trading session for a symbol."""
        if not self.trading_session or self.trading_session.context.symbol != symbol:
            self.trading_session = TradingSession(symbol)
            logger.info(f"[SESSION] Created new trading session for {symbol}")
        return self.trading_session
    
    def get_analysis_pipeline(self, symbol: str) -> PreTradeAnalysisPipeline:
        """Get or create analysis pipeline for a symbol."""
        if symbol not in self.active_pipelines:
            session = self.get_or_create_trading_session(symbol)
            self.active_pipelines[symbol] = PreTradeAnalysisPipeline(session)
            logger.info(f"[SESSION] Created analysis pipeline for {symbol}")
        return self.active_pipelines[symbol]

# Global session state
session_state = SessionState()

# Data models for MCP tools
class OptionsChainRequest(BaseModel):
    """Request model for options chain data."""
    symbol: str = Field(..., description="Stock symbol")
    expiry: Optional[str] = Field(None, description="Expiration date (YYYY-MM-DD)")
    include_stats: bool = Field(True, description="Include statistics and Greeks")

class StrategyCalculationRequest(BaseModel):
    """Request model for strategy calculations."""
    strategy_type: str = Field(..., description="Type of options strategy")
    symbol: str = Field(..., description="Stock symbol")
    strikes: List[float] = Field(..., description="Strike prices")
    expiry: str = Field(..., description="Expiration date")
    
class TradeExecutionRequest(BaseModel):
    """Request model for trade execution."""
    strategy: Dict[str, Any] = Field(..., description="Strategy details")
    confirm_token: str = Field(..., description="Confirmation token from user")

# Helper functions for data extraction
def _get_trade_commission(trade) -> float:
    """Extract commission from trade fills."""
    commission = 0.0
    try:
        if hasattr(trade, 'fills') and callable(trade.fills):
            fills = trade.fills()
            if fills:
                for fill in fills:
                    if hasattr(fill, 'commission'):
                        commission += float(fill.commission)
    except Exception as e:
        logger.debug(f"Could not extract commission: {e}")
    return commission

# MCP Tool: Get Options Chain
@mcp.tool(name="trade_get_options_chain")
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    include_stats: bool = True
) -> Dict[str, Any]:
    """
    [TRADING] Fetch IBKR options chain with Greeks for stocks/ETFs.
    Real-time options market data, not file operations.
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL')
        expiry: Optional expiration date filter (YYYY-MM-DD)
        include_stats: Include IV, volume, and other statistics
    
    Returns:
        Complete options chain data with Greeks
    """
    logger.info(f"Fetching options chain for {symbol}")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        # Import the data module
        from src.modules.data import options_data
        
        # Initialize if needed
        await options_data.initialize()
        
        # Fetch the chain
        chain = await options_data.fetch_chain(symbol, expiry)
        
        # Convert to serializable format
        chain_data = []
        for opt in chain:
            chain_data.append({
                'symbol': opt.symbol,
                'strike': opt.strike,
                'expiry': opt.expiry.isoformat(),
                'type': opt.right.value,
                'bid': opt.bid,
                'ask': opt.ask,
                'last': opt.last,
                'volume': opt.volume,
                'open_interest': opt.open_interest,
                'iv': opt.iv,
                'underlying_price': opt.underlying_price,
                'greeks': {
                    'delta': opt.greeks.delta,
                    'gamma': opt.greeks.gamma,
                    'theta': opt.greeks.theta,
                    'vega': opt.greeks.vega,
                    'rho': opt.greeks.rho
                }
            })
        
        result = {
            'symbol': symbol,
            'chain': chain_data,
            'count': len(chain_data),
            'timestamp': datetime.now().isoformat()
        }
        
        # Include statistics if requested
        if include_stats and chain:
            stats = await options_data.get_statistics(symbol)
            result['statistics'] = stats
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch options chain: {e}")
        return {
            'error': str(e),
            'symbol': symbol
        }

# MCP Tool: Calculate Strategy
@mcp.tool(name="trade_calculate_strategy")
async def calculate_strategy(
    strategy_type: str,
    symbol: str,
    strikes: List[Union[float, int, str]],  # Accept multiple types for each strike
    expiry: str,
    quantity: Union[int, str] = 1  # Accept both int and string for coercion
) -> Dict[str, Any]:
    """
    Calculate P&L profile for a Level 2 options strategy.
    
    ALLOWED STRATEGIES:
    - long_call, long_put (single options)
    - bull_call_spread, bear_put_spread (debit spreads)
    - long_straddle, long_strangle (volatility)
    - covered_call, protective_put (require stock)
    
    NOT ALLOWED (Level 3+ required):
    - bull_put_spread, bear_call_spread (credit spreads)
    - cash_secured_put, calendar_spread, diagonal_spread
    
    Args:
        strategy_type: Type of strategy (must be Level 2 compliant)
        symbol: Stock symbol
        strikes: List of strike prices
        expiry: Expiration date (YYYY-MM-DD)
        quantity: Number of contracts (default 1)
    
    Returns:
        Strategy analysis with max profit, max loss, breakeven
    """
    logger.info(f"[CALC] === CALCULATE_STRATEGY CALLED ===")
    logger.info(f"[CALC] Symbol: {symbol}, Type: {strategy_type}, Strikes: {strikes}")
    logger.info(f"[CALC] Session state ID: {id(session_state)}")
    logger.info(f"[CALC] Current session symbol: {session_state.current_symbol}")
    
    try:
        # Import modules
        from src.modules.data import options_data
        from src.modules.strategies import (
            BullCallSpread, BearPutSpread, SingleOption,
            LongStraddle, LongStrangle, Level2StrategyError,
            create_bull_call_spread, create_bear_put_spread
        )
        from src.models import OptionLeg, OrderAction, OptionRight
        from src.modules.utils import coerce_numeric, coerce_integer
        
        # Coerce parameters to proper types
        quantity = coerce_integer(quantity, 'quantity') or quantity
        strikes = [coerce_numeric(s, f'strike[{i}]') or s for i, s in enumerate(strikes)]
        
        # Check if strategy is Level 2 compliant
        level2_strategies = [
            'long_call', 'long_put',
            'bull_call_spread', 'bear_put_spread',
            'long_straddle', 'long_strangle',
            'covered_call', 'protective_put', 'collar',
            'long_iron_condor'
        ]
        
        if strategy_type not in level2_strategies:
            return {
                'error': f"Strategy '{strategy_type}' requires Level 3+ permissions",
                'allowed_strategies': level2_strategies,
                'message': "You have Level 2 permissions. Credit spreads and naked options are not allowed."
            }
        
        # Fetch options data
        await options_data.initialize()
        chain = await options_data.fetch_chain(symbol, expiry)
        
        if not chain:
            return {'error': f"No options data available for {symbol}"}
        
        # Find the relevant contracts
        contracts_by_strike = {}
        for opt in chain:
            key = (opt.strike, opt.right.value)
            contracts_by_strike[key] = opt
        
        # Build strategy based on type
        strategy = None
        
        if strategy_type == 'bull_call_spread' and len(strikes) == 2:
            long_call = contracts_by_strike.get((strikes[0], 'C'))
            short_call = contracts_by_strike.get((strikes[1], 'C'))
            
            if long_call and short_call:
                strategy = await create_bull_call_spread(long_call, short_call, quantity)
        
        elif strategy_type == 'bear_put_spread' and len(strikes) == 2:
            long_put = contracts_by_strike.get((strikes[1], 'P'))  # Higher strike
            short_put = contracts_by_strike.get((strikes[0], 'P'))  # Lower strike
            
            if long_put and short_put:
                strategy = await create_bear_put_spread(long_put, short_put, quantity)
        
        elif strategy_type in ['long_call', 'long_put'] and len(strikes) == 1:
            right = 'C' if strategy_type == 'long_call' else 'P'
            contract = contracts_by_strike.get((strikes[0], right))
            
            if contract:
                leg = OptionLeg(contract, OrderAction.BUY, quantity)
                strategy = SingleOption(leg)
        
        elif strategy_type == 'long_straddle' and len(strikes) == 1:
            call = contracts_by_strike.get((strikes[0], 'C'))
            put = contracts_by_strike.get((strikes[0], 'P'))
            
            if call and put:
                call_leg = OptionLeg(call, OrderAction.BUY, quantity)
                put_leg = OptionLeg(put, OrderAction.BUY, quantity)
                strategy = LongStraddle(call_leg, put_leg)
        
        if not strategy:
            return {
                'error': f"Could not build {strategy_type} with strikes {strikes}",
                'available_strikes': sorted(set(opt.strike for opt in chain))
            }
        
        # Calculate strategy metrics
        max_profit = await strategy.calculate_max_profit()
        max_loss = await strategy.calculate_max_loss()
        breakevens = await strategy.get_breakeven_points()
        probability = await strategy.calculate_probability_of_profit()
        net_debit_credit = await strategy.calculate_net_debit_credit()
        greeks = await strategy.aggregate_greeks()
        
        # Ensure this is a debit strategy (Level 2 requirement)
        if net_debit_credit > 0:
            return {
                'error': "This would be a credit strategy. Level 2 only allows debit strategies.",
                'net_credit': net_debit_credit,
                'message': "You must pay premium upfront with Level 2 permissions."
            }
        
        # Log strategy object details before creating dict
        logger.info(f"[CALC] Building strategy dict for {strategy_type}")
        logger.info(f"[CALC] Strategy object type: {type(strategy).__name__}")
        logger.info(f"[CALC] Strategy has legs attr: {hasattr(strategy, 'legs')}")
        if hasattr(strategy, 'legs'):
            logger.info(f"[CALC] Number of legs: {len(strategy.legs)}")
            for i, leg in enumerate(strategy.legs):
                logger.info(f"[CALC] Leg {i}: {type(leg).__name__} - {leg.action if hasattr(leg, 'action') else 'no action'}")
        
        # Generate unique strategy ID
        strategy_id = str(uuid.uuid4())
        
        # Properly serialize legs data
        serialized_legs = []
        if hasattr(strategy, 'legs'):
            for leg in strategy.legs:
                # Convert leg to dict using appropriate method
                if hasattr(leg, 'to_dict'):
                    serialized_legs.append(leg.to_dict())
                elif hasattr(leg, '__dict__'):
                    # Use asdict for dataclass objects
                    try:
                        serialized_legs.append(asdict(leg))
                    except Exception:
                        # Fallback - convert to dict manually
                        serialized_legs.append({
                            'contract': asdict(leg.contract) if hasattr(leg.contract, '__dict__') else str(leg.contract),
                            'action': leg.action.value if hasattr(leg.action, 'value') else str(leg.action),
                            'quantity': leg.quantity if hasattr(leg, 'quantity') else 1
                        })
                else:
                    # Last resort - basic string conversion
                    logger.warning(f"[CALC] Could not serialize leg: {type(leg).__name__}")
                    serialized_legs.append(str(leg))
        
        # Create the strategy dict with all needed info
        strategy_dict = {
            'strategy_id': strategy_id,  # Add unique ID
            'strategy_type': strategy_type,
            'symbol': symbol,
            'strikes': strikes,
            'expiry': expiry,
            'quantity': quantity,
            'analysis': {
                'max_profit': max_profit if max_profit != float('inf') else 'Unlimited',
                'max_loss': max_loss,
                'breakeven_points': breakevens,
                'probability_of_profit': f"{probability:.1%}" if probability else 'N/A',
                'net_debit': abs(net_debit_credit),
                'greeks': greeks
            },
            'level2_compliant': True,
            'timestamp': datetime.now().isoformat(),
            # Add the strategy object data for execution
            'legs': serialized_legs,  # Use properly serialized legs
            'name': strategy.name if hasattr(strategy, 'name') else f"{strategy_type} Strategy",
            'max_profit_raw': max_profit if max_profit != float('inf') else None,
            'max_loss_raw': max_loss,
            'required_capital': abs(net_debit_credit)
        }
        
        logger.info(f"[CALC] Strategy dict created with {len(strategy_dict.get('legs', []))} legs")
        logger.info(f"[CALC] Calling session_state.save_strategy()")
        
        # Save strategy to session state for execution
        session_state.save_strategy(strategy, strategy_dict, symbol)
        
        logger.info(f"[CALC] Strategy saved to session state")
        
        # Add execution hint
        strategy_dict['ready_to_execute'] = True
        strategy_dict['execute_hint'] = "Strategy calculated and ready. Use trade_execute() with confirmation token to place order."
        
        return strategy_dict
        
    except Level2StrategyError as e:
        return {
            'error': str(e),
            'level2_required': True,
            'message': "This strategy configuration requires Level 3+ permissions"
        }
    except Exception as e:
        logger.error(f"Failed to calculate strategy: {e}")
        return {'error': str(e)}

# MCP Tool: Execute Trade
@mcp.tool(name="trade_execute")
async def execute_trade(
    confirm_token: str,
    strategy: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    [TRADING] Execute live trades through IBKR TWS.
    REAL MONEY - Requires explicit confirmation. Not a simulation.
    
    CRITICAL: 
    - Requires explicit confirmation token "USER_CONFIRMED"
    - Only Level 2 strategies allowed (debit spreads, long options)
    - Will display MAX LOSS before execution
    - Will prompt for STOP LOSS after fill
    
    Args:
        confirm_token: Must be exactly "USER_CONFIRMED"
        strategy: Optional strategy dict (uses saved strategy if not provided)
    
    Returns:
        Execution status, fill details, and stop loss prompt
    """
    logger.warning(f"Trade execution requested with token: {confirm_token}")
    
    # CRITICAL: Safety validation BEFORE execution
    params = {
        'confirm_token': confirm_token,
        'strategy': strategy
    }
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_execute',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_execute', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_execute",
            "action_required": "Add confirm_token='USER_CONFIRMED' to execute"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_execute', params, True)
    
    # Get strategy from session state if not provided
    saved_strategy = None
    logger.info(f"[EXEC] Execute called with strategy param: {strategy is not None}")
    
    if strategy is None:
        logger.info(f"[EXEC] No strategy provided, checking session state")
        saved_strategy, strategy = session_state.get_strategy()
        
        if not strategy:
            logger.error(f"[EXEC] No strategy found in session state")
            return {
                'error': 'No strategy available',
                'message': 'You must first calculate a strategy before executing.',
                'required_flow': '1. get_options_chain() → 2. calculate_strategy() → 3. execute_trade()',
                'hint': 'Call calculate_strategy() with your desired strikes and strategy type first.'
            }
        
        logger.info(f"[EXEC] Using saved strategy for {strategy.get('symbol')}")
        logger.info(f"[EXEC] Saved strategy has {len(strategy.get('legs', []))} legs")
        logger.info(f"[EXEC] Strategy max_loss_raw: {strategy.get('max_loss_raw')}")
        logger.info(f"[EXEC] Strategy analysis.max_loss: {strategy.get('analysis', {}).get('max_loss')}")
        logger.info(f"[EXEC] Strategy required_capital: {strategy.get('required_capital')}")
    else:
        logger.info(f"[EXEC] Using provided strategy with {len(strategy.get('legs', []))} legs")
    
    try:
        # Import modules
        from src.modules.execution import OrderBuilder, ConfirmationManager
        from src.modules.risk import RiskValidator
        from src.modules.strategies import validate_level2_strategy, Level2StrategyError
        from src.modules.tws.connection import tws_connection
        
        # Validate Level 2 compliance
        try:
            # Check if strategy type is allowed
            strategy_type = strategy.get('strategy_type', '')
            forbidden_strategies = [
                'bull_put_spread', 'bear_call_spread',  # Credit spreads
                'cash_secured_put', 'short_put',        # Naked puts
                'short_call',                           # Naked calls
                'calendar_spread', 'diagonal_spread',   # Time spreads
                'butterfly',                             # Complex
                'short_straddle', 'short_strangle'      # Naked volatility
            ]
            
            if strategy_type in forbidden_strategies:
                return {
                    'error': f"Strategy '{strategy_type}' requires Level 3+ permissions",
                    'your_level': 'Level 2',
                    'allowed': 'Only debit spreads and long options',
                    'forbidden': 'No credit spreads or naked options'
                }
            
            # Check for net credit (not allowed)
            net_debit_credit = strategy.get('net_debit_credit', 0)
            if net_debit_credit > 0:  # Positive = credit
                return {
                    'error': 'Credit strategies not allowed with Level 2',
                    'net_credit': net_debit_credit,
                    'message': 'You must pay premium upfront (debit only)'
                }
                
        except Level2StrategyError as e:
            return {
                'error': str(e),
                'level_required': 'Level 3+',
                'your_level': 'Level 2'
            }
        
        # Initialize components
        order_builder = OrderBuilder(tws_connection)
        confirmation_manager = ConfirmationManager()
        risk_validator = RiskValidator()
        
        # Get account info for risk calculations
        account_info = await tws_connection.get_account_info()
        account_balance = account_info.get('net_liquidation', 0)
        
        # Display pre-execution summary with MAX LOSS
        # Use max_loss_raw if available (from saved strategy), fallback to analysis.max_loss
        max_loss = strategy.get('max_loss_raw', 0)
        if max_loss == 0:
            # Try to get from analysis section
            max_loss = strategy.get('analysis', {}).get('max_loss', 0)
        
        # Get net debit from required_capital or analysis
        net_debit = strategy.get('required_capital', 0)
        if net_debit == 0:
            net_debit = strategy.get('analysis', {}).get('net_debit', 0)
        
        max_loss_pct = (abs(max_loss) / account_balance * 100) if account_balance > 0 else 0
        
        pre_execution_display = {
            'strategy': strategy.get('name', 'Unknown'),
            'symbol': strategy.get('symbol', ''),
            'MAX_LOSS': f"${abs(max_loss):,.2f}",
            'MAX_LOSS_PCT': f"{max_loss_pct:.1f}% of account",
            'max_profit': strategy.get('max_profit_raw', strategy.get('analysis', {}).get('max_profit', 'Unknown')),
            'net_debit': f"${abs(net_debit):,.2f}",
            'breakeven': strategy.get('analysis', {}).get('breakeven_points', strategy.get('breakeven', [])),
            'WARNING': "This is LIVE TRADING with real money"
        }
        
        logger.warning(f"EXECUTING TRADE: {pre_execution_display}")
        
        # Build and submit order - construct Strategy object properly
        from src.models import Strategy as StrategyModel, StrategyType, Greeks
        
        # Create Strategy object from the strategy data
        try:
            # Get strategy type
            strategy_type = StrategyType(strategy.get('strategy_type', 'long_call'))
            
            # Extract legs if they exist
            legs_data = strategy.get('legs', [])
            logger.info(f"[EXEC] Extracted {len(legs_data)} legs from strategy dict")
            
            if not legs_data:
                logger.warning(f"[EXEC] No legs in strategy dict, checking saved_strategy object")
                # Try to get from saved strategy object
                if saved_strategy and hasattr(saved_strategy, 'legs'):
                    legs_data = saved_strategy.legs
                    logger.info(f"[EXEC] Retrieved {len(legs_data)} legs from saved strategy object")
                else:
                    logger.error(f"[EXEC] No legs found anywhere - saved_strategy: {saved_strategy is not None}, has legs: {hasattr(saved_strategy, 'legs') if saved_strategy else False}")
                    logger.error(f"[EXEC] Strategy keys: {list(strategy.keys())}")
                    return {
                        'error': 'Strategy incomplete',
                        'message': 'Strategy has no leg information. Please recalculate the strategy.',
                        'required_flow': '1. get_options_chain() → 2. calculate_strategy() → 3. execute_trade()'
                    }
            
            # Convert dict legs to OptionLeg objects
            from src.models import OptionLeg, OptionContract, OptionRight, OrderAction, Greeks
            legs = []
            for leg_data in legs_data:
                # Check if it's already an OptionLeg object (has 'contract' attribute, not key)
                if hasattr(leg_data, 'contract') and hasattr(leg_data, 'action'):
                    legs.append(leg_data)
                    continue
                    
                # It's a dict, need to reconstruct from serialized data
                if isinstance(leg_data, dict):
                    contract_data = leg_data.get('contract', {})
                else:
                    # Unexpected data type
                    logger.error(f"[EXEC] Unexpected leg_data type: {type(leg_data)}")
                    continue
                
                # Create OptionContract from dict
                try:
                    # Parse expiry - handle ISO format and datetime objects
                    expiry_raw = contract_data.get('expiry')
                    if isinstance(expiry_raw, str):
                        # Remove timezone info and parse
                        expiry = datetime.fromisoformat(expiry_raw.replace('Z', '+00:00').split('T')[0] + 'T00:00:00')
                    else:
                        expiry = expiry_raw
                    
                    # Parse right - handle string values 'C'/'P' or 'CALL'/'PUT' or enum
                    right_raw = contract_data.get('right')
                    if isinstance(right_raw, str):
                        if right_raw in ['C', 'CALL']:
                            right = OptionRight.CALL
                        elif right_raw in ['P', 'PUT']:
                            right = OptionRight.PUT
                        else:
                            right = OptionRight(right_raw)
                    else:
                        right = right_raw if right_raw else OptionRight.CALL
                    
                    option_contract = OptionContract(
                        symbol=contract_data.get('symbol', ''),
                        strike=float(contract_data.get('strike', 0)),
                        expiry=expiry,
                        right=right,
                        bid=float(contract_data.get('bid', 0)),
                        ask=float(contract_data.get('ask', 0)),
                        last=float(contract_data.get('last', 0)),
                        volume=int(contract_data.get('volume', 0)),
                        open_interest=int(contract_data.get('open_interest', 0)),
                        iv=float(contract_data.get('iv', 0)),
                        greeks=Greeks(
                            delta=float(contract_data.get('greeks', {}).get('delta', 0)),
                            gamma=float(contract_data.get('greeks', {}).get('gamma', 0)),
                            theta=float(contract_data.get('greeks', {}).get('theta', 0)),
                            vega=float(contract_data.get('greeks', {}).get('vega', 0)),
                            rho=float(contract_data.get('greeks', {}).get('rho', 0)) if contract_data.get('greeks', {}).get('rho') else None
                        ) if contract_data.get('greeks') else Greeks(delta=0, gamma=0, theta=0, vega=0),
                        underlying_price=float(contract_data.get('underlying_price', 0))
                    )
                    
                    # Parse action - handle string 'BUY'/'SELL' or enum
                    action_raw = leg_data.get('action')
                    if isinstance(action_raw, str):
                        if action_raw == 'BUY':
                            action = OrderAction.BUY
                        elif action_raw == 'SELL':
                            action = OrderAction.SELL
                        else:
                            action = OrderAction(action_raw)
                    else:
                        action = action_raw if action_raw else OrderAction.BUY
                    
                    # Create OptionLeg
                    option_leg = OptionLeg(
                        contract=option_contract,
                        action=action,
                        quantity=int(leg_data.get('quantity', 1))
                    )
                    legs.append(option_leg)
                    logger.debug(f"[EXEC] Successfully reconstructed leg: {option_leg.action.value} {option_leg.quantity} {option_contract.symbol} {option_contract.strike}{option_contract.right.value}")
                    
                except Exception as e:
                    logger.error(f"[EXEC] Failed to reconstruct leg from dict: {e}")
                    logger.error(f"[EXEC] Leg data: {leg_data}")
                    continue
            
            logger.info(f"[EXEC] Reconstructed {len(legs)} OptionLeg objects from dict data")
            
            # Use the raw values if available, otherwise get from analysis section
            max_profit_val = strategy.get('max_profit_raw')
            if max_profit_val is None:
                analysis_profit = strategy.get('analysis', {}).get('max_profit', 'Unlimited')
                max_profit_val = float('inf') if analysis_profit == 'Unlimited' else analysis_profit
            
            max_loss_val = strategy.get('max_loss_raw', strategy.get('analysis', {}).get('max_loss', 0.0))
            breakeven_val = strategy.get('analysis', {}).get('breakeven_points', strategy.get('breakeven', []))
            
            strategy_obj = StrategyModel(
                name=strategy.get('name', f"{strategy_type.value} Strategy"),
                type=strategy_type,
                legs=legs,  # Now these are proper OptionLeg objects
                max_profit=max_profit_val,
                max_loss=max_loss_val,
                breakeven=breakeven_val,
                current_value=strategy.get('current_value', 0.0),
                probability_profit=strategy.get('probability_profit'),
                required_capital=strategy.get('required_capital', abs(max_loss_val))
            )
        except Exception as e:
            logger.error(f"Failed to construct Strategy object: {e}")
            return {
                'error': 'Strategy construction failed',
                'message': str(e),
                'hint': 'Make sure you call calculate_strategy() first to build a complete strategy'
            }
        
        # Validate with risk module
        await risk_validator.validate_trade_execution(
            strategy_obj, 
            account_info,
            confirm_token
        )
        
        # Submit order through TWS - route based on number of legs
        if len(strategy_obj.legs) == 1:
            # Single option order (long call or long put)
            logger.info(f"Routing single option order for {strategy_obj.name}")
            result = await tws_connection.place_option_order(
                strategy_obj.legs[0],  # Pass the single leg
                order_type='MKT'  # Use market order by default for single options
            )
        else:
            # Multi-leg strategy (spreads, straddles, etc.)
            logger.info(f"Routing combo order for {strategy_obj.name} with {len(strategy_obj.legs)} legs")
            result = await tws_connection.place_combo_order(strategy_obj)
        
        # MANDATORY: Prompt for stop loss
        stop_loss_prompt = {
            'action_required': 'SET STOP LOSS',
            'message': 'Stop loss order recommended to limit risk',
            'suggested_stops': {
                'conservative': f"10% below entry (${max_loss * 0.1:,.2f} risk)",
                'moderate': f"20% below entry (${max_loss * 0.2:,.2f} risk)",
                'technical': "At key support level"
            },
            'command': 'Use set_stop_loss() with position_id and stop_price'
        }
        
        return {
            'status': 'success',
            'order_id': result.get('order_id'),
            'execution': result,
            'max_loss_displayed': f"${max_loss:,.2f}",
            'stop_loss_prompt': stop_loss_prompt,
            'next_action': 'MUST SET STOP LOSS',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Trade execution failed: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Trade execution failed. No order was placed.'
        }

# Note: trade_set_stop_loss is implemented below with full functionality

# MCP Tool: Get News
@mcp.tool(name="trade_get_news")
async def get_news(
    symbol: str,
    provider: str = 'all',
    num_articles: int = 10
) -> Dict[str, Any]:
    """
    Fetch IBKR news articles for a given symbol.
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL')
        provider: News provider filter ('all', 'dow_jones', 'reuters', etc.)
        num_articles: Number of articles to retrieve (default 10, max 50)
    
    Returns:
        List of news articles with title, summary, date, and provider
    """
    logger.info(f"Fetching news for {symbol} from {provider}")
    
    try:
        # Import TWS connection
        from src.modules.tws.connection import tws_connection
        from src.config import config
        
        # Validate parameters
        if num_articles > 50:
            num_articles = 50
        if num_articles < 1:
            num_articles = 1
        
        # Check if news subscriptions are enabled
        if not config.data.subscribe_to_news:
            return {
                'error': 'News subscriptions are disabled in configuration',
                'symbol': symbol,
                'message': 'Enable SUBSCRIBE_TO_NEWS in environment variables'
            }
        
        # Initialize TWS connection if needed
        if not tws_connection.connected:
            await tws_connection.connect()
        
        # Create stock contract for news request
        from ib_async import Stock
        contract = Stock(symbol, 'SMART', 'USD')
        
        # Get qualified contract from TWS
        qualified_contracts = await tws_connection.ib.qualifyContractsAsync(contract)
        if not qualified_contracts:
            return {
                'error': f'Could not find contract for symbol {symbol}',
                'symbol': symbol,
                'message': 'Verify the symbol is valid and traded'
            }
        
        contract = qualified_contracts[0]
        
        # Request historical news
        news_articles = []
        
        try:
            # Use reqHistoricalNews to get recent news
            # Note: This requires news feed permissions in IBKR account
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)  # Last 7 days
            
            # Format dates for IBKR API (YYYYMMDD HH:MM:SS)
            start_str = start_date.strftime('%Y%m%d %H:%M:%S')
            end_str = end_date.strftime('%Y%m%d %H:%M:%S')
            
            # Request historical news
            historical_news = await tws_connection.ib.reqHistoricalNewsAsync(
                conId=contract.conId,
                providerCodes=provider if provider != 'all' else '',
                startDateTime=start_str,
                endDateTime=end_str,
                totalResults=num_articles
            )
            
            # Process news articles
            if historical_news:
                for news_item in historical_news[:num_articles]:
                    # Get article details if available
                    article_detail = None
                    try:
                        if hasattr(news_item, 'articleId'):
                            article_detail = await tws_connection.ib.reqNewsArticleAsync(
                                providerCode=news_item.providerCode,
                                articleId=news_item.articleId
                            )
                    except Exception as e:
                        logger.warning(f"Could not fetch article detail: {e}")
                    
                    # Build article data
                    article_data = {
                        'title': getattr(news_item, 'headline', 'No title available'),
                        'provider': getattr(news_item, 'providerCode', 'Unknown'),
                        'date': getattr(news_item, 'time', ''),
                        'summary': getattr(news_item, 'summary', ''),
                        'article_id': getattr(news_item, 'articleId', ''),
                    }
                    
                    # Add full article text if available
                    if article_detail and hasattr(article_detail, 'articleText'):
                        # Truncate long articles for readability
                        full_text = article_detail.articleText
                        if len(full_text) > 1000:
                            article_data['summary'] = full_text[:1000] + '...'
                        else:
                            article_data['summary'] = full_text
                    
                    news_articles.append(article_data)
            else:
                # No news data available
                return {
                    'status': 'success',
                    'symbol': symbol,
                    'articles': [],
                    'count': 0,
                    'message': 'No news articles found for this symbol or news feed not available',
                    'timestamp': datetime.now().isoformat()
                }
        
        except Exception as news_error:
            # Handle specific news permission errors
            error_msg = str(news_error).lower()
            if 'news' in error_msg and ('permission' in error_msg or 'subscription' in error_msg):
                return {
                    'error': 'News feed access not available',
                    'symbol': symbol,
                    'message': 'Your IBKR account may not have news feed subscriptions enabled. Check your market data subscriptions.',
                    'suggestion': 'Contact IBKR to enable news feeds or upgrade your market data package'
                }
            else:
                raise news_error
        
        # Return results
        result = {
            'symbol': symbol,
            'provider': provider,
            'articles': news_articles,
            'count': len(news_articles),
            'requested_count': num_articles,
            'timestamp': datetime.now().isoformat()
        }
        
        if not news_articles:
            result['message'] = f'No news articles found for {symbol} in the last 7 days'
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch news for {symbol}: {e}")
        
        # Provide helpful error messages based on error type
        error_msg = str(e).lower()
        if 'connection' in error_msg:
            message = 'TWS connection error. Ensure TWS is running and connected.'
        elif 'permission' in error_msg or 'subscription' in error_msg:
            message = 'News feed permission error. Check your IBKR market data subscriptions.'
        elif 'contract' in error_msg:
            message = f'Invalid symbol: {symbol}. Verify the symbol is correct.'
        else:
            message = 'News request failed. Check TWS connection and permissions.'
        
        return {
            'error': str(e),
            'symbol': symbol,
            'provider': provider,
            'message': message
        }

# MCP Tool: Get Level 2 Depth
@mcp.tool(name="trade_get_market_depth")
async def get_market_depth(
    symbol: str,
    levels: int = 5
) -> Dict[str, Any]:
    """
    Get Level 2 depth of book data (IEX feed).
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL')
        levels: Number of price levels (max 10)
    
    Returns:
        Order book with bid/ask levels and analytics
    """
    logger.info(f"Fetching Level 2 depth for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.depth_of_book import DepthOfBook, DepthProvider
        from src.config import config
        
        if not config.data.use_level2_depth:
            return {
                'error': 'Level 2 depth is disabled',
                'message': 'Enable USE_LEVEL2_DEPTH in environment variables'
            }
        
        await ensure_tws_connected()
        
        depth = DepthOfBook(tws_connection)
        
        # Safely get depth provider enum
        try:
            provider = DepthProvider[config.data.depth_provider.upper()]
        except KeyError:
            logger.warning(f"Invalid depth provider '{config.data.depth_provider}', using IEX")
            provider = DepthProvider.IEX
        
        order_book = await depth.get_depth(
            symbol=symbol,
            num_levels=min(levels, config.data.max_depth_levels),
            provider=provider,
            smart_depth=config.data.use_smart_depth
        )
        
        return order_book.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting market depth: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get Depth Analytics
@mcp.tool(name="trade_get_depth_analytics")
async def get_depth_analytics(symbol: str) -> Dict[str, Any]:
    """
    Get advanced depth analytics including price impact estimates.
    
    Args:
        symbol: Stock symbol
    
    Returns:
        Depth analytics with VWAP estimates and market maker info
    """
    logger.info(f"Calculating depth analytics for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.depth_of_book import DepthOfBook
        
        await ensure_tws_connected()
        
        depth = DepthOfBook(tws_connection)
        analytics = await depth.get_depth_analytics(symbol)
        
        return analytics
        
    except Exception as e:
        logger.error(f"Error getting depth analytics: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get Index Quote
@mcp.tool(name="trade_get_index_quote")
async def get_index_quote(symbol: str) -> Dict[str, Any]:
    """
    Get index quote (SPX, NDX, VIX, etc).
    
    Args:
        symbol: Index symbol
    
    Returns:
        Index quote with price and change data
    """
    logger.info(f"Fetching index quote for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.indices import IndexTrading
        from src.config import config
        
        if not config.data.enable_index_trading:
            return {
                'error': 'Index trading is disabled',
                'message': 'Enable ENABLE_INDEX_TRADING in environment variables'
            }
        
        await ensure_tws_connected()
        
        indices = IndexTrading(tws_connection)
        quote = await indices.get_index_quote(symbol)
        
        return quote.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting index quote: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get Index Options
@mcp.tool(name="trade_get_index_options")
async def get_index_options(
    symbol: str,
    expiry: Optional[str] = None,
    strike_range_pct: float = 0.1
) -> List[Dict[str, Any]]:
    """
    Get index options chain (SPX, NDX, etc).
    
    Args:
        symbol: Index symbol
        expiry: Optional expiry date (YYYY-MM-DD)
        strike_range_pct: Strike range as percentage of spot
    
    Returns:
        List of index option contracts with Greeks
    """
    logger.info(f"Fetching index options for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.indices import IndexTrading
        
        await ensure_tws_connected()
        
        indices = IndexTrading(tws_connection)
        options = await indices.get_index_options(
            symbol=symbol,
            expiry=expiry,
            strike_range_pct=strike_range_pct
        )
        
        return [
            {
                'symbol': opt.symbol,
                'strike': opt.strike,
                'expiry': opt.expiry.isoformat(),
                'right': opt.right.value,
                'bid': opt.bid,
                'ask': opt.ask,
                'last': opt.last,
                'mid': opt.mid_price,
                'iv': opt.iv,
                'volume': opt.volume,
                'multiplier': opt.multiplier,
                'greeks': {
                    'delta': opt.greeks.delta if opt.greeks else None,
                    'gamma': opt.greeks.gamma if opt.greeks else None,
                    'vega': opt.greeks.vega if opt.greeks else None,
                    'theta': opt.greeks.theta if opt.greeks else None
                }
            }
            for opt in options
        ]
        
    except Exception as e:
        logger.error(f"Error getting index options: {e}")
        return [{'error': str(e), 'symbol': symbol}]


# MCP Tool: Get Crypto Quote
@mcp.tool(name="trade_get_crypto_quote")
async def get_crypto_quote(
    symbol: str,
    quote_currency: str = "USD"
) -> Dict[str, Any]:
    """
    Get cryptocurrency quote (BTC, ETH, etc).
    
    Args:
        symbol: Crypto symbol
        quote_currency: Quote currency (USD, EUR, etc)
    
    Returns:
        Crypto quote with 24h change and volume
    """
    logger.info(f"Fetching crypto quote for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.crypto import CryptoTrading, CryptoExchange
        from src.config import config
        
        if not config.data.use_crypto_feed:
            return {
                'error': 'Crypto trading is disabled',
                'message': 'Enable USE_CRYPTO_FEED in environment variables'
            }
        
        await ensure_tws_connected()
        
        crypto = CryptoTrading(
            tws_connection,
            CryptoExchange[config.data.crypto_exchange]
        )
        quote = await crypto.get_crypto_quote(symbol, quote_currency)
        
        return quote.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting crypto quote: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get Crypto Analysis
@mcp.tool(name="trade_analyze_crypto")
async def analyze_crypto(symbol: str) -> Dict[str, Any]:
    """
    Get comprehensive crypto analysis with technicals.
    
    Args:
        symbol: Crypto symbol
    
    Returns:
        Analysis with RSI, moving averages, and recommendation
    """
    logger.info(f"Analyzing crypto {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.crypto import CryptoTrading, CryptoExchange
        from src.config import config
        
        if not config.data.use_crypto_feed:
            return {
                'error': 'Crypto trading is disabled',
                'message': 'Enable USE_CRYPTO_FEED in environment variables'
            }
        
        await ensure_tws_connected()
        
        crypto = CryptoTrading(
            tws_connection,
            CryptoExchange[config.data.crypto_exchange]
        )
        analysis = await crypto.get_crypto_analysis(symbol)
        
        return analysis
        
    except Exception as e:
        logger.error(f"Error analyzing crypto: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get FX Quote
@mcp.tool(name="trade_get_fx_quote")
async def get_fx_quote(pair: str) -> Dict[str, Any]:
    """
    Get forex quote (EURUSD, GBPUSD, etc).
    
    Args:
        pair: Currency pair (6 characters, e.g., 'EURUSD')
    
    Returns:
        FX quote with bid/ask and spread in pips
    """
    logger.info(f"Fetching FX quote for {pair}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.forex import ForexTrading, FXVenue
        from src.config import config
        
        if not config.data.use_fx_feed:
            return {
                'error': 'Forex trading is disabled',
                'message': 'Enable USE_FX_FEED in environment variables'
            }
        
        await ensure_tws_connected()
        
        forex = ForexTrading(
            tws_connection,
            FXVenue[config.data.fx_exchange]
        )
        quote = await forex.get_fx_quote(pair)
        
        return quote.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting FX quote: {e}")
        return {'error': str(e), 'pair': pair}


# MCP Tool: Get FX Analytics
@mcp.tool(name="trade_analyze_fx_pair")
async def analyze_fx_pair(pair: str) -> Dict[str, Any]:
    """
    Get forex pair analysis with technicals and recommendation.
    
    Args:
        pair: Currency pair
    
    Returns:
        FX analysis with trend, ATR, and trading levels
    """
    logger.info(f"Analyzing FX pair {pair}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.forex import ForexTrading, FXVenue
        from src.config import config
        
        if not config.data.use_fx_feed:
            return {
                'error': 'Forex trading is disabled',
                'message': 'Enable USE_FX_FEED in environment variables'
            }
        
        await ensure_tws_connected()
        
        forex = ForexTrading(
            tws_connection,
            FXVenue[config.data.fx_exchange]
        )
        analytics = await forex.get_fx_analytics(pair)
        
        return analytics
        
    except Exception as e:
        logger.error(f"Error analyzing FX pair: {e}")
        return {'error': str(e), 'pair': pair}


# MCP Tool: Get VIX Term Structure
@mcp.tool(name="trade_get_vix_term_structure")
async def get_vix_term_structure() -> List[Dict[str, Any]]:
    """
    Get VIX futures term structure for volatility analysis.
    
    Returns:
        VIX futures curve with contango/backwardation metrics
    """
    logger.info("Fetching VIX term structure")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.data.indices import IndexTrading
        
        await ensure_tws_connected()
        
        indices = IndexTrading(tws_connection)
        term_structure = await indices.get_vix_term_structure()
        
        return term_structure
        
    except Exception as e:
        logger.error(f"Error getting VIX term structure: {e}")
        return [{'error': str(e)}]


# MCP Tool: Get My Positions
@mcp.tool(name="trade_get_positions")
async def get_my_positions() -> Dict[str, Any]:
    """
    [TRADING] Get all IBKR positions with P&L.
    Investment portfolio positions, not file positions.
    
    Returns:
        Dict containing all positions with unrealized P&L, market values, and Greeks
    """
    logger.info("Fetching current positions")
    
    try:
        # Ensure TWS is connected
        await ensure_tws_connected()
        
        from src.modules.tws.connection import tws_connection
        from ib_async import Position, PortfolioItem
        
        # Get positions from TWS
        positions: List[Position] = tws_connection.ib.positions()
        
        # Get portfolio items for P&L data
        portfolio: List[PortfolioItem] = tws_connection.ib.portfolio()
        
        # Build position data
        position_data = []
        total_unrealized_pnl = 0.0
        total_realized_pnl = 0.0
        
        for position in positions:
            # Find matching portfolio item for P&L
            portfolio_item = next(
                (item for item in portfolio if item.contract.conId == position.contract.conId),
                None
            )
            
            # Determine position type
            if position.contract.secType == 'OPT':
                position_type = 'option'
                # Parse option details
                option_details = {
                    'symbol': position.contract.symbol,
                    'strike': position.contract.strike,
                    'expiry': position.contract.lastTradeDateOrContractMonth,
                    'right': position.contract.right,
                    'multiplier': int(position.contract.multiplier or 100)
                }
            elif position.contract.secType == 'STK':
                position_type = 'stock'
                option_details = None
            else:
                position_type = position.contract.secType.lower()
                option_details = None
            
            # Build position entry
            pos_entry = {
                'position_id': str(position.contract.conId),
                'account': position.account,
                'symbol': position.contract.symbol,
                'position_type': position_type,
                'quantity': position.position,
                'avg_cost': position.avgCost,
                'option_details': option_details
            }
            
            # Add P&L data if available
            if portfolio_item:
                pos_entry.update({
                    'market_value': portfolio_item.marketValue,
                    'unrealized_pnl': portfolio_item.unrealizedPNL,
                    'realized_pnl': portfolio_item.realizedPNL,
                    'market_price': portfolio_item.marketPrice
                })
                total_unrealized_pnl += portfolio_item.unrealizedPNL
                total_realized_pnl += portfolio_item.realizedPNL
            
            position_data.append(pos_entry)
        
        return {
            'status': 'success',
            'positions': position_data,
            'position_count': len(position_data),
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_realized_pnl': total_realized_pnl,
            'total_pnl': total_unrealized_pnl + total_realized_pnl,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not retrieve positions. Check TWS connection.'
        }


# MCP Tool: Get Open Orders
@mcp.tool(name="trade_get_open_orders")
async def get_open_orders() -> Dict[str, Any]:
    """
    Get all pending/open orders.
    
    Returns:
        Dict containing all open orders with their status and details
    """
    logger.info("Fetching open orders")
    
    try:
        await ensure_tws_connected()
        
        from src.modules.tws.connection import tws_connection
        from ib_async import Trade, Order, Contract, OrderStatus
        
        # Get all open orders
        open_trades: List[Trade] = tws_connection.ib.openTrades()
        
        # Build order data
        order_data = []
        
        for trade in open_trades:
            order: Order = trade.order
            contract: Contract = trade.contract
            status: OrderStatus = trade.orderStatus
            
            # Determine order details based on type
            order_details = {
                'order_type': order.orderType,
                'action': order.action,
                'quantity': order.totalQuantity,
                'filled': status.filled,
                'remaining': status.remaining,
                'status': status.status
            }
            
            # Add price information based on order type
            if order.orderType == 'LMT':
                order_details['limit_price'] = order.lmtPrice
            elif order.orderType == 'STP':
                order_details['stop_price'] = order.auxPrice
            elif order.orderType == 'TRAIL':
                order_details['trailing_amount'] = order.trailingPercent or order.auxPrice
            
            # Build contract details
            if contract.secType == 'OPT':
                contract_details = {
                    'type': 'option',
                    'symbol': contract.symbol,
                    'strike': contract.strike,
                    'expiry': contract.lastTradeDateOrContractMonth,
                    'right': contract.right
                }
            elif contract.secType == 'STK':
                contract_details = {
                    'type': 'stock',
                    'symbol': contract.symbol
                }
            elif contract.secType == 'BAG':
                contract_details = {
                    'type': 'combo',
                    'symbol': contract.symbol,
                    'legs': len(contract.comboLegs) if contract.comboLegs else 0
                }
            else:
                contract_details = {
                    'type': contract.secType.lower(),
                    'symbol': contract.symbol
                }
            
            # Build order entry
            order_entry = {
                'order_id': order.orderId,
                'perm_id': order.permId,
                'client_id': order.clientId,
                'account': order.account,
                'contract': contract_details,
                'order': order_details,
                'time_in_force': order.tif,
                'submit_time': None,  # OrderStatus doesn't have lastFillTime
                'commission': _get_trade_commission(trade),
                'parent_id': order.parentId if order.parentId else None
            }
            
            order_data.append(order_entry)
        
        # Group orders by parent (for bracket orders)
        parent_orders = {}
        child_orders = []
        
        for order in order_data:
            if order['parent_id']:
                child_orders.append(order)
            else:
                parent_orders[order['order_id']] = order
        
        # Attach children to parents
        for child in child_orders:
            parent_id = child['parent_id']
            if parent_id in parent_orders:
                if 'child_orders' not in parent_orders[parent_id]:
                    parent_orders[parent_id]['child_orders'] = []
                parent_orders[parent_id]['child_orders'].append(child)
        
        return {
            'status': 'success',
            'orders': list(parent_orders.values()),
            'order_count': len(parent_orders),
            'total_orders_with_children': len(order_data),
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch open orders: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not retrieve open orders. Check TWS connection.'
        }


@mcp.tool(name="trade_close_position")
async def close_position(
    symbol: str,
    position_type: str,  # 'call', 'put', 'spread', 'stock'
    quantity: Union[int, str],  # Accept both int and string for coercion
    order_type: str = 'MKT',  # 'MKT' or 'LMT'
    limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    position_id: Optional[str] = None,  # Optional specific position ID
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    [TRADING] Close IBKR trading positions.
    Sell investments to exit trades, not closing files.
    
    Args:
        symbol: Symbol of the position to close
        position_type: Type of position ('call', 'put', 'spread', 'stock')
        quantity: Number of contracts/shares to close
        order_type: Market or limit order
        limit_price: Price for limit orders (accepts float, int, or string)
        position_id: Optional specific position ID to close
    
    Returns:
        Order execution result
    """
    logger.info(f"Closing {position_type} position for {symbol}")
    
    # Coerce numeric types to handle schema validation issues
    from src.modules.utils import coerce_numeric, coerce_integer
    
    # Ensure proper types
    quantity = coerce_integer(quantity, 'quantity') or quantity
    limit_price = coerce_numeric(limit_price, 'limit_price') if limit_price is not None else None
    
    # Validate limit order requirements
    if order_type == 'LMT' and limit_price is None:
        return {
            'status': 'error',
            'error': 'MISSING_LIMIT_PRICE',
            'message': 'Limit orders require limit_price parameter. Use MKT for market orders.',
            'function': 'trade_close_position'
        }
    
    # CRITICAL: Safety validation for position closing
    params = {
        'symbol': symbol,
        'position_type': position_type,
        'quantity': quantity,
        'order_type': order_type,
        'limit_price': limit_price,  # Include for validation
        'confirm_token': confirm_token
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_close_position',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_close_position', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_close_position",
            "action_required": "Add confirm_token='USER_CONFIRMED' for immediate execution"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_close_position', params, True)
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.advanced_orders import close_position as close_position_impl
        from src.modules.execution.verification import check_tws_health, verify_order_executed
        
        # Check TWS health first
        is_healthy, health_report = await check_tws_health(tws_connection)
        if not is_healthy:
            logger.error(f"TWS unhealthy: {health_report['errors']}")
            return {
                'status': 'failed',
                'error': 'TWS_UNHEALTHY',
                'message': f"TWS connection issues: {', '.join(health_report['errors'])}",
                'health_report': health_report
            }
        
        # Get initial positions for verification
        initial_positions = tws_connection.ib.positions()
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        # Execute the close order
        result = await close_position_impl(
            tws_connection,
            symbol,
            position_type,
            quantity,
            order_type,
            limit_price,
            position_id
        )
        
        # If order was placed, verify execution
        if result.get('status') == 'success' and result.get('order_id'):
            logger.info(f"Verifying close position order {result['order_id']}")
            
            verified, verify_msg, verify_details = await verify_order_executed(
                tws_connection,
                result['order_id'],
                symbol,
                quantity,
                initial_positions,
                timeout=10
            )
            
            if verified:
                result['verified'] = True
                result['verification_details'] = verify_details
                logger.info(f"✅ Position close VERIFIED for {symbol}")
            else:
                result['verified'] = False
                result['verification_error'] = verify_msg
                result['status'] = 'unverified'
                logger.warning(f"⚠️ Position close NOT VERIFIED for {symbol}: {verify_msg}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to close position: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Position closing failed. Check TWS connection and position details.'
        }


@mcp.tool(name="trade_set_stop_loss")
async def set_stop_loss(
    position_id: str,
    stop_price: Union[float, int, str],  # Accept multiple types for coercion
    stop_type: str = 'fixed',  # 'fixed' or 'trailing'
    trailing_amount: Optional[Union[float, int, str]] = None,  # For trailing stops (dollars or percent)
    trailing_type: Optional[str] = 'amount',  # 'amount' or 'percent'
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set a stop loss order for an existing position.
    
    Args:
        position_id: Position identifier (contract ID or order ID)
        stop_price: Stop trigger price (for fixed stops) or initial stop (for trailing)
        stop_type: 'fixed' for regular stop, 'trailing' for trailing stop
        trailing_amount: Amount or percent to trail (for trailing stops)
        trailing_type: 'amount' for dollar trailing, 'percent' for percentage
    
    Returns:
        Stop order confirmation
    """
    logger.info(f"Setting {stop_type} stop loss for position {position_id} at {stop_price}")
    
    # CRITICAL: Safety validation for stop loss orders
    params = {
        'position_id': position_id,
        'stop_price': stop_price,
        'stop_type': stop_type,
        'confirm_token': confirm_token
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_set_stop_loss',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_set_stop_loss', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_set_stop_loss",
            "action_required": "Add confirmation if this creates immediate orders"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_set_stop_loss', params, True)
    
    try:
        # Import required modules
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.advanced_orders import set_stop_loss as set_stop_loss_impl
        from src.modules.utils import coerce_numeric
        
        # Coerce numeric types to handle schema validation issues
        stop_price = coerce_numeric(stop_price, 'stop_price') or stop_price
        trailing_amount = coerce_numeric(trailing_amount, 'trailing_amount') if trailing_amount is not None else None
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        # Set the stop loss
        result = await set_stop_loss_impl(
            tws_connection,
            position_id,
            stop_price,
            stop_type,
            trailing_amount,
            trailing_type
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to set stop loss: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Stop loss order failed. Check position ID and stop price.'
        }


@mcp.tool(name="trade_modify_order")
async def modify_order(
    order_id: str,
    new_limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types for coercion
    new_quantity: Optional[Union[int, str]] = None,  # Accept multiple types for coercion
    new_stop_price: Optional[Union[float, int, str]] = None,  # Accept multiple types for coercion
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Modify an existing pending order.
    
    Args:
        order_id: Order ID to modify
        new_limit_price: New limit price (for limit orders)
        new_quantity: New quantity
        new_stop_price: New stop price (for stop orders)
    
    Returns:
        Modification confirmation
    """
    logger.info(f"Modifying order {order_id}")
    
    # CRITICAL: Safety validation for order modification 
    params = {
        'order_id': order_id,
        'new_limit_price': new_limit_price,
        'new_quantity': new_quantity,
        'new_stop_price': new_stop_price,
        'confirm_token': confirm_token
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_modify_order',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_modify_order', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_modify_order",
            "action_required": "Add confirmation for order modifications"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_modify_order', params, True)
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.advanced_orders import modify_order as modify_order_impl
        from src.modules.utils import coerce_numeric, coerce_integer
        
        # Coerce numeric types to handle schema validation issues
        new_limit_price = coerce_numeric(new_limit_price, 'new_limit_price') if new_limit_price is not None else None
        new_quantity = coerce_integer(new_quantity, 'new_quantity') if new_quantity is not None else None
        new_stop_price = coerce_numeric(new_stop_price, 'new_stop_price') if new_stop_price is not None else None
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        result = await modify_order_impl(
            tws_connection,
            order_id,
            new_limit_price,
            new_quantity,
            new_stop_price
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to modify order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Order modification failed. Order may have been filled or cancelled.'
        }


@mcp.tool(name="trade_cancel_order")
async def cancel_order(
    order_id: str,
    cancel_all: bool = False,
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Cancel a pending order or all open orders.
    
    Args:
        order_id: Order ID to cancel (ignored if cancel_all is True)
        cancel_all: Cancel all open orders if True
    
    Returns:
        Cancellation confirmation
    """
    logger.info(f"Cancelling {'all orders' if cancel_all else f'order {order_id}'}")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.advanced_orders import cancel_order as cancel_order_impl
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        result = await cancel_order_impl(
            tws_connection,
            order_id,
            cancel_all
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to cancel order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Order cancellation failed. Order may have already been filled.'
        }


@mcp.tool(name="trade_create_conditional_order")
async def create_conditional_order(
    symbol: str,
    contract_type: str,  # 'STOCK', 'OPTION'
    action: str,  # 'BUY', 'SELL', 'BUY_TO_CLOSE', 'SELL_TO_CLOSE'
    quantity: Union[int, str],  # Accept both int and string for coercion
    order_type: str,  # 'MKT', 'LMT', 'STP', 'STP_LMT'
    conditions: List[Dict[str, Any]],  # List of condition specifications
    limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    stop_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    strike: Optional[Union[float, int, str]] = None,  # Accept multiple types
    expiry: Optional[str] = None,
    right: Optional[str] = None,
    trigger_method: str = 'Last',
    outside_rth: bool = False,
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a conditional order with multiple trigger conditions.
    Perfect for buy-to-close orders on short options.
    
    Args:
        symbol: Underlying symbol
        contract_type: 'STOCK' or 'OPTION'
        action: Order action (BUY, SELL, BUY_TO_CLOSE, SELL_TO_CLOSE)
        quantity: Number of shares/contracts
        order_type: Order type (MKT, LMT, STP, STP_LMT)
        conditions: List of conditions, each dict containing:
            - type: 'price', 'time', 'margin', 'percent_change'
            - operator: 'above', 'below', 'at'
            - value: Trigger value
            - conj_type: 'AND' or 'OR'
        limit_price: Limit price for LMT orders
        stop_price: Stop price for STP orders
        strike: Option strike price
        expiry: Option expiration (YYYYMMDD)
        right: Option right ('C' or 'P')
        trigger_method: How to evaluate price conditions
        outside_rth: Allow triggering outside regular hours
    
    Returns:
        Order confirmation with details
    
    Example for buy-to-close short 645 call:
        create_conditional_order(
            symbol='SPY',
            contract_type='OPTION',
            action='BUY_TO_CLOSE',
            quantity=1,
            order_type='MKT',
            conditions=[{'type': 'price', 'operator': 'above', 'value': 650}],
            strike=645,
            expiry='20250117',
            right='C'
        )
    """
    logger.info(f"Creating conditional {action} order for {symbol}")
    
    # Coerce numeric types to handle schema validation issues
    from src.modules.utils import coerce_numeric, coerce_integer
    
    # Ensure proper types
    quantity = coerce_integer(quantity, 'quantity') or quantity
    limit_price = coerce_numeric(limit_price, 'limit_price') if limit_price is not None else None
    stop_price = coerce_numeric(stop_price, 'stop_price') if stop_price is not None else None
    strike = coerce_numeric(strike, 'strike') if strike is not None else None
    
    # CRITICAL: Safety validation for conditional orders
    params = {
        'action': action,
        'order_type': order_type,
        'conditions': conditions,
        'confirm_token': confirm_token,
        'quantity': quantity,
        'symbol': symbol,
        'limit_price': limit_price,
        'stop_price': stop_price
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_create_conditional_order',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_create_conditional_order', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED", 
            "message": error_message,
            "function": "trade_create_conditional_order",
            "action_required": "Review parameters and add confirmation if needed"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_create_conditional_order', params, True)
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.conditional_orders import create_conditional_order as create_conditional_impl
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        result = await create_conditional_impl(
            tws_connection=tws_connection,
            symbol=symbol,
            contract_type=contract_type,
            action=action,
            quantity=quantity,
            order_type=order_type,
            conditions=conditions,
            limit_price=limit_price,
            stop_price=stop_price,
            strike=strike,
            expiry=expiry,
            right=right,
            trigger_method=trigger_method,
            outside_rth=outside_rth
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to create conditional order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Conditional order creation failed. Check parameters and connection.'
        }


@mcp.tool(name="trade_buy_to_close")
async def buy_to_close_option(
    symbol: str,
    strike: Union[float, int, str],  # Accept multiple types for coercion
    expiry: str,  # YYYYMMDD format
    right: str,  # 'C' for call, 'P' for put
    quantity: Union[int, str],  # Accept both int and string for coercion
    order_type: str = 'MKT',
    limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    trigger_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    trigger_condition: str = 'immediate',  # 'immediate', 'above', 'below'
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a buy-to-close order for a short option position.
    This closes short calls or puts to reduce risk.
    
    Args:
        symbol: Underlying symbol
        strike: Option strike price
        expiry: Option expiration (YYYYMMDD)
        right: 'C' for call, 'P' for put
        quantity: Number of contracts to close
        order_type: 'MKT' or 'LMT'
        limit_price: Limit price if using LMT order
        trigger_price: Price to trigger the order (optional)
        trigger_condition: When to trigger ('immediate', 'above', 'below')
    
    Returns:
        Order confirmation
    
    Example to close short 645 call:
        buy_to_close_option(
            symbol='SPY',
            strike=645,
            expiry='20250117',
            right='C',
            quantity=1
        )
    """
    logger.info(f"Creating buy-to-close order for {quantity} {symbol} {strike}{right}")
    
    # Coerce numeric types to handle schema validation issues
    from src.modules.utils import coerce_numeric, coerce_integer
    
    # Ensure proper types
    strike = coerce_numeric(strike, 'strike') or strike
    quantity = coerce_integer(quantity, 'quantity') or quantity
    limit_price = coerce_numeric(limit_price, 'limit_price') if limit_price is not None else None
    trigger_price = coerce_numeric(trigger_price, 'trigger_price') if trigger_price is not None else None
    
    # CRITICAL: Safety validation BEFORE any execution logic
    params = {
        'trigger_condition': trigger_condition,
        'order_type': order_type,
        'confirm_token': confirm_token,
        'trigger_price': trigger_price,
        'symbol': symbol,
        'quantity': quantity,
        'limit_price': limit_price
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_buy_to_close',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_buy_to_close', params, False)
        return {
            "status": "blocked", 
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_buy_to_close",
            "action_required": "Add confirm_token='USER_CONFIRMED' for immediate execution"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_buy_to_close', params, True)
    
    try:
        from src.modules.tws.connection import tws_connection
        
        # Ensure connection
        await tws_connection.ensure_connected()
        
        if trigger_condition == 'immediate' or trigger_price is None:
            # Place immediate buy-to-close order
            from ib_async import Option, MarketOrder, LimitOrder
            
            # Create option contract
            option = Option(symbol, expiry, strike, right, 'SMART', currency='USD')
            
            # Qualify contract
            qualified = await tws_connection.ib.qualifyContractsAsync(option)
            if qualified:
                option = qualified[0]
            
            # Create order
            if order_type == 'MKT':
                order = MarketOrder('BUY', quantity)
            else:
                if limit_price is None:
                    return {
                        'error': 'Limit price required',
                        'message': 'Limit price must be specified for LMT orders',
                        'status': 'failed'
                    }
                order = LimitOrder('BUY', quantity, limit_price)
            
            # Place order
            trade = tws_connection.ib.placeOrder(option, order)
            
            await _async_safe_sleep(2.0)
            
            return {
                'status': 'success',
                'order_id': trade.order.orderId,
                'action': 'BUY_TO_CLOSE',
                'symbol': symbol,
                'strike': strike,
                'expiry': expiry,
                'right': right,
                'quantity': quantity,
                'order_type': order_type,
                'limit_price': limit_price,
                'message': f'Buy-to-close order placed for {quantity} {symbol} {strike}{right} contracts',
                'timestamp': datetime.now().isoformat()
            }
            
        else:
            # Create conditional buy-to-close order
            from src.modules.execution.conditional_orders import create_buy_to_close_order
            
            # Build trigger conditions
            conditions = [{
                'type': 'price',
                'operator': trigger_condition,
                'value': trigger_price,
                'conj_type': 'AND'
            }]
            
            result = await create_buy_to_close_order(
                tws_connection=tws_connection,
                symbol=symbol,
                strike=strike,
                expiry=expiry,
                right=right,
                quantity=quantity,
                trigger_conditions=conditions,
                order_type=order_type,
                limit_price=limit_price
            )
            return result
            
    except Exception as e:
        logger.error(f"Failed to create buy-to-close order: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Buy-to-close order failed. Check position and parameters.'
        }


@mcp.tool(name="trade_direct_close")
async def direct_close(
    symbol: str,
    position_type: str,  # 'call', 'put', 'stock'
    strike: Optional[Union[float, int, str]] = None,  # Accept multiple types
    right: Optional[str] = None,  # 'C' or 'P'
    quantity: Optional[Union[int, str]] = None,  # Accept multiple types
    order_type: str = 'MKT',
    limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    DIRECT position close with verification. Bypasses problematic layers.
    Use when standard close_position fails.
    
    Args:
        symbol: Symbol to close
        position_type: 'call', 'put', or 'stock'
        strike: Option strike (for options)
        right: 'C' or 'P' (for options)
        quantity: Quantity to close (auto-detect if None)
        order_type: 'MKT' or 'LMT'
        limit_price: Price for limit orders
        confirm_token: Must be 'USER_CONFIRMED'
    
    Returns:
        Verified execution result
    """
    logger.info(f"DIRECT CLOSE: {symbol} {position_type}")
    
    # Safety check
    if confirm_token != 'USER_CONFIRMED':
        return {
            'status': 'blocked',
            'error': 'CONFIRMATION_REQUIRED',
            'message': 'Direct close requires confirm_token="USER_CONFIRMED"'
        }
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.direct_execution import direct_close_position
        
        # Coerce types
        from src.modules.utils import coerce_numeric, coerce_integer
        
        strike = coerce_numeric(strike, 'strike') if strike else None
        quantity = coerce_integer(quantity, 'quantity') if quantity else None
        limit_price = coerce_numeric(limit_price, 'limit_price') if limit_price else None
        
        result = await direct_close_position(
            tws_connection,
            symbol,
            position_type,
            strike=strike,
            right=right,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            bypass_safety=False
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Direct close failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'message': 'Direct close failed. Check TWS connection.'
        }


@mcp.tool(name="trade_emergency_close")
async def emergency_close_all(
    symbol: str,
    confirm_token: str,
    second_confirmation: str
) -> Dict[str, Any]:
    """
    EMERGENCY: Close ALL positions for a symbol using market orders.
    Requires double confirmation for safety.
    
    Args:
        symbol: Symbol to close ALL positions
        confirm_token: Must be 'USER_CONFIRMED'
        second_confirmation: Must be 'YES_CLOSE_ALL'
    
    Returns:
        Results of all position closes
    """
    logger.warning(f"🚨 EMERGENCY CLOSE requested for {symbol}")
    
    # Double safety check
    if confirm_token != 'USER_CONFIRMED' or second_confirmation != 'YES_CLOSE_ALL':
        return {
            'status': 'blocked',
            'error': 'DOUBLE_CONFIRMATION_REQUIRED',
            'message': 'Emergency close requires both confirm_token="USER_CONFIRMED" and second_confirmation="YES_CLOSE_ALL"'
        }
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.direct_execution import emergency_market_close
        
        result = await emergency_market_close(
            tws_connection,
            symbol,
            force=True
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Emergency close failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'message': 'Emergency close failed. Manual intervention required.'
        }


@mcp.tool(name="trade_set_price_alert")
async def set_price_alert(
    symbol: str,
    trigger_price: Union[float, int, str],  # Accept multiple types for coercion
    condition: str = 'above',  # 'above' or 'below'
    action: str = 'notify',  # 'notify', 'close_position', 'place_order'
    action_params: Optional[Dict[str, Any]] = None,
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set a price-triggered alert or action.
    
    Args:
        symbol: Symbol to monitor
        trigger_price: Price level to trigger at
        condition: Trigger when price goes 'above' or 'below'
        action: What to do when triggered
        action_params: Parameters for the action (e.g., order details)
    
    Returns:
        Alert configuration confirmation
    """
    logger.info(f"Setting price alert for {symbol} {condition} {trigger_price}")
    
    try:
        from src.modules.execution.advanced_orders import set_price_alert as set_price_alert_impl
        result = await set_price_alert_impl(
            tws_connection,
            symbol,
            trigger_price,
            condition,
            action,
            action_params
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to set price alert: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Price alert setup failed. Check parameters and TWS connection.'
        }


@mcp.tool(name="trade_roll_option")
async def roll_option_position(
    position_id: str,
    new_strike: Optional[float] = None,
    new_expiry: Optional[str] = None,  # Format: YYYY-MM-DD
    roll_type: str = 'calendar',  # 'calendar', 'diagonal', 'vertical'
    confirm_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Roll an option position to a different strike and/or expiration.
    
    Args:
        position_id: Current position to roll
        new_strike: New strike price (for vertical/diagonal rolls)
        new_expiry: New expiration date (for calendar/diagonal rolls)
        roll_type: Type of roll to perform
    
    Returns:
        Roll execution confirmation with both closing and opening trades
    """
    logger.info(f"Rolling position {position_id} using {roll_type} roll")
    
    # CRITICAL: Safety validation for option rolling (creates new trades)
    params = {
        'position_id': position_id,
        'new_strike': new_strike,
        'new_expiry': new_expiry,
        'roll_type': roll_type,
        'confirm_token': confirm_token
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_roll_option',
        params
    )
    
    if not is_valid:
        ExecutionSafety.log_execution_attempt('trade_roll_option', params, False)
        return {
            "status": "blocked",
            "error": "SAFETY_CHECK_FAILED",
            "message": error_message,
            "function": "trade_roll_option",
            "action_required": "Add confirm_token='USER_CONFIRMED' to execute roll"
        }
    
    # Log successful validation
    ExecutionSafety.log_execution_attempt('trade_roll_option', params, True)
    
    try:
        from src.modules.execution.advanced_orders import roll_option_position as roll_option_impl
        result = await roll_option_impl(
            tws_connection,
            position_id,
            new_strike,
            new_expiry,
            roll_type
        )
        return result
        
    except Exception as e:
        logger.error(f"Failed to roll position: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Position roll failed. Check parameters and market hours.'
        }


# ============================================================================
# ESSENTIAL TRADING TOOLS
# ============================================================================

@mcp.tool(name="trade_get_quote")
async def get_quote(
    symbol: str,
    asset_type: str = 'STK'  # 'STK' for stock, 'OPT' for option
) -> Dict[str, Any]:
    """
    [TRADING] Get real-time quotes from IBKR for stocks/ETFs.
    Live market data for trading decisions, not file quotes.
    
    Args:
        symbol: Stock/ETF symbol (e.g., 'SPY', 'AAPL')
        asset_type: 'STK' for stocks/ETFs, 'OPT' for options
    
    Returns:
        Current price, bid/ask, volume, day change, and market data
    """
    logger.info(f"Fetching quote for {symbol}")
    
    try:
        await ensure_tws_connected()
        from src.modules.tws.connection import tws_connection
        from ib_async import Stock
        
        # Create contract
        if asset_type == 'STK':
            contract = Stock(symbol, 'SMART', 'USD')
        else:
            return {
                'error': 'Option quotes need strike and expiry',
                'message': 'Use trade_get_options_chain for option quotes'
            }
        
        # Qualify contract
        qualified = await tws_connection.ib.qualifyContractsAsync(contract)
        if not qualified:
            return {
                'error': 'Symbol not found',
                'message': f'Could not find {symbol}',
                'status': 'failed'
            }
        contract = qualified[0]
        
        # Request market data snapshot
        ticker = tws_connection.ib.reqMktData(contract, '', snapshot=True)
        
        # Wait for data to populate
        for _ in range(20):  # Try for up to 2 seconds
            await asyncio.sleep(0.1)
            if ticker.last and ticker.last > 0:
                break
        
        # Try reqTickers for more complete data
        tickers = await tws_connection.ib.reqTickersAsync(contract)
        if tickers:
            ticker = tickers[0]
        
        # Calculate day change
        day_change = None
        day_change_pct = None
        if ticker.close and ticker.last:
            day_change = ticker.last - ticker.close
            day_change_pct = (day_change / ticker.close) * 100
        
        # Build response
        quote_data = {
            'status': 'success',
            'symbol': symbol,
            'last': ticker.last or ticker.marketPrice() or 0,
            'bid': ticker.bid if ticker.bid and ticker.bid > 0 else None,
            'ask': ticker.ask if ticker.ask and ticker.ask > 0 else None,
            'bid_size': ticker.bidSize if ticker.bidSize else None,
            'ask_size': ticker.askSize if ticker.askSize else None,
            'volume': ticker.volume if ticker.volume else None,
            'open': ticker.open if ticker.open else None,
            'high': ticker.high if ticker.high else None,
            'low': ticker.low if ticker.low else None,
            'close': ticker.close if ticker.close else None,
            'previous_close': ticker.close,
            'day_change': day_change,
            'day_change_percent': day_change_pct,
            'timestamp': datetime.now().isoformat()
        }
        
        # Add spread calculation
        if quote_data['bid'] and quote_data['ask']:
            quote_data['spread'] = quote_data['ask'] - quote_data['bid']
            quote_data['spread_percent'] = (quote_data['spread'] / quote_data['ask']) * 100
        
        # Cancel market data subscription
        tws_connection.ib.cancelMktData(contract)
        
        return quote_data
        
    except Exception as e:
        logger.error(f"Failed to fetch quote for {symbol}: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': f'Could not fetch quote for {symbol}. Market may be closed or symbol invalid.'
        }


@mcp.tool(name="trade_get_account_summary")
async def get_account_summary() -> Dict[str, Any]:
    """
    [TRADING] Get IBKR account balance, buying power, and margin info.
    Trading account summary, not system account information.
    
    Returns:
        Account summary with balance, buying power, margin cushion, and P&L
    """
    logger.info("Fetching account information")
    
    try:
        await ensure_tws_connected()
        from src.modules.tws.connection import tws_connection
        
        # Use the async account info method
        account_info = await tws_connection.get_account_info()
        
        # Return the account info with success status
        return {
            'status': 'success',
            **account_info,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch account info: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not retrieve account information. Check TWS connection.'
        }


@mcp.tool(name="trade_check_margin_risk")
async def check_margin_risk() -> Dict[str, Any]:
    """
    [TRADING] Check IBKR margin status and margin call risk.
    Trading risk assessment, not system margin checks.
    
    Returns:
        Margin status with risk levels and recommendations
    """
    logger.info("Checking margin status and margin call risk")
    
    try:
        # Get account info first
        account_info = await get_account_summary()
        if account_info.get('status') != 'success':
            return account_info
        
        # Calculate margin health metrics
        net_liq = account_info['net_liquidation']
        cushion = account_info['margin_cushion']
        excess_liq = account_info['excess_liquidity']
        buying_power = account_info['buying_power']
        
        # Determine risk level
        if cushion < 0:
            risk_level = 'MARGIN_CALL'
            risk_color = 'RED'
        elif cushion < 0.05:
            risk_level = 'CRITICAL'
            risk_color = 'RED'
        elif cushion < 0.15:
            risk_level = 'HIGH' 
            risk_color = 'ORANGE'
        elif cushion < 0.30:
            risk_level = 'MODERATE'
            risk_color = 'YELLOW'
        else:
            risk_level = 'LOW'
            risk_color = 'GREEN'
        
        # Calculate loss buffer
        loss_before_margin_call = excess_liq
        loss_percentage_before_call = (loss_before_margin_call / net_liq) * 100 if net_liq > 0 else 0
        
        # Build recommendations
        recommendations = []
        if risk_level in ['MARGIN_CALL', 'CRITICAL']:
            recommendations.extend([
                "URGENT: Close or reduce positions immediately",
                "Consider depositing additional funds",
                "Avoid opening new positions"
            ])
        elif risk_level == 'HIGH':
            recommendations.extend([
                "Reduce position sizes to lower margin usage",
                "Avoid high-margin strategies",
                "Consider taking profits on winning positions"
            ])
        elif risk_level == 'MODERATE':
            recommendations.extend([
                "Monitor positions closely",
                "Be selective with new trades",
                "Keep some cash reserve"
            ])
        else:
            recommendations.extend([
                "Margin levels are healthy",
                "Safe to trade within risk parameters"
            ])
        
        return {
            'status': 'success',
            'risk_level': risk_level,
            'risk_color': risk_color,
            'margin_cushion_percent': cushion * 100,
            'margin_usage_percent': account_info['margin_usage_percent'],
            'excess_liquidity': excess_liq,
            'loss_before_margin_call': loss_before_margin_call,
            'loss_percentage_before_call': loss_percentage_before_call,
            'net_liquidation': net_liq,
            'buying_power': buying_power,
            'position_sizing': {
                'conservative': buying_power * 0.25,
                'moderate': buying_power * 0.5,
                'aggressive': buying_power * 0.75
            },
            'recommendations': recommendations,
            'summary': f"{risk_level} risk: {cushion:.1%} cushion, ${loss_before_margin_call:,.0f} buffer before margin call",
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to check margin status: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not check margin status. Check TWS connection.'
        }


@mcp.tool(name="trade_get_price_history")
async def get_price_history(
    symbol: str,
    duration: str = '5 d',  # '1 d', '5 d', '1 M', '3 M', '1 Y'
    bar_size: str = '1 hour',  # '1 min', '5 mins', '15 mins', '1 hour', '1 day'
    data_type: str = 'TRADES'  # 'TRADES', 'MIDPOINT', 'BID', 'ASK'
) -> Dict[str, Any]:
    """
    [TRADING] Get IBKR historical price data for technical analysis.
    Stock price history for trading, not file history.
    
    Args:
        symbol: Stock/ETF symbol
        duration: Time period ('1 d', '5 d', '1 M', '3 M', '1 Y')
        bar_size: Bar size ('1 min', '5 mins', '15 mins', '1 hour', '1 day')
        data_type: Type of data ('TRADES', 'MIDPOINT', 'BID', 'ASK')
    
    Returns:
        Historical bars with OHLCV data and basic statistics
    """
    logger.info(f"Fetching {duration} price history for {symbol}")
    
    try:
        await ensure_tws_connected()
        from src.modules.tws.connection import tws_connection
        from ib_async import Stock
        
        # Create and qualify contract
        contract = Stock(symbol, 'SMART', 'USD')
        qualified = await tws_connection.ib.qualifyContractsAsync(contract)
        if not qualified:
            return {
                'error': 'Symbol not found',
                'message': f'Could not find {symbol}',
                'status': 'failed'
            }
        contract = qualified[0]
        
        # Request historical data
        bars = await tws_connection.ib.reqHistoricalDataAsync(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=data_type,
            useRTH=True,
            formatDate=1
        )
        
        if not bars:
            return {
                'error': 'No data available',
                'message': f'No historical data available for {symbol}',
                'status': 'failed'
            }
        
        # Convert bars to list
        price_data = []
        for bar in bars:
            price_data.append({
                'time': bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': int(bar.volume) if bar.volume else 0
            })
        
        # Calculate statistics
        closes = [bar['close'] for bar in price_data]
        current_price = closes[-1]
        price_change = current_price - closes[0]
        price_change_pct = (price_change / closes[0]) * 100
        
        # Simple moving averages
        sma_20 = sum(closes[-20:]) / min(20, len(closes))
        sma_50 = sum(closes[-50:]) / min(50, len(closes)) if len(closes) >= 50 else None
        
        return {
            'status': 'success',
            'symbol': symbol,
            'duration': duration,
            'bar_size': bar_size,
            'bar_count': len(price_data),
            'bars': price_data,
            'current_price': current_price,
            'price_change': price_change,
            'price_change_percent': price_change_pct,
            'period_high': max(bar['high'] for bar in price_data),
            'period_low': min(bar['low'] for bar in price_data),
            'sma_20': sma_20,
            'sma_50': sma_50,
            'trend': 'UPTREND' if current_price > sma_20 else 'DOWNTREND',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch price history for {symbol}: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': f'Could not fetch price history for {symbol}. Check symbol and parameters.'
        }


@mcp.tool(name="trade_get_volatility_analysis")
async def get_volatility_analysis(symbol: str) -> Dict[str, Any]:
    """
    [TRADING] Get IBKR volatility metrics with IV rank and HV analysis.
    Options volatility for trading, not system volatility.
    
    Args:
        symbol: Stock/ETF symbol
    
    Returns:
        IV metrics, HV, IV rank, and volatility recommendations
    """
    logger.info(f"Fetching volatility metrics for {symbol}")
    
    try:
        from src.modules.tws.connection import tws_connection
        await ensure_tws_connected()
        
        # Get historical volatility from price history directly
        # Call the get_price_history MCP tool function directly
        history = await get_price_history(symbol, duration='3 M', bar_size='1 day')
        
        # Calculate historical volatility
        closes = []
        if history and history.get('status') == 'success' and 'bars' in history:
            closes = [bar['close'] for bar in history['bars']]
        if len(closes) > 1:
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            daily_volatility = (variance ** 0.5)
            hv_30 = daily_volatility * (252 ** 0.5) * 100  # Annualized
        else:
            hv_30 = 0
        
        # Get current quote for ATM strike
        # Call the get_quote MCP tool function directly
        quote = await get_quote(symbol)
        current_price = quote.get('last', 0) if quote and quote.get('status') == 'success' else 0
        
        # Get options chain for IV
        from src.modules.data import options_data
        await options_data.initialize()
        chain = await options_data.fetch_chain(symbol, None)
        
        # Calculate current IV from ATM options
        current_iv = 0
        if chain and current_price > 0:
            atm_options = []
            for opt in chain:
                strike_diff = abs(opt.strike - current_price)
                if strike_diff < current_price * 0.02:  # Within 2%
                    if opt.iv and opt.iv > 0:
                        atm_options.append(opt.iv)
            
            if atm_options:
                current_iv = sum(atm_options) / len(atm_options) * 100
        
        # Calculate IV rank (simplified estimate)
        estimated_iv_low = hv_30 * 0.8
        estimated_iv_high = hv_30 * 2.0
        
        if estimated_iv_high > estimated_iv_low:
            iv_rank = ((current_iv - estimated_iv_low) / (estimated_iv_high - estimated_iv_low)) * 100
        else:
            iv_rank = 50
        
        iv_rank = max(0, min(100, iv_rank))  # Clamp between 0-100
        
        # Determine IV state and recommendation
        if iv_rank > 80:
            iv_state = 'VERY_HIGH'
            recommendation = 'Good for selling premium (credit spreads, covered calls)'
        elif iv_rank > 50:
            iv_state = 'HIGH'
            recommendation = 'Consider premium selling strategies'
        elif iv_rank > 20:
            iv_state = 'NORMAL'
            recommendation = 'Neutral - both buying and selling viable'
        else:
            iv_state = 'LOW'
            recommendation = 'Good for buying options (debit spreads, long options)'
        
        return {
            'status': 'success',
            'symbol': symbol,
            'implied_volatility': round(current_iv, 2),
            'historical_volatility_30d': round(hv_30, 2),
            'iv_hv_ratio': round(current_iv / hv_30 if hv_30 > 0 else 1, 2),
            'iv_rank': round(iv_rank, 1),
            'iv_state': iv_state,
            'recommendation': recommendation,
            'edge': 'SELL_VOLATILITY' if iv_rank > 70 else 'BUY_VOLATILITY' if iv_rank < 30 else 'NEUTRAL',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch volatility metrics for {symbol}: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': f'Could not fetch volatility metrics for {symbol}.'
        }


@mcp.tool(name="trade_get_watchlist_quotes")
async def get_watchlist_quotes(symbols: List[str]) -> Dict[str, Any]:
    """
    [TRADING] Get IBKR quotes for multiple symbols (watchlist).
    Multiple stock quotes for portfolio monitoring, not file watching.
    
    Args:
        symbols: List of stock/ETF symbols
    
    Returns:
        Quotes for all symbols with summary statistics
    """
    logger.info(f"Fetching quotes for {len(symbols)} symbols")
    
    try:
        from src.modules.tws.connection import tws_connection
        await ensure_tws_connected()
        
        quotes = []
        errors = []
        
        # Fetch each quote
        # Call the get_quote MCP tool function directly
        for symbol in symbols:
            try:
                quote = await get_quote(symbol)
                if quote and quote.get('status') == 'success':
                    quotes.append(quote)
                else:
                    errors.append({'symbol': symbol, 'error': quote.get('error', 'No quote data returned') if quote else 'No quote returned'})
            except Exception as e:
                errors.append({'symbol': symbol, 'error': str(e)})
        
        # Calculate summary statistics
        gainers = sorted([q for q in quotes if q.get('day_change_percent', 0) > 0], 
                        key=lambda x: x.get('day_change_percent', 0), reverse=True)[:3]
        losers = sorted([q for q in quotes if q.get('day_change_percent', 0) < 0], 
                       key=lambda x: x.get('day_change_percent', 0))[:3]
        most_active = sorted([q for q in quotes if q.get('volume', 0) > 0], 
                            key=lambda x: x.get('volume', 0), reverse=True)[:3]
        
        return {
            'status': 'success',
            'quotes': quotes,
            'symbols_requested': len(symbols),
            'symbols_returned': len(quotes),
            'errors': errors,
            'summary': {
                'gainers': [q['symbol'] for q in gainers],
                'losers': [q['symbol'] for q in losers],
                'most_active': [q['symbol'] for q in most_active],
                'average_change_percent': sum(q.get('day_change_percent', 0) for q in quotes) / len(quotes) if quotes else 0
            },
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch multiple quotes: {e}")
        return {
            'error': str(e),
            'status': 'failed',
            'message': 'Could not fetch quotes. Check TWS connection.'
        }


# ============================================================================
# NEW COMPREHENSIVE TRADING TOOLS WITH FULL PIPELINE
# ============================================================================

@mcp.tool(name="trade_analyze_opportunity")
async def analyze_opportunity(
    symbol: str,
    strategy_type: str,
    strikes: List[float],
    expiry: Optional[str] = None,
    run_full_analysis: bool = True
) -> Dict[str, Any]:
    """
    [TRADING] Comprehensive pre-trade analysis with enforced workflow.
    Runs news, volatility, options chain analysis before strategy calculation.
    
    Args:
        symbol: Stock symbol
        strategy_type: Type of strategy to analyze
        strikes: Strike prices for the strategy
        expiry: Option expiry date
        run_full_analysis: Run complete analysis pipeline
        
    Returns:
        Complete analysis with risk assessment
    """
    logger.info(f"[ANALYZE] Starting comprehensive analysis for {symbol}")
    
    try:
        # Get or create trading session
        trading_session = session_state.get_or_create_trading_session(symbol)
        
        # Get analysis pipeline
        pipeline = session_state.get_analysis_pipeline(symbol)
        
        if run_full_analysis:
            # Run complete pre-trade analysis
            from src.modules.tws.connection import tws_connection
            
            # Define MCP tools for pipeline
            # Create wrapper functions for MCP tools to ensure they're callable
            async def _get_news_wrapper(symbol, **kwargs):
                return await get_news(symbol, **kwargs)
            
            async def _get_volatility_wrapper(symbol, **kwargs):
                return await get_volatility_analysis(symbol, **kwargs)
            
            async def _get_options_wrapper(symbol, **kwargs):
                return await get_options_chain(symbol, **kwargs)
            
            async def _calculate_strategy_wrapper(**kwargs):
                return await calculate_strategy(**kwargs)
            
            async def _check_margin_wrapper(**kwargs):
                return await check_margin_risk(**kwargs)
            
            mcp_tools = {
                'trade_get_news': _get_news_wrapper,
                'trade_get_volatility_analysis': _get_volatility_wrapper,
                'trade_get_options_chain': _get_options_wrapper,
                'trade_calculate_strategy': _calculate_strategy_wrapper,
                'trade_check_margin_risk': _check_margin_wrapper
            }
            
            # Run analysis pipeline
            success, analysis_data = await pipeline.run_analysis(
                symbol=symbol,
                tws_connection=tws_connection,
                mcp_tools=mcp_tools
            )
            
            if not success:
                return {
                    'status': 'failed',
                    'error': 'Analysis pipeline failed',
                    'details': analysis_data,
                    'missing_steps': pipeline.get_missing_steps()
                }
        
        # Calculate strategy
        strategy_config = {
            'strategy_type': strategy_type,
            'symbol': symbol,
            'strikes': strikes,
            'expiry': expiry or 'next_monthly',
            'quantity': 1
        }
        
        # Create wrapper for calculate_strategy
        async def _calc_wrapper(**kwargs):
            return await calculate_strategy(**kwargs)
        
        is_valid, strategy_result = await pipeline.validate_strategy(
            strategy_config,
            {'trade_calculate_strategy': _calc_wrapper}
        )
        
        if not is_valid:
            return {
                'status': 'failed',
                'error': 'Strategy validation failed',
                'details': strategy_result
            }
        
        # Get account info for risk check
        from src.modules.tws.connection import tws_connection
        account_info = await tws_connection.get_account_summary()
        
        # Run risk validation
        async def _risk_wrapper(**kwargs):
            return await check_margin_risk(**kwargs)
        
        risk_valid, risk_result = await pipeline.validate_risk(
            strategy_result,
            account_info,
            {'trade_check_margin_risk': _risk_wrapper}
        )
        
        # Create strategy in manager
        if risk_valid and strategy_result:
            strategy_id = session_state.strategy_manager.create_strategy(
                symbol=symbol,
                strategy_type=strategy_type,
                legs=strategy_result.get('legs', []),
                strikes=strikes,
                expiry=expiry or 'next_monthly',
                quantity=1,
                max_loss=strategy_result.get('max_loss', 0),
                max_profit=strategy_result.get('max_profit', 0),
                breakeven=strategy_result.get('breakeven', [])
            )
            
            logger.info(f"[ANALYZE] Created strategy {strategy_id} in manager")
        else:
            strategy_id = None
        
        return {
            'status': 'success',
            'symbol': symbol,
            'strategy_type': strategy_type,
            'strategy_id': strategy_id,
            'session_state': trading_session.get_current_state(),
            'analysis_complete': pipeline._analysis_complete,
            'strategy_details': strategy_result,
            'risk_validation': risk_result,
            'risk_approved': risk_valid,
            'execution_ready': risk_valid and strategy_id is not None,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[ANALYZE] Analysis failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'symbol': symbol
        }


@mcp.tool(name="trade_execute_with_verification")
async def execute_with_verification(
    strategy_id: Optional[str] = None,
    symbol: Optional[str] = None,
    confirm_token: str = None,
    set_stop_loss: bool = True,
    stop_loss_percent: float = 50.0
) -> Dict[str, Any]:
    """
    [TRADING] Execute trade with full verification and stop loss.
    Uses strategy from analysis or session state.
    
    Args:
        strategy_id: Strategy ID from analysis (optional)
        symbol: Symbol if using session strategy (optional)
        confirm_token: Must be 'USER_CONFIRMED'
        set_stop_loss: Automatically set stop loss
        stop_loss_percent: Stop loss at X% of max loss
        
    Returns:
        Execution result with verification
    """
    logger.info(f"[EXECUTE_V2] Starting verified execution")
    
    # Validate confirmation
    if confirm_token != 'USER_CONFIRMED':
        return {
            'status': 'blocked',
            'error': 'CONFIRMATION_REQUIRED',
            'message': "Execution requires confirm_token='USER_CONFIRMED'"
        }
    
    try:
        # Get strategy from manager or session
        strategy = None
        managed_strategy = None
        
        if strategy_id:
            logger.info(f"[EXECUTE_V2] Looking for strategy_id: {strategy_id}")
            managed_strategy = session_state.strategy_manager.get_strategy(strategy_id)
            if managed_strategy:
                logger.info(f"[EXECUTE_V2] Found managed strategy for {managed_strategy.symbol}")
                strategy = {
                    'strategy_type': managed_strategy.strategy_type,
                    'symbol': managed_strategy.symbol,
                    'legs': managed_strategy.legs,
                    'strikes': managed_strategy.strikes,
                    'quantity': managed_strategy.quantity,
                    'max_loss_raw': managed_strategy.max_loss,
                    'max_profit_raw': managed_strategy.max_profit,
                    'analysis': {
                        'breakeven_points': managed_strategy.breakeven
                    }
                }
            else:
                logger.warning(f"[EXECUTE_V2] No managed strategy found for ID: {strategy_id}")
        elif symbol:
            # Try session state
            logger.info(f"[EXECUTE_V2] Looking for strategy by symbol: {symbol}")
            _, strategy = session_state.get_strategy()
            if strategy:
                logger.info(f"[EXECUTE_V2] Found session strategy for {strategy.get('symbol')}")
        else:
            # Try to get any strategy from session
            logger.info(f"[EXECUTE_V2] No strategy_id or symbol provided, checking session")
            _, strategy = session_state.get_strategy()
            if strategy:
                logger.info(f"[EXECUTE_V2] Found session strategy: {strategy.get('strategy_type')} for {strategy.get('symbol')}")
        
        if not strategy:
            # Log what we have in session for debugging
            logger.error(f"[EXECUTE_V2] NO_STRATEGY - Session state ID: {id(session_state)}")
            logger.error(f"[EXECUTE_V2] Current strategy dict: {session_state.current_strategy_dict is not None}")
            logger.error(f"[EXECUTE_V2] Strategy manager has {len(session_state.strategy_manager.active_strategies)} active strategies")
            return {
                'status': 'failed',
                'error': 'NO_STRATEGY',
                'message': 'No strategy found. Calculate a strategy first using trade_calculate_strategy.',
                'hint': 'Strategy must be calculated in the same session. Use trade_calculate_strategy first.'
            }
        
        # Execute using existing trade_execute
        exec_result = await execute_trade(
            confirm_token='USER_CONFIRMED',
            strategy=strategy
        )
        
        if exec_result.get('status') != 'success':
            return exec_result
        
        # Link to strategy manager
        if managed_strategy and exec_result.get('order_id'):
            session_state.strategy_manager.link_position_to_strategy(
                position_id=f"order_{exec_result['order_id']}",
                strategy_id=strategy_id,
                order_id=exec_result['order_id'],
                fill_price=exec_result.get('fill_price')
            )
        
        # Set stop loss if requested
        stop_result = None
        if set_stop_loss and exec_result.get('status') == 'success':
            max_loss = strategy.get('max_loss', 0)
            if max_loss:
                stop_trigger = abs(max_loss) * (stop_loss_percent / 100)
                
                # Set stop loss (simplified - should calculate based on position)
                from src.modules.tws.connection import tws_connection
                # This would need proper implementation
                logger.info(f"[EXECUTE_V2] Would set stop loss at ${stop_trigger:.2f}")
                
                if managed_strategy:
                    session_state.strategy_manager.set_stop_loss(
                        strategy_id=strategy_id,
                        stop_price=stop_trigger,
                        stop_type='dollar_loss'
                    )
        
        return {
            'status': 'success',
            'execution': exec_result,
            'strategy_id': strategy_id,
            'stop_loss_set': stop_result is not None,
            'managed': managed_strategy is not None,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[EXECUTE_V2] Execution failed: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }


@mcp.tool(name="trade_get_session_status")
async def get_session_status(symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    [TRADING] Get current trading session status and active strategies.
    
    Args:
        symbol: Optional symbol to check (checks all if not provided)
        
    Returns:
        Session status and active strategies
    """
    try:
        result = {
            'strategy_manager': session_state.strategy_manager.get_summary(),
            'sessions': {},
            'active_strategies': []
        }
        
        # Get trading session info
        if session_state.trading_session:
            result['sessions'][session_state.trading_session.context.symbol] = \
                session_state.trading_session.get_current_state()
        
        # Get active strategies
        if symbol:
            strategies = session_state.strategy_manager.get_strategies_by_symbol(symbol)
        else:
            strategies = list(session_state.strategy_manager.active_strategies.values())
        
        for strategy in strategies:
            result['active_strategies'].append({
                'strategy_id': strategy.strategy_id,
                'symbol': strategy.symbol,
                'type': strategy.strategy_type,
                'status': strategy.status,
                'pnl': strategy.current_pnl,
                'expires_at': strategy.expires_at.isoformat()
            })
        
        result['timestamp'] = datetime.now().isoformat()
        return result
        
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        return {
            'error': str(e),
            'status': 'failed'
        }


# ============================================================================
# EXTENDED HOURS TRADING TOOLS
# ============================================================================

@mcp.tool(name="trade_place_extended_order")
async def place_extended_order(
    symbol: str,
    action: str,  # BUY or SELL
    quantity: Union[int, str],  # Accept both int and string for coercion
    order_type: str = "LMT",
    limit_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    stop_price: Optional[Union[float, int, str]] = None,  # Accept multiple types
    time_in_force: str = "DAY",
    outside_rth: bool = True,
    good_till_date: Optional[str] = None,
    confirm_token: str = None
) -> Dict[str, Any]:
    """
    [TRADING] Place order with extended hours support (pre-market, after-hours, overnight).
    Follows IBKR best practices for extended trading.
    
    Args:
        symbol: Stock symbol
        action: BUY or SELL
        quantity: Number of shares
        order_type: MKT, LMT, STP, STP_LMT (LMT recommended for extended hours)
        limit_price: Required for LMT orders
        stop_price: Required for STP orders
        time_in_force: DAY, GTC, IOC, GTD, OPG
        outside_rth: Enable trading outside regular hours
        good_till_date: For GTD orders (YYYYMMDD HH:MM:SS)
        confirm_token: Must be 'USER_CONFIRMED'
        
    Returns:
        Order placement result with session info
    """
    logger.info(f"[EXTENDED] Placing extended hours order for {symbol}")
    
    # Validate confirmation
    params = {
        'symbol': symbol,
        'action': action,
        'quantity': quantity,
        'order_type': order_type,
        'outside_rth': outside_rth,
        'confirm_token': confirm_token
    }
    
    is_valid, error_message = ExecutionSafety.validate_execution_request(
        'trade_place_extended_order',
        params
    )
    
    if not is_valid:
        return {
            'status': 'blocked',
            'error': 'SAFETY_CHECK_FAILED',
            'message': error_message,
            'action_required': "Add confirm_token='USER_CONFIRMED'"
        }
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.extended_hours import (
            create_extended_hours_order,
            ExtendedHoursConfig
        )
        
        # Ensure connected
        await ensure_tws_connected()
        
        # Configure for extended hours
        config = ExtendedHoursConfig(
            allow_pre_market=True,
            allow_after_hours=True,
            allow_overnight=False,  # Requires special permission
            limit_order_only=True,  # Safer for extended hours
            max_order_size_extended=500
        )
        
        # Create and place order
        result = await create_extended_hours_order(
            tws_connection=tws_connection,
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            outside_rth=outside_rth,
            good_till_date=good_till_date,
            extended_hours_config=config
        )
        
        return result
        
    except Exception as e:
        logger.error(f"[EXTENDED] Order placement failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'symbol': symbol
        }


@mcp.tool(name="trade_get_extended_schedule")
async def get_extended_schedule() -> Dict[str, Any]:
    """
    [TRADING] Get current extended hours trading schedule and session status.
    Shows pre-market, regular, after-hours, and overnight sessions.
    
    Returns:
        Trading schedule with current session info
    """
    try:
        from src.modules.execution.extended_hours import get_extended_hours_schedule
        
        schedule = get_extended_hours_schedule()
        
        # Add TWS connection status
        from src.modules.tws.connection import tws_connection
        schedule['tws_connected'] = tws_connection.connected
        
        return schedule
        
    except Exception as e:
        logger.error(f"Failed to get schedule: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }


@mcp.tool(name="trade_modify_for_extended")
async def modify_for_extended(
    order_id: int,
    enable_extended: bool = True,
    new_time_in_force: Optional[str] = None,
    confirm_token: str = None
) -> Dict[str, Any]:
    """
    [TRADING] Modify existing order to enable/disable extended hours trading.
    
    Args:
        order_id: Order ID to modify
        enable_extended: Enable or disable extended hours
        new_time_in_force: Optional new TIF (GTC, GTD, etc.)
        confirm_token: Must be 'USER_CONFIRMED'
        
    Returns:
        Modification result
    """
    logger.info(f"[EXTENDED] Modifying order {order_id} for extended hours")
    
    # Validate confirmation
    if confirm_token != 'USER_CONFIRMED':
        return {
            'status': 'blocked',
            'error': 'CONFIRMATION_REQUIRED',
            'message': "Order modification requires confirm_token='USER_CONFIRMED'"
        }
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.execution.extended_hours import modify_for_extended_hours
        
        # Ensure connected
        await ensure_tws_connected()
        
        # Modify order
        result = await modify_for_extended_hours(
            tws_connection=tws_connection,
            order_id=order_id,
            enable_extended=enable_extended,
            new_tif=new_time_in_force
        )
        
        return result
        
    except Exception as e:
        logger.error(f"[EXTENDED] Order modification failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'order_id': order_id
        }


# MCP Tool: Market Scanner
@mcp.tool(name="trade_scan_market")
async def scan_market(
    scan_type: str = "high_iv",
    min_iv_rank: Optional[float] = 50,
    min_volume_ratio: Optional[float] = 2.0,
    min_change_pct: Optional[float] = 3.0,
    symbols: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    [TRADING] Scan market for trading opportunities.
    
    Args:
        scan_type: Type of scan ('high_iv', 'unusual_options', 'momentum', 'opportunities', 'overview')
        min_iv_rank: Minimum IV rank for high_iv scan
        min_volume_ratio: Minimum volume/OI ratio for unusual options
        min_change_pct: Minimum % change for momentum scan
        symbols: List of symbols for opportunities scan
        
    Returns:
        Scan results based on type
    """
    logger.info(f"[SCANNER] Running {scan_type} market scan")
    
    try:
        from src.modules.tws.connection import tws_connection
        from src.modules.scanner import MarketScanner
        
        scanner = MarketScanner(tws_connection)
        
        if scan_type == "high_iv":
            results = await scanner.scan_high_iv_stocks(min_iv_rank or 50)
            return {
                'scan_type': 'high_iv',
                'min_iv_rank': min_iv_rank,
                'results': results,
                'count': len(results)
            }
            
        elif scan_type == "unusual_options":
            results = await scanner.scan_unusual_options_volume(min_volume_ratio or 2.0)
            return {
                'scan_type': 'unusual_options',
                'min_volume_ratio': min_volume_ratio,
                'results': results,
                'count': len(results)
            }
            
        elif scan_type == "momentum":
            results = await scanner.scan_momentum_stocks(min_change_pct or 3.0)
            return {
                'scan_type': 'momentum',
                'min_change_pct': min_change_pct,
                'results': results,
                'count': len(results)
            }
            
        elif scan_type == "opportunities":
            if not symbols:
                symbols = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA']  # Default watchlist
            results = await scanner.scan_options_opportunities(symbols)
            return {
                'scan_type': 'opportunities',
                'symbols': symbols,
                'results': results,
                'count': len(results)
            }
            
        elif scan_type == "overview":
            overview = await scanner.get_market_overview()
            return {
                'scan_type': 'overview',
                'market_data': overview,
                'timestamp': datetime.now().isoformat()
            }
            
        else:
            return {
                'error': f'Unknown scan type: {scan_type}',
                'valid_types': ['high_iv', 'unusual_options', 'momentum', 'opportunities', 'overview']
            }
            
    except Exception as e:
        logger.error(f"[SCANNER] Market scan failed: {e}")
        return {
            'status': 'failed',
            'error': str(e),
            'scan_type': scan_type
        }


# MCP Tool: Get Market Data Feed Status
@mcp.tool(name="trade_check_market_data")
async def check_market_data() -> Dict[str, Any]:
    """
    [TRADING] Check market data feed status and subscriptions.
    
    Returns:
        Market data status and subscription info
    """
    logger.info("[MARKET_DATA] Checking market data feed status")
    
    try:
        from src.modules.tws.connection import tws_connection
        
        if not tws_connection.connected:
            await tws_connection.connect()
            
        ib = tws_connection.ib
        
        # Test market data with multiple symbols
        test_symbols = ['SPY', 'AAPL', 'NVDA']
        results = {}
        
        for symbol in test_symbols:
            from ib_async import Stock
            stock = Stock(symbol, 'SMART', 'USD')
            
            # Qualify contract first
            qualified = await ib.qualifyContractsAsync(stock)
            if qualified:
                stock = qualified[0]
                
                ticker = ib.reqMktData(stock, snapshot=True)
                await asyncio.sleep(2)
                
                results[symbol] = {
                    'bid': ticker.bid,
                    'ask': ticker.ask,
                    'last': ticker.last,
                    'volume': ticker.volume,
                    'status': 'OK' if ticker.bid > 0 and ticker.ask > 0 else 'NO_DATA'
                }
                
                ib.cancelMktData(stock)
            else:
                results[symbol] = {
                    'status': 'CANNOT_QUALIFY',
                    'error': 'Contract could not be qualified'
                }
        
        # Check overall status
        working_feeds = sum(1 for r in results.values() if r.get('status') == 'OK')
        
        return {
            'connected': tws_connection.connected,
            'account': ib.managedAccounts()[0] if ib.managedAccounts() else None,
            'market_data_type': 'LIVE' if working_feeds > 0 else 'DELAYED_OR_NONE',
            'test_results': results,
            'working_feeds': working_feeds,
            'total_tested': len(test_symbols),
            'status': 'OK' if working_feeds == len(test_symbols) else 'PARTIAL' if working_feeds > 0 else 'FAILED',
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[MARKET_DATA] Check failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'connected': False
        }


# ============================================================================
# NEW PORTFOLIO AND POSITION MANAGEMENT TOOLS
# ============================================================================

@mcp.tool
async def trade_get_portfolio_summary() -> Dict[str, Any]:
    """
    Get comprehensive portfolio summary with aggregate P&L and Greeks.
    
    Returns complete portfolio overview including:
    - Total P&L (realized and unrealized)
    - Aggregate Greeks across all positions
    - Position count and distribution
    - Cash and buying power
    - Risk metrics
    
    Returns:
        Portfolio summary with P&L, Greeks, and risk metrics
    """
    from src.modules.data.portfolio import PortfolioAnalyzer
    
    logger.info("[PORTFOLIO] Getting portfolio summary")
    
    try:
        # Ensure connection
        await ensure_tws_connected()
        
        # Get portfolio analyzer
        analyzer = PortfolioAnalyzer()
        
        # Get comprehensive summary
        summary = await analyzer.get_portfolio_summary()
        
        logger.info(f"[PORTFOLIO] Retrieved summary: {summary.positions_count} positions, total P&L: ${summary.total_pnl:,.2f}")
        logger.debug(f"[PORTFOLIO] Greeks - Delta: {summary.greeks.total_delta:.2f}, Theta: {summary.greeks.total_theta:.2f}")
        
        return {
            'status': 'success',
            'account_id': summary.account_id,
            'timestamp': summary.timestamp.isoformat(),
            'positions': {
                'count': summary.positions_count,
                'long_positions': summary.long_positions,
                'short_positions': summary.short_positions,
                'options_positions': summary.options_positions,
                'stock_positions': summary.stock_positions
            },
            'value': {
                'total_value': summary.total_value,
                'total_cash': summary.total_cash,
                'buying_power': summary.buying_power,
                'margin_used': summary.margin_used,
                'available_funds': summary.available_funds
            },
            'pnl': {
                'total_pnl': summary.total_pnl,
                'daily_pnl': summary.daily_pnl,
                'unrealized_pnl': summary.unrealized_pnl,
                'realized_pnl': summary.realized_pnl,
                'pnl_percentage': summary.pnl_percentage
            },
            'greeks': summary.greeks.to_dict() if summary.greeks else None,
            'risk_metrics': {
                'portfolio_beta': summary.portfolio_beta,
                'var_95': summary.var_95,
                'max_drawdown': summary.max_drawdown,
                'sharpe_ratio': summary.sharpe_ratio
            },
            'positions_detail': summary.positions_detail
        }
        
    except Exception as e:
        logger.error(f"[PORTFOLIO] Failed to get summary: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to retrieve portfolio summary'
        }


@mcp.tool
async def trade_get_history(
    symbol: Optional[str] = None,
    days: int = 30,
    include_closed: bool = True,
    include_open: bool = False
) -> Dict[str, Any]:
    """
    Get historical trades and P&L for analysis.
    
    Args:
        symbol: Filter by symbol (None for all)
        days: Number of days of history (default 30)
        include_closed: Include closed trades
        include_open: Include open positions
    
    Returns:
        Historical trades with P&L and performance metrics
    """
    from src.modules.data.trade_history import TradeHistoryAnalyzer
    
    logger.info(f"[HISTORY] Getting trade history - symbol: {symbol}, days: {days}")
    
    try:
        await ensure_tws_connected()
        
        analyzer = TradeHistoryAnalyzer()
        
        # Get trades based on filters
        trades = await analyzer.get_trade_history(
            symbol=symbol,
            days=days,
            include_closed=include_closed,
            include_open=include_open
        )
        
        logger.info(f"[HISTORY] Found {len(trades)} trades in last {days} days")
        
        # Calculate statistics
        stats = await analyzer.calculate_statistics(trades)
        
        logger.debug(f"[HISTORY] Stats - Win rate: {stats.get('win_rate', 0):.1f}%, Avg P&L: ${stats.get('avg_pnl', 0):.2f}")
        
        return {
            'status': 'success',
            'period': f'{days} days',
            'symbol_filter': symbol or 'all',
            'trades_count': len(trades),
            'trades': trades,
            'statistics': stats,
            'performance': {
                'total_pnl': stats.get('total_pnl', 0),
                'win_rate': stats.get('win_rate', 0),
                'average_win': stats.get('average_win', 0),
                'average_loss': stats.get('average_loss', 0),
                'profit_factor': stats.get('profit_factor', 0),
                'max_win': stats.get('max_win', 0),
                'max_loss': stats.get('max_loss', 0),
                'best_symbol': stats.get('best_symbol'),
                'worst_symbol': stats.get('worst_symbol')
            }
        }
        
    except Exception as e:
        logger.error(f"[HISTORY] Failed to get trade history: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to retrieve trade history'
        }


@mcp.tool
async def trade_adjust_position(
    symbol: str,
    adjustment_type: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Adjust existing position (roll, resize, hedge, partial close).
    
    Args:
        symbol: Symbol to adjust
        adjustment_type: Type of adjustment ('roll', 'resize', 'hedge', 'partial_close')
        params: Adjustment parameters specific to type:
            - roll: {'new_expiry': 'YYYYMMDD', 'new_strike': float}
            - resize: {'new_quantity': int}
            - hedge: {'hedge_type': 'protective_put'|'covered_call', 'strike': float}
            - partial_close: {'quantity_to_close': int}
    
    Returns:
        Adjustment result with confirmation required for execution
    """
    from src.modules.execution.position_adjuster import PositionAdjuster
    
    logger.info(f"[ADJUST] Position adjustment requested - {symbol} {adjustment_type}")
    logger.debug(f"[ADJUST] Parameters: {params}")
    
    try:
        await ensure_tws_connected()
        
        # Get current position
        from src.modules.tws.connection import tws_connection
        positions = await tws_connection.get_positions()
        
        position = None
        for pos in positions:
            contract = ensure_contract(pos.contract)
            if contract.symbol == symbol:
                position = pos
                break
        
        if not position:
            logger.warning(f"[ADJUST] No position found for {symbol}")
            return {
                'status': 'error',
                'error': 'No position found',
                'message': f'No open position for {symbol}'
            }
        
        logger.info(f"[ADJUST] Found position: {position.position} contracts")
        
        # Create adjuster
        adjuster = PositionAdjuster()
        
        # Calculate adjustment
        if adjustment_type == 'roll':
            result = await adjuster.calculate_roll(
                position=position,
                new_expiry=params['new_expiry'],
                new_strike=params.get('new_strike')
            )
            
        elif adjustment_type == 'resize':
            result = await adjuster.calculate_resize(
                position=position,
                new_quantity=params['new_quantity']
            )
            
        elif adjustment_type == 'hedge':
            result = await adjuster.calculate_hedge(
                position=position,
                hedge_type=params['hedge_type'],
                strike=params.get('strike')
            )
            
        elif adjustment_type == 'partial_close':
            result = await adjuster.calculate_partial_close(
                position=position,
                quantity_to_close=params['quantity_to_close']
            )
            
        else:
            return {
                'status': 'error',
                'error': 'Invalid adjustment type',
                'valid_types': ['roll', 'resize', 'hedge', 'partial_close']
            }
        
        logger.info(f"[ADJUST] Adjustment calculated - Net cost: ${result.get('net_cost', 0):.2f}")
        logger.debug(f"[ADJUST] Orders to execute: {len(result.get('orders', []))}")
        
        # Generate confirmation token
        import uuid
        confirmation_token = str(uuid.uuid4())
        
        # Store adjustment in session
        session = TradingSession.get_or_create(symbol)
        session.pending_adjustment = {
            'token': confirmation_token,
            'adjustment': result,
            'timestamp': datetime.now()
        }
        
        logger.info(f"[ADJUST] Confirmation token generated: {confirmation_token[:8]}...")
        
        return {
            'status': 'confirmation_required',
            'adjustment_type': adjustment_type,
            'symbol': symbol,
            'current_position': {
                'quantity': position.position,
                'avg_cost': position.avgCost
            },
            'proposed_adjustment': result,
            'confirmation_token': confirmation_token,
            'message': 'Review adjustment and confirm with token to execute'
        }
        
    except Exception as e:
        logger.error(f"[ADJUST] Failed to calculate adjustment: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to calculate position adjustment'
        }


@mcp.tool
async def trade_analyze_greeks() -> Dict[str, Any]:
    """
    Analyze portfolio-wide Greeks with scenario analysis.
    
    Returns comprehensive Greeks analysis including:
    - Aggregate Greeks across all positions
    - Beta-weighted delta (SPY weighted)
    - Greeks by underlying
    - Scenario analysis (market moves)
    - Time decay projection
    
    Returns:
        Portfolio Greeks analysis with scenarios
    """
    from src.modules.risk.greeks_analyzer import GreeksAnalyzer
    
    logger.info("[GREEKS] Starting portfolio Greeks analysis")
    
    try:
        await ensure_tws_connected()
        
        analyzer = GreeksAnalyzer()
        
        # Get current Greeks
        current_greeks = await analyzer.get_portfolio_greeks()
        
        logger.info(f"[GREEKS] Portfolio Delta: {current_greeks.total_delta:.2f}, Theta: {current_greeks.total_theta:.2f}")
        
        # Calculate scenarios
        scenarios = await analyzer.calculate_scenarios()
        
        logger.debug(f"[GREEKS] Calculated {len(scenarios)} market scenarios")
        
        # Time decay projection
        time_decay = await analyzer.project_time_decay(days=5)
        
        # Greeks by underlying
        by_underlying = await analyzer.get_greeks_by_underlying()
        
        logger.info(f"[GREEKS] Analysis complete - {len(by_underlying)} underlyings")
        
        return {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'portfolio_greeks': current_greeks.to_dict(),
            'greeks_by_underlying': by_underlying,
            'scenario_analysis': scenarios,
            'time_decay_projection': time_decay,
            'risk_metrics': {
                'direction_risk': 'bullish' if current_greeks.total_delta > 0 else 'bearish',
                'delta_dollars': current_greeks.total_delta * 100,  # Assuming SPY at 100
                'daily_theta_dollars': current_greeks.total_theta,
                'vega_exposure': current_greeks.total_vega,
                'gamma_risk': 'high' if abs(current_greeks.total_gamma) > 10 else 'moderate'
            },
            'recommendations': await analyzer.get_hedging_recommendations()
        }
        
    except Exception as e:
        logger.error(f"[GREEKS] Analysis failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Failed to analyze portfolio Greeks'
        }


# Initialize TWS connection when needed
async def ensure_tws_connected():
    """Ensure TWS connection is established."""
    from src.modules.tws.connection import tws_connection
    if not tws_connection.connected:
        try:
            logger.info("Establishing TWS connection...")
            await tws_connection.connect()
            logger.info("✅ TWS connection established")
        except Exception as e:
            logger.error(f"Failed to connect to TWS: {e}")
            raise Exception(f"TWS connection failed: {e}")

# Main entry point
def main():
    """Run the MCP server."""
    logger.info("="*60)
    logger.info(f"Starting {config.mcp.server_name} MCP server...")
    logger.info("VERSION: 2.0 - With Session State Management")
    logger.info(f"Session state ID: {id(session_state)}")
    logger.info(f"TWS connection: {config.tws.host}:{config.tws.port}")
    logger.info(f"Risk controls: Confirmation={config.risk.require_confirmation}")
    logger.info("="*60)
    
    try:
        # Run the MCP server
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
