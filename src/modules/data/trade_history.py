"""
Trade history analysis module.
Retrieves and analyzes historical trades for performance metrics.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import defaultdict

from loguru import logger
from ib_async import Trade, Fill

from src.modules.tws.connection import get_tws_connection
from src.modules.utils.type_coercion import ensure_trade


@dataclass
class TradeRecord:
    """Historical trade record."""
    symbol: str
    trade_date: datetime
    action: str  # BUY/SELL
    quantity: int
    fill_price: float
    commission: float
    realized_pnl: float
    order_id: int
    execution_id: str
    account: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP response."""
        return {
            'symbol': self.symbol,
            'trade_date': self.trade_date.isoformat(),
            'action': self.action,
            'quantity': self.quantity,
            'fill_price': self.fill_price,
            'commission': self.commission,
            'realized_pnl': self.realized_pnl,
            'order_id': self.order_id,
            'execution_id': self.execution_id,
            'account': self.account
        }


class TradeHistoryAnalyzer:
    """Analyzes historical trading data."""
    
    def __init__(self):
        """Initialize trade history analyzer."""
        self.tws = None
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 30  # seconds
        
    async def _ensure_connection(self):
        """Ensure TWS connection is established."""
        if not self.tws:
            self.tws = await get_tws_connection()
            
    async def get_trade_history(
        self,
        symbol: Optional[str] = None,
        days: int = 30,
        include_closed: bool = True,
        include_open: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get historical trades.
        
        Args:
            symbol: Filter by symbol
            days: Number of days of history
            include_closed: Include closed trades
            include_open: Include open positions
            
        Returns:
            List of trade records
        """
        await self._ensure_connection()
        
        logger.info(f"[HISTORY] Fetching {days} days of trade history")
        
        trades = []
        
        try:
            # Get fills from TWS
            ib = self.tws.ib
            
            # Get recent fills
            fills = ib.fills()
            
            logger.debug(f"[HISTORY] Retrieved {len(fills)} fills from TWS")
            
            # Filter by date
            cutoff_date = datetime.now() - timedelta(days=days)
            
            for fill in fills:
                # Check date
                if fill.time < cutoff_date:
                    continue
                    
                # Check symbol filter
                if symbol and fill.contract.symbol != symbol:
                    continue
                
                # Create trade record
                trade_record = TradeRecord(
                    symbol=fill.contract.symbol,
                    trade_date=fill.time,
                    action=fill.execution.side,
                    quantity=fill.execution.shares,
                    fill_price=fill.execution.price,
                    commission=fill.commissionReport.commission if fill.commissionReport else 0,
                    realized_pnl=fill.commissionReport.realizedPNL if fill.commissionReport else 0,
                    order_id=fill.execution.orderId,
                    execution_id=fill.execution.execId,
                    account=fill.execution.acctNumber
                )
                
                trades.append(trade_record.to_dict())
            
            # Get open trades if requested
            if include_open:
                open_trades = ib.openTrades()
                logger.debug(f"[HISTORY] Found {len(open_trades)} open trades")
                
                for trade in open_trades:
                    if symbol and trade.contract.symbol != symbol:
                        continue
                        
                    trades.append({
                        'symbol': trade.contract.symbol,
                        'trade_date': trade.log[0].time if trade.log else datetime.now(),
                        'action': trade.order.action,
                        'quantity': trade.order.totalQuantity,
                        'fill_price': 0,  # Not filled yet
                        'commission': 0,
                        'realized_pnl': 0,
                        'order_id': trade.order.orderId,
                        'execution_id': 'PENDING',
                        'account': trade.order.account,
                        'status': 'OPEN'
                    })
            
            logger.info(f"[HISTORY] Processed {len(trades)} trades")
            
        except Exception as e:
            logger.error(f"[HISTORY] Error fetching trades: {e}")
            raise
            
        return trades
    
    async def calculate_statistics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate performance statistics from trades.
        
        Args:
            trades: List of trade records
            
        Returns:
            Performance statistics
        """
        if not trades:
            return {
                'total_trades': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'average_win': 0,
                'average_loss': 0,
                'profit_factor': 0,
                'max_win': 0,
                'max_loss': 0
            }
        
        logger.debug(f"[HISTORY] Calculating stats for {len(trades)} trades")
        
        # Group by symbol
        by_symbol = defaultdict(list)
        for trade in trades:
            by_symbol[trade['symbol']].append(trade)
        
        # Calculate P&L
        total_pnl = sum(t.get('realized_pnl', 0) for t in trades)
        wins = [t for t in trades if t.get('realized_pnl', 0) > 0]
        losses = [t for t in trades if t.get('realized_pnl', 0) < 0]
        
        win_rate = (len(wins) / len(trades)) * 100 if trades else 0
        
        avg_win = sum(t['realized_pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['realized_pnl'] for t in losses) / len(losses) if losses else 0
        
        # Profit factor
        gross_profit = sum(t['realized_pnl'] for t in wins)
        gross_loss = abs(sum(t['realized_pnl'] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Best/worst trades
        max_win = max((t['realized_pnl'] for t in wins), default=0)
        max_loss = min((t['realized_pnl'] for t in losses), default=0)
        
        # Best/worst symbols
        symbol_pnl = {
            symbol: sum(t['realized_pnl'] for t in trades_list)
            for symbol, trades_list in by_symbol.items()
        }
        
        best_symbol = max(symbol_pnl.items(), key=lambda x: x[1])[0] if symbol_pnl else None
        worst_symbol = min(symbol_pnl.items(), key=lambda x: x[1])[0] if symbol_pnl else None
        
        logger.info(f"[HISTORY] Stats: Total P&L: ${total_pnl:.2f}, Win rate: {win_rate:.1f}%")
        
        return {
            'total_trades': len(trades),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate, 1),
            'wins': len(wins),
            'losses': len(losses),
            'average_win': round(avg_win, 2),
            'average_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_win': round(max_win, 2),
            'max_loss': round(max_loss, 2),
            'best_symbol': best_symbol,
            'worst_symbol': worst_symbol,
            'by_symbol': {
                symbol: {
                    'trades': len(trades_list),
                    'pnl': round(sum(t['realized_pnl'] for t in trades_list), 2)
                }
                for symbol, trades_list in by_symbol.items()
            }
        }