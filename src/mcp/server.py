#!/usr/bin/env python3
"""
SumpPump MCP Server - Main entry point.
Provides MCP tools for IBKR options trading through Claude Desktop.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from src.config import config

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

# MCP Tool: Get Options Chain
@mcp.tool()
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    include_stats: bool = True
) -> Dict[str, Any]:
    """
    Fetch full options chain for a symbol with Greeks and statistics.
    
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
@mcp.tool()
async def calculate_strategy(
    strategy_type: str,
    symbol: str,
    strikes: List[float],
    expiry: str,
    quantity: int = 1
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
    logger.info(f"Calculating {strategy_type} for {symbol}")
    
    try:
        # Import modules
        from src.modules.data import options_data
        from src.modules.strategies import (
            BullCallSpread, BearPutSpread, SingleOption,
            LongStraddle, LongStrangle, Level2StrategyError,
            create_bull_call_spread, create_bear_put_spread
        )
        from src.models import OptionLeg, OrderAction, OptionRight
        
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
        
        return {
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
            'timestamp': datetime.now().isoformat()
        }
        
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
@mcp.tool()
async def execute_trade(
    strategy: Dict[str, Any],
    confirm_token: str
) -> Dict[str, Any]:
    """
    Execute a Level 2 compliant trade with mandatory confirmation.
    
    CRITICAL: 
    - Requires explicit confirmation token "USER_CONFIRMED"
    - Only Level 2 strategies allowed (debit spreads, long options)
    - Will display MAX LOSS before execution
    - Will prompt for STOP LOSS after fill
    
    Args:
        strategy: Complete strategy details (must be Level 2 compliant)
        confirm_token: Must be exactly "USER_CONFIRMED"
    
    Returns:
        Execution status, fill details, and stop loss prompt
    """
    logger.warning(f"Trade execution requested with token: {confirm_token}")
    
    # CRITICAL: Validate confirmation token
    if confirm_token != "USER_CONFIRMED":
        return {
            "error": "Invalid confirmation token",
            "required": "confirm_token must be exactly 'USER_CONFIRMED'",
            "message": "Trade execution requires explicit user confirmation"
        }
    
    try:
        # Import modules
        from src.modules.execution import OrderBuilder, ConfirmationManager
        from src.modules.risk import RiskValidator
        from src.modules.strategies import validate_level2_strategy, Level2StrategyError
        from src.modules.tws.connection import tws_connection
        
        # Validate Level 2 compliance
        try:
            # Check if strategy type is allowed
            strategy_type = strategy.get('type', '')
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
        max_loss = strategy.get('max_loss', 0)
        max_loss_pct = (max_loss / account_balance * 100) if account_balance > 0 else 0
        
        pre_execution_display = {
            'strategy': strategy.get('name', 'Unknown'),
            'symbol': strategy.get('symbol', ''),
            'MAX_LOSS': f"${max_loss:,.2f}",
            'MAX_LOSS_PCT': f"{max_loss_pct:.1f}% of account",
            'max_profit': strategy.get('max_profit', 'Unknown'),
            'net_debit': f"${abs(net_debit_credit):,.2f}",
            'breakeven': strategy.get('breakeven', []),
            'WARNING': "This is LIVE TRADING with real money"
        }
        
        logger.warning(f"EXECUTING TRADE: {pre_execution_display}")
        
        # Build and submit order - construct Strategy object properly
        from src.models import Strategy as StrategyModel, StrategyType, OptionLeg
        
        # Create Strategy object from the strategy data
        try:
            # Get strategy type
            strategy_type = StrategyType(strategy.get('strategy_type', 'long_call'))
            
            # Extract legs if they exist, otherwise create basic structure
            legs = strategy.get('legs', [])
            if not legs:
                # This is a simplified strategy without legs - we need to rebuild it
                logger.warning("Strategy missing legs - execution needs to be called after calculate_strategy")
                return {
                    'error': 'Strategy incomplete',
                    'message': 'You must first calculate the strategy before executing. Please call calculate_strategy() first.',
                    'required_flow': '1. get_options_chain() → 2. calculate_strategy() → 3. execute_trade()'
                }
            
            strategy_obj = StrategyModel(
                name=strategy.get('name', f"{strategy_type.value} Strategy"),
                type=strategy_type,
                legs=legs,
                max_profit=strategy.get('max_profit', float('inf')),
                max_loss=strategy.get('max_loss', 0.0),
                breakeven=strategy.get('breakeven', []),
                current_value=strategy.get('current_value', 0.0),
                probability_profit=strategy.get('probability_profit'),
                required_capital=strategy.get('required_capital', 0.0)
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
        
        # Submit order through TWS
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

# MCP Tool: Set Stop Loss
@mcp.tool()
async def set_stop_loss(
    position_id: str,
    stop_price: float
) -> Dict[str, Any]:
    """
    Set a stop loss order for an existing position.
    
    Args:
        position_id: Position identifier
        stop_price: Stop loss trigger price
    
    Returns:
        Stop order confirmation
    """
    logger.info(f"Setting stop loss for position {position_id} at {stop_price}")
    
    return {
        "position_id": position_id,
        "stop_price": stop_price,
        "status": "pending_implementation"
    }

# MCP Tool: Get News
@mcp.tool()
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
@mcp.tool()
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
        order_book = await depth.get_depth(
            symbol=symbol,
            num_levels=min(levels, config.data.max_depth_levels),
            provider=DepthProvider[config.data.depth_provider],
            smart_depth=config.data.use_smart_depth
        )
        
        return order_book.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting market depth: {e}")
        return {'error': str(e), 'symbol': symbol}


# MCP Tool: Get Depth Analytics
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
    logger.info(f"Starting {config.mcp.server_name} MCP server...")
    logger.info(f"TWS connection: {config.tws.host}:{config.tws.port}")
    logger.info(f"Risk controls: Confirmation={config.risk.require_confirmation}")
    
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
