"""
Consolidated MCP Tools Implementation
Safe consolidation with 100% backward compatibility
Version: 1.0.0
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class AssetType(Enum):
    """Supported asset types for consolidated tools."""
    STOCK = 'STK'
    INDEX = 'IND'
    OPTION = 'OPT'
    CRYPTO = 'CRYPTO'
    FOREX = 'FX'

class ConsolidationSafety:
    """Safety validators for consolidated tools."""
    
    @staticmethod
    def validate_market_data_params(params: Dict) -> tuple[bool, str]:
        """Validate parameters for market data consolidation."""
        symbols = params.get('symbols')
        asset_type = params.get('asset_type', 'STK')
        
        # Validate symbols
        if not symbols:
            return False, "Symbols parameter is required"
        
        # Ensure symbols is a list
        if isinstance(symbols, str):
            params['symbols'] = [symbols]
        elif not isinstance(symbols, list):
            return False, "Symbols must be string or list"
        
        # Validate asset type
        valid_types = ['STK', 'IND', 'OPT', 'CRYPTO', 'FX']
        if asset_type not in valid_types:
            return False, f"Invalid asset_type. Must be one of: {valid_types}"
        
        return True, "Valid"
    
    @staticmethod
    def validate_portfolio_params(params: Dict) -> tuple[bool, str]:
        """Validate parameters for portfolio consolidation."""
        view = params.get('view', 'positions')
        valid_views = ['positions', 'summary', 'account', 'complete']
        
        if view not in valid_views:
            return False, f"Invalid view. Must be one of: {valid_views}"
        
        return True, "Valid"
    
    @staticmethod
    def validate_close_params(params: Dict) -> tuple[bool, str]:
        """Validate parameters for position close consolidation."""
        close_type = params.get('close_type', 'standard')
        valid_types = ['standard', 'buy_to_close', 'direct', 'emergency']
        
        if close_type not in valid_types:
            return False, f"Invalid close_type. Must be one of: {valid_types}"
        
        # Emergency close requires double confirmation
        if close_type == 'emergency':
            if params.get('confirm_token') != 'USER_CONFIRMED':
                return False, "Emergency close requires confirm_token='USER_CONFIRMED'"
            if params.get('second_confirmation') != 'YES_CLOSE_ALL':
                return False, "Emergency close requires second_confirmation='YES_CLOSE_ALL'"
        
        # All other closes need single confirmation
        elif close_type in ['standard', 'buy_to_close', 'direct']:
            if not params.get('confirm_token'):
                return False, f"{close_type} close requires confirm_token='USER_CONFIRMED'"
        
        return True, "Valid"

class MarketDataConsolidator:
    """Consolidates all quote-related tools."""
    
    @staticmethod
    async def get_market_data(
        symbols: Union[str, List[str]],
        asset_type: str = 'STK',
        include_depth: bool = False,
        include_analytics: bool = False,
        include_news: bool = False
    ) -> Dict[str, Any]:
        """
        Universal market data retrieval tool.
        
        Consolidates:
        - trade_get_quote
        - trade_get_watchlist_quotes
        - trade_get_index_quote
        - trade_get_crypto_quote
        - trade_get_fx_quote
        - trade_get_market_depth (optional)
        - trade_get_depth_analytics (optional)
        """
        try:
            # Normalize symbols to list
            if isinstance(symbols, str):
                symbols = [symbols]
            
            # Validate parameters
            params = {
                'symbols': symbols,
                'asset_type': asset_type
            }
            is_valid, error_msg = ConsolidationSafety.validate_market_data_params(params)
            if not is_valid:
                return {
                    'status': 'error',
                    'error': 'INVALID_PARAMS',
                    'message': error_msg
                }
            
            logger.info(f"[CONSOLIDATED] Getting market data for {len(symbols)} symbols, type: {asset_type}")
            
            # Route to appropriate implementation
            from src.modules.tws.connection import tws_connection
            
            # Single symbol optimization
            if len(symbols) == 1:
                result = await MarketDataConsolidator._get_single_quote(
                    tws_connection, 
                    symbols[0], 
                    asset_type,
                    include_depth,
                    include_analytics
                )
            else:
                result = await MarketDataConsolidator._get_multiple_quotes(
                    tws_connection,
                    symbols,
                    asset_type
                )
            
            # Add optional data
            if include_depth and len(symbols) == 1:
                depth_data = await MarketDataConsolidator._get_depth_data(
                    tws_connection, 
                    symbols[0]
                )
                result['depth'] = depth_data
            
            if include_analytics and len(symbols) == 1:
                analytics = await MarketDataConsolidator._get_depth_analytics(
                    tws_connection, 
                    symbols[0]
                )
                result['analytics'] = analytics
            
            if include_news and len(symbols) == 1:
                news = await MarketDataConsolidator._get_news(
                    tws_connection, 
                    symbols[0]
                )
                result['news'] = news
            
            return result
            
        except Exception as e:
            logger.error(f"[CONSOLIDATED] Market data failed: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to retrieve market data'
            }
    
    @staticmethod
    async def _get_single_quote(tws, symbol, asset_type, include_depth, include_analytics):
        """Get quote for single symbol."""
        # Route based on asset type
        if asset_type == 'STK':
            from src.modules.data.quotes import get_stock_quote
            return await get_stock_quote(tws, symbol)
        elif asset_type == 'IND':
            from src.modules.data.indices import get_index_quote
            return await get_index_quote(tws, symbol)
        elif asset_type == 'CRYPTO':
            from src.modules.data.crypto import get_crypto_quote
            return await get_crypto_quote(tws, symbol)
        elif asset_type == 'FX':
            from src.modules.data.forex import get_fx_quote
            return await get_fx_quote(tws, symbol)
        else:
            return {'error': f'Unsupported asset type: {asset_type}'}
    
    @staticmethod
    async def _get_multiple_quotes(tws, symbols, asset_type):
        """Get quotes for multiple symbols."""
        # Parallel fetch for efficiency
        tasks = []
        for symbol in symbols:
            tasks.append(
                MarketDataConsolidator._get_single_quote(
                    tws, symbol, asset_type, False, False
                )
            )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Format response
        quotes = []
        errors = []
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                errors.append({'symbol': symbol, 'error': str(result)})
            elif result.get('status') == 'error':
                errors.append({'symbol': symbol, 'error': result.get('error')})
            else:
                quotes.append(result)
        
        # Calculate summary statistics
        gainers = sorted([q for q in quotes if q.get('day_change_percent', 0) > 0], 
                        key=lambda x: x.get('day_change_percent', 0), reverse=True)[:3]
        losers = sorted([q for q in quotes if q.get('day_change_percent', 0) < 0], 
                       key=lambda x: x.get('day_change_percent', 0))[:3]
        
        return {
            'status': 'success',
            'quotes': quotes,
            'symbols_requested': len(symbols),
            'symbols_returned': len(quotes),
            'errors': errors,
            'summary': {
                'gainers': [q.get('symbol') for q in gainers],
                'losers': [q.get('symbol') for q in losers],
                'average_change': sum(q.get('day_change_percent', 0) for q in quotes) / len(quotes) if quotes else 0
            },
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    async def _get_depth_data(tws, symbol):
        """Get Level 2 market depth."""
        from src.modules.data.depth_of_book import get_market_depth
        return await get_market_depth(tws, symbol)
    
    @staticmethod
    async def _get_depth_analytics(tws, symbol):
        """Get depth analytics."""
        from src.modules.data.depth_of_book import analyze_depth
        return await analyze_depth(tws, symbol)
    
    @staticmethod
    async def _get_news(tws, symbol):
        """Get news for symbol."""
        # Implementation would go here
        return []

class PortfolioConsolidator:
    """Consolidates portfolio-related tools."""
    
    @staticmethod
    async def get_portfolio(
        view: str = 'positions',
        include_greeks: bool = False,
        include_history: bool = False,
        symbol_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Universal portfolio information tool.
        
        Consolidates:
        - trade_get_positions
        - trade_get_account_summary
        - trade_get_portfolio_summary
        """
        try:
            # Validate parameters
            params = {'view': view}
            is_valid, error_msg = ConsolidationSafety.validate_portfolio_params(params)
            if not is_valid:
                return {
                    'status': 'error',
                    'error': 'INVALID_PARAMS',
                    'message': error_msg
                }
            
            logger.info(f"[CONSOLIDATED] Getting portfolio view: {view}")
            
            from src.modules.tws.connection import tws_connection
            await tws_connection.ensure_connected()
            
            # Route based on view type
            if view == 'positions':
                return await PortfolioConsolidator._get_positions(
                    tws_connection, 
                    symbol_filter
                )
            elif view == 'account':
                return await PortfolioConsolidator._get_account_summary(
                    tws_connection
                )
            elif view == 'summary':
                return await PortfolioConsolidator._get_portfolio_summary(
                    tws_connection,
                    include_greeks
                )
            elif view == 'complete':
                # Get everything
                positions = await PortfolioConsolidator._get_positions(
                    tws_connection, 
                    symbol_filter
                )
                account = await PortfolioConsolidator._get_account_summary(
                    tws_connection
                )
                summary = await PortfolioConsolidator._get_portfolio_summary(
                    tws_connection,
                    include_greeks
                )
                
                return {
                    'status': 'success',
                    'positions': positions.get('positions', []),
                    'account': account,
                    'summary': summary,
                    'timestamp': datetime.now().isoformat()
                }
            
        except Exception as e:
            logger.error(f"[CONSOLIDATED] Portfolio retrieval failed: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to retrieve portfolio data'
            }
    
    @staticmethod
    async def _get_positions(tws, symbol_filter=None):
        """Get current positions."""
        positions = tws.ib.positions()
        
        # Filter if requested
        if symbol_filter:
            positions = [p for p in positions if p.contract.symbol == symbol_filter]
        
        # Format positions
        formatted = []
        for pos in positions:
            formatted.append({
                'symbol': pos.contract.symbol,
                'position': pos.position,
                'avg_cost': pos.avgCost,
                'market_value': pos.marketValue if hasattr(pos, 'marketValue') else None,
                'unrealized_pnl': pos.unrealizedPNL if hasattr(pos, 'unrealizedPNL') else None
            })
        
        return {
            'status': 'success',
            'positions': formatted,
            'count': len(formatted)
        }
    
    @staticmethod
    async def _get_account_summary(tws):
        """Get account summary."""
        account_values = tws.ib.accountValues()
        account_summary = tws.ib.accountSummary()
        
        # Extract key values
        summary = {
            'status': 'success',
            'net_liquidation': 0,
            'total_cash': 0,
            'buying_power': 0,
            'account_values': {}
        }
        
        for value in account_values:
            if value.tag == 'NetLiquidation':
                summary['net_liquidation'] = float(value.value)
            elif value.tag == 'TotalCashValue':
                summary['total_cash'] = float(value.value)
            elif value.tag == 'BuyingPower':
                summary['buying_power'] = float(value.value)
            
            summary['account_values'][value.tag] = value.value
        
        return summary
    
    @staticmethod
    async def _get_portfolio_summary(tws, include_greeks):
        """Get comprehensive portfolio summary."""
        from src.modules.data.portfolio import PortfolioAnalyzer
        
        analyzer = PortfolioAnalyzer()
        summary = await analyzer.get_portfolio_summary()
        
        result = {
            'status': 'success',
            'total_value': summary.total_value,
            'total_pnl': summary.total_pnl,
            'positions_count': summary.positions_count
        }
        
        if include_greeks and summary.greeks:
            result['greeks'] = summary.greeks.to_dict()
        
        return result

