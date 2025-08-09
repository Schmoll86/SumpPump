"""
Historical data provider for trade analysis.
Fetches historical executions from IBKR on-demand with smart caching.
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
import time

from loguru import logger
from ib_async import ExecutionFilter, Execution, CommissionReport

from src.modules.tws.connection import get_tws_connection


@dataclass
class HistoricalExecution:
    """Historical execution record."""
    symbol: str
    exec_id: str
    order_id: int
    time: datetime
    side: str  # BOT/SLD
    quantity: int
    price: float
    commission: float
    realized_pnl: float
    account: str
    exchange: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'symbol': self.symbol,
            'exec_id': self.exec_id,
            'order_id': self.order_id,
            'time': self.time.isoformat(),
            'side': self.side,
            'quantity': self.quantity,
            'price': self.price,
            'commission': self.commission,
            'realized_pnl': self.realized_pnl,
            'account': self.account,
            'exchange': self.exchange
        }


class HistoricalDataProvider:
    """
    Provides historical trade data without maintaining a database.
    Uses intelligent caching to minimize API calls.
    """
    
    def __init__(self):
        """Initialize historical data provider."""
        self.tws = None
        self.cache_dir = Path.home() / '.sumppump' / 'historical'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = 3600  # 1 hour cache
        
    async def _ensure_connection(self):
        """Ensure TWS connection."""
        if not self.tws:
            self.tws = await get_tws_connection()
    
    def _get_cache_file(self, days_back: int, symbol: Optional[str]) -> Path:
        """Get cache file path."""
        symbol_str = symbol or 'all'
        return self.cache_dir / f"exec_{symbol_str}_{days_back}d.json"
    
    def _is_cache_valid(self, cache_file: Path) -> bool:
        """Check if cache is still valid."""
        if not cache_file.exists():
            return False
            
        age = time.time() - cache_file.stat().st_mtime
        return age < self.cache_ttl
    
    def _load_cache(self, cache_file: Path) -> List[HistoricalExecution]:
        """Load executions from cache."""
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                
            executions = []
            for item in data:
                exec_data = HistoricalExecution(
                    symbol=item['symbol'],
                    exec_id=item['exec_id'],
                    order_id=item['order_id'],
                    time=datetime.fromisoformat(item['time']),
                    side=item['side'],
                    quantity=item['quantity'],
                    price=item['price'],
                    commission=item['commission'],
                    realized_pnl=item['realized_pnl'],
                    account=item['account'],
                    exchange=item['exchange']
                )
                executions.append(exec_data)
                
            logger.info(f"[HISTORY] Loaded {len(executions)} executions from cache")
            return executions
            
        except Exception as e:
            logger.error(f"[HISTORY] Failed to load cache: {e}")
            return []
    
    def _save_cache(self, cache_file: Path, executions: List[HistoricalExecution]):
        """Save executions to cache."""
        try:
            data = [exec.to_dict() for exec in executions]
            
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.info(f"[HISTORY] Saved {len(executions)} executions to cache")
            
        except Exception as e:
            logger.error(f"[HISTORY] Failed to save cache: {e}")
    
    async def get_executions(
        self,
        days_back: int = 365,
        symbol: Optional[str] = None,
        use_cache: bool = True
    ) -> List[HistoricalExecution]:
        """
        Get historical executions from IBKR.
        
        Args:
            days_back: Number of days of history
            symbol: Filter by symbol (None for all)
            use_cache: Use cached data if available
            
        Returns:
            List of historical executions
        """
        # Check cache first
        cache_file = self._get_cache_file(days_back, symbol)
        
        if use_cache and self._is_cache_valid(cache_file):
            logger.info(f"[HISTORY] Using cached data for {days_back} days")
            return self._load_cache(cache_file)
            
        # Fetch from IBKR
        logger.info(f"[HISTORY] Fetching {days_back} days of executions from IBKR")
        
        await self._ensure_connection()
        ib = self.tws.ib
        
        # Create filter
        exec_filter = ExecutionFilter()
        if symbol:
            exec_filter.symbol = symbol
            
        # Set time filter
        start_time = datetime.now() - timedelta(days=days_back)
        exec_filter.time = start_time.strftime('%Y%m%d-00:00:00')
        
        # Request executions
        executions_data = await ib.reqExecutionsAsync(exec_filter)
        
        logger.info(f"[HISTORY] Received {len(executions_data)} executions from IBKR")
        
        # Convert to our format
        executions = []
        for exec_data in executions_data:
            if not exec_data:
                continue
                
            execution = exec_data.execution if hasattr(exec_data, 'execution') else exec_data
            commission = exec_data.commissionReport if hasattr(exec_data, 'commissionReport') else None
            
            # Defensive checks for all fields
            hist_exec = HistoricalExecution(
                symbol=execution.contract.symbol if hasattr(execution, 'contract') and execution.contract else 'UNKNOWN',
                exec_id=execution.execId if hasattr(execution, 'execId') else '',
                order_id=execution.orderId if hasattr(execution, 'orderId') else 0,
                time=execution.time if hasattr(execution, 'time') else datetime.now(),
                side=execution.side if hasattr(execution, 'side') else 'UNKNOWN',
                quantity=execution.shares if hasattr(execution, 'shares') else 0,
                price=execution.price if hasattr(execution, 'price') else 0.0,
                commission=commission.commission if commission and hasattr(commission, 'commission') else 0.0,
                realized_pnl=commission.realizedPNL if commission and hasattr(commission, 'realizedPNL') else 0.0,
                account=execution.acctNumber if hasattr(execution, 'acctNumber') else 'UNKNOWN',
                exchange=execution.exchange if hasattr(execution, 'exchange') else 'UNKNOWN'
            )
            executions.append(hist_exec)
        
        # Sort by time
        executions.sort(key=lambda x: x.time, reverse=True)
        
        # Save to cache
        if use_cache:
            self._save_cache(cache_file, executions)
            
        return executions
    
    async def analyze_performance(
        self,
        executions: List[HistoricalExecution]
    ) -> Dict[str, Any]:
        """
        Analyze performance from historical executions.
        
        Args:
            executions: List of executions to analyze
            
        Returns:
            Performance metrics
        """
        if not executions:
            return {
                'total_trades': 0,
                'message': 'No executions to analyze'
            }
            
        logger.info(f"[HISTORY] Analyzing {len(executions)} executions")
        
        # Group by symbol
        by_symbol = {}
        for exec in executions:
            if exec.symbol not in by_symbol:
                by_symbol[exec.symbol] = []
            by_symbol[exec.symbol].append(exec)
        
        # Calculate metrics
        total_pnl = sum(exec.realized_pnl for exec in executions)
        total_commission = sum(exec.commission for exec in executions)
        
        # Separate wins and losses
        wins = [e for e in executions if e.realized_pnl > 0]
        losses = [e for e in executions if e.realized_pnl < 0]
        
        win_rate = (len(wins) / len(executions)) * 100 if executions else 0
        
        avg_win = sum(e.realized_pnl for e in wins) / len(wins) if wins else 0
        avg_loss = sum(e.realized_pnl for e in losses) / len(losses) if losses else 0
        
        # Profit factor
        gross_profit = sum(e.realized_pnl for e in wins)
        gross_loss = abs(sum(e.realized_pnl for e in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Best and worst trades
        best_trade = max(executions, key=lambda x: x.realized_pnl) if executions else None
        worst_trade = min(executions, key=lambda x: x.realized_pnl) if executions else None
        
        # Symbol performance
        symbol_performance = {}
        for symbol, execs in by_symbol.items():
            symbol_pnl = sum(e.realized_pnl for e in execs)
            symbol_trades = len(execs)
            symbol_performance[symbol] = {
                'trades': symbol_trades,
                'total_pnl': round(symbol_pnl, 2),
                'avg_pnl': round(symbol_pnl / symbol_trades, 2) if symbol_trades > 0 else 0
            }
        
        # Sort symbols by P&L
        best_symbol = max(symbol_performance.items(), key=lambda x: x[1]['total_pnl'])[0] if symbol_performance else None
        worst_symbol = min(symbol_performance.items(), key=lambda x: x[1]['total_pnl'])[0] if symbol_performance else None
        
        return {
            'period': {
                'start': min(e.time for e in executions).isoformat() if executions else None,
                'end': max(e.time for e in executions).isoformat() if executions else None,
                'days': (max(e.time for e in executions) - min(e.time for e in executions)).days if executions else 0
            },
            'summary': {
                'total_trades': len(executions),
                'unique_symbols': len(by_symbol),
                'total_pnl': round(total_pnl, 2),
                'total_commission': round(total_commission, 2),
                'net_pnl': round(total_pnl - total_commission, 2)
            },
            'performance': {
                'win_rate': round(win_rate, 1),
                'wins': len(wins),
                'losses': len(losses),
                'average_win': round(avg_win, 2),
                'average_loss': round(avg_loss, 2),
                'profit_factor': round(profit_factor, 2),
                'expectancy': round((win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss), 2)
            },
            'extremes': {
                'best_trade': {
                    'symbol': best_trade.symbol,
                    'pnl': best_trade.realized_pnl,
                    'date': best_trade.time.isoformat()
                } if best_trade else None,
                'worst_trade': {
                    'symbol': worst_trade.symbol,
                    'pnl': worst_trade.realized_pnl,
                    'date': worst_trade.time.isoformat()
                } if worst_trade else None
            },
            'by_symbol': symbol_performance,
            'top_performers': {
                'best_symbol': best_symbol,
                'worst_symbol': worst_symbol
            }
        }
    
    async def get_daily_pnl(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get daily P&L for the last N days.
        
        Args:
            days: Number of days
            
        Returns:
            Daily P&L breakdown
        """
        executions = await self.get_executions(days_back=days)
        
        # Group by date
        daily_pnl = {}
        for exec in executions:
            date_str = exec.time.date().isoformat()
            
            if date_str not in daily_pnl:
                daily_pnl[date_str] = {
                    'trades': 0,
                    'gross_pnl': 0,
                    'commission': 0,
                    'net_pnl': 0
                }
                
            daily_pnl[date_str]['trades'] += 1
            daily_pnl[date_str]['gross_pnl'] += exec.realized_pnl
            daily_pnl[date_str]['commission'] += exec.commission
            daily_pnl[date_str]['net_pnl'] += (exec.realized_pnl - exec.commission)
        
        # Round values
        for date_str in daily_pnl:
            for key in ['gross_pnl', 'commission', 'net_pnl']:
                daily_pnl[date_str][key] = round(daily_pnl[date_str][key], 2)
        
        # Calculate cumulative
        dates = sorted(daily_pnl.keys())
        cumulative = 0
        for date in dates:
            cumulative += daily_pnl[date]['net_pnl']
            daily_pnl[date]['cumulative'] = round(cumulative, 2)
        
        return {
            'period': f'{days} days',
            'daily_breakdown': daily_pnl,
            'total_days': len(daily_pnl),
            'profitable_days': sum(1 for d in daily_pnl.values() if d['net_pnl'] > 0),
            'losing_days': sum(1 for d in daily_pnl.values() if d['net_pnl'] < 0),
            'best_day': max(daily_pnl.items(), key=lambda x: x[1]['net_pnl'])[0] if daily_pnl else None,
            'worst_day': min(daily_pnl.items(), key=lambda x: x[1]['net_pnl'])[0] if daily_pnl else None,
            'total_net_pnl': round(sum(d['net_pnl'] for d in daily_pnl.values()), 2)
        }
    
    async def clear_cache(self):
        """Clear all cached historical data."""
        logger.info("[HISTORY] Clearing historical data cache")
        
        for cache_file in self.cache_dir.glob("exec_*.json"):
            try:
                cache_file.unlink()
                logger.debug(f"[HISTORY] Deleted {cache_file.name}")
            except Exception as e:
                logger.error(f"[HISTORY] Failed to delete {cache_file.name}: {e}")
                
        logger.info("[HISTORY] Cache cleared")