class ClosePositionConsolidator:
    """Consolidates position closing tools."""
    
    @staticmethod
    async def close_positions(
        symbol: str,
        close_type: str = 'standard',
        **kwargs
    ) -> Dict[str, Any]:
        """
        Universal position closing tool.
        
        Consolidates:
        - trade_close_position
        - trade_buy_to_close
        - trade_direct_close
        - trade_emergency_close
        
        Routes to appropriate implementation based on close_type.
        """
        try:
            # Build params for validation
            params = {
                'symbol': symbol,
                'close_type': close_type,
                'confirm_token': kwargs.get('confirm_token'),
                'second_confirmation': kwargs.get('second_confirmation')
            }
            
            # Validate parameters
            is_valid, error_msg = ConsolidationSafety.validate_close_params(params)
            if not is_valid:
                return {
                    'status': 'blocked',
                    'error': 'SAFETY_CHECK_FAILED',
                    'message': error_msg
                }
            
            logger.info(f"[CONSOLIDATED] Closing position - type: {close_type}, symbol: {symbol}")
            
            # Route to appropriate implementation
            if close_type == 'standard':
                from src.modules.execution.advanced_orders import close_position
                return await close_position(**kwargs)
            
            elif close_type == 'buy_to_close':
                from src.modules.execution.conditional_orders import create_buy_to_close_order
                return await create_buy_to_close_order(**kwargs)
            
            elif close_type == 'direct':
                from src.modules.execution.direct_execution import direct_close_position
                return await direct_close_position(**kwargs)
            
            elif close_type == 'emergency':
                from src.modules.execution.direct_execution import emergency_market_close
                return await emergency_market_close(symbol=symbol, force=True)
            
            else:
                return {
                    'status': 'error',
                    'error': 'INVALID_CLOSE_TYPE',
                    'message': f'Unknown close_type: {close_type}'
                }
                
        except Exception as e:
            logger.error(f"[CONSOLIDATED] Close position failed: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to close position'
            }

# Backward Compatibility Layer
class BackwardCompatibilityAliases:
    """
    Provides exact backward compatibility for all consolidated tools.
    These can be registered as MCP tools with original names.
    """
    
    @staticmethod
    async def trade_get_quote(symbol: str, asset_type: str = 'STK'):
        """Legacy trade_get_quote compatibility."""
        result = await MarketDataConsolidator.get_market_data(
            symbols=symbol,
            asset_type=asset_type
        )
        # Transform to match legacy single quote format
        if result.get('quotes') and len(result['quotes']) > 0:
            return result['quotes'][0]
        return result
    
    @staticmethod
    async def trade_get_watchlist_quotes(symbols: List[str]):
        """Legacy trade_get_watchlist_quotes compatibility."""
        return await MarketDataConsolidator.get_market_data(
            symbols=symbols,
            asset_type='STK'
        )
    
    @staticmethod
    async def trade_get_index_quote(symbol: str):
        """Legacy trade_get_index_quote compatibility."""
        result = await MarketDataConsolidator.get_market_data(
            symbols=symbol,
            asset_type='IND'
        )
        # Transform to match legacy format
        if result.get('quotes') and len(result['quotes']) > 0:
            return result['quotes'][0]
        return result
    
    @staticmethod
    async def trade_get_crypto_quote(symbol: str):
        """Legacy trade_get_crypto_quote compatibility."""
        result = await MarketDataConsolidator.get_market_data(
            symbols=symbol,
            asset_type='CRYPTO'
        )
        # Transform to match legacy format
        if result.get('quotes') and len(result['quotes']) > 0:
            return result['quotes'][0]
        return result
    
    @staticmethod
    async def trade_get_fx_quote(base: str, quote: str):
        """Legacy trade_get_fx_quote compatibility."""
        symbol = f"{base}{quote}"
        result = await MarketDataConsolidator.get_market_data(
            symbols=symbol,
            asset_type='FX'
        )
        # Transform to match legacy format
        if result.get('quotes') and len(result['quotes']) > 0:
            return result['quotes'][0]
        return result
    
    @staticmethod
    async def trade_get_positions():
        """Legacy trade_get_positions compatibility."""
        return await PortfolioConsolidator.get_portfolio(view='positions')
    
    @staticmethod
    async def trade_get_account_summary():
        """Legacy trade_get_account_summary compatibility."""
        return await PortfolioConsolidator.get_portfolio(view='account')
    
    @staticmethod
    async def trade_get_portfolio_summary():
        """Legacy trade_get_portfolio_summary compatibility."""
        return await PortfolioConsolidator.get_portfolio(
            view='summary',
            include_greeks=True
        )
    
    @staticmethod
    async def trade_close_position(
        symbol: str,
        position_type: str,
        quantity: int,
        order_type: str = 'MKT',
        limit_price: Optional[float] = None,
        position_id: Optional[str] = None,
        confirm_token: Optional[str] = None
    ):
        """Legacy trade_close_position compatibility."""
        return await ClosePositionConsolidator.close_positions(
            symbol=symbol,
            close_type='standard',
            position_type=position_type,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            position_id=position_id,
            confirm_token=confirm_token
        )
    
    @staticmethod
    async def trade_buy_to_close(
        symbol: str,
        strike: float,
        expiry: str,
        right: str,
        quantity: int,
        order_type: str = 'MKT',
        limit_price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        trigger_condition: str = 'immediate',
        confirm_token: Optional[str] = None
    ):
        """Legacy trade_buy_to_close compatibility."""
        return await ClosePositionConsolidator.close_positions(
            symbol=symbol,
            close_type='buy_to_close',
            strike=strike,
            expiry=expiry,
            right=right,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            trigger_price=trigger_price,
            trigger_condition=trigger_condition,
            confirm_token=confirm_token
        )
    
    @staticmethod
    async def trade_direct_close(
        symbol: str,
        position_type: str,
        strike: Optional[float] = None,
        right: Optional[str] = None,
        quantity: Optional[int] = None,
        order_type: str = 'MKT',
        limit_price: Optional[float] = None,
        confirm_token: Optional[str] = None
    ):
        """Legacy trade_direct_close compatibility."""
        return await ClosePositionConsolidator.close_positions(
            symbol=symbol,
            close_type='direct',
            position_type=position_type,
            strike=strike,
            right=right,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            confirm_token=confirm_token
        )
    
    @staticmethod
    async def trade_emergency_close(
        symbol: str,
        confirm_token: str,
        second_confirmation: str
    ):
        """Legacy trade_emergency_close compatibility."""
        return await ClosePositionConsolidator.close_positions(
            symbol=symbol,
            close_type='emergency',
            confirm_token=confirm_token,
            second_confirmation=second_confirmation
        )