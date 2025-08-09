"""
Live data manager for event-driven market updates.
Replaces polling with streaming for real-time data.
"""

import asyncio
from typing import Dict, Set, Optional, Callable, Any
from datetime import datetime
from dataclasses import dataclass
from collections import defaultdict

from loguru import logger
from ib_async import Contract, Ticker, IB

from src.modules.tws.connection import get_tws_connection


@dataclass
class LiveDataSubscription:
    """Represents a live data subscription."""
    contract: Contract
    ticker: Ticker
    callbacks: Set[Callable]
    subscription_time: datetime
    last_update: datetime
    update_count: int = 0
    
    def add_callback(self, callback: Callable):
        """Add a callback for updates."""
        self.callbacks.add(callback)
        
    def remove_callback(self, callback: Callable):
        """Remove a callback."""
        self.callbacks.discard(callback)


class LiveDataManager:
    """
    Manages live streaming market data subscriptions.
    Provides event-driven updates instead of polling.
    """
    
    def __init__(self):
        """Initialize live data manager."""
        self.tws = None
        self.subscriptions: Dict[int, LiveDataSubscription] = {}  # conId -> subscription
        self.active_tickers: Dict[int, Ticker] = {}  # conId -> ticker
        self.update_handlers: Dict[str, Set[Callable]] = defaultdict(set)
        self._running = False
        self._update_task = None
        
    async def _ensure_connection(self):
        """Ensure TWS connection is established."""
        if not self.tws:
            self.tws = await get_tws_connection()
            
    async def subscribe(
        self, 
        contract: Contract,
        callback: Optional[Callable] = None,
        generic_ticks: str = ""
    ) -> Ticker:
        """
        Subscribe to live market data for a contract.
        
        Args:
            contract: Contract to subscribe to
            callback: Optional callback for updates
            generic_ticks: Generic tick types (e.g., "106" for option Greeks)
            
        Returns:
            Live ticker that updates automatically
        """
        await self._ensure_connection()
        ib = self.tws.ib
        
        # Check if already subscribed
        if contract.conId in self.subscriptions:
            logger.debug(f"[LIVE] Already subscribed to {contract.symbol}")
            subscription = self.subscriptions[contract.conId]
            if callback:
                subscription.add_callback(callback)
            return subscription.ticker
            
        logger.info(f"[LIVE] Subscribing to {contract.symbol} (conId: {contract.conId})")
        
        # Request live market data (NOT snapshot)
        ticker = ib.reqMktData(
            contract,
            genericTickList=generic_ticks,
            snapshot=False,  # Stream, don't snapshot!
            regulatorySnapshot=False
        )
        
        # Set up event handler for this ticker
        ticker.updateEvent += self._on_ticker_update
        
        # Create subscription
        subscription = LiveDataSubscription(
            contract=contract,
            ticker=ticker,
            callbacks={callback} if callback else set(),
            subscription_time=datetime.now(),
            last_update=datetime.now()
        )
        
        self.subscriptions[contract.conId] = subscription
        self.active_tickers[contract.conId] = ticker
        
        # Wait for first update (max 2 seconds)
        try:
            await asyncio.wait_for(ticker.updateEvent, timeout=2.0)
            logger.info(f"[LIVE] Initial data received for {contract.symbol}")
        except asyncio.TimeoutError:
            logger.warning(f"[LIVE] No initial data for {contract.symbol} (market may be closed)")
            
        return ticker
    
    def _on_ticker_update(self, ticker: Ticker):
        """
        Handle ticker update events.
        Called automatically when ticker data changes.
        """
        # Find subscription for this ticker
        for conId, subscription in self.subscriptions.items():
            if subscription.ticker == ticker:
                subscription.last_update = datetime.now()
                subscription.update_count += 1
                
                # Log significant updates
                if subscription.update_count % 10 == 0:
                    logger.debug(
                        f"[LIVE] {ticker.contract.symbol} - "
                        f"Bid: {ticker.bid}, Ask: {ticker.ask}, "
                        f"Last: {ticker.last} (update #{subscription.update_count})"
                    )
                
                # Call registered callbacks
                for callback in subscription.callbacks:
                    try:
                        asyncio.create_task(callback(ticker))
                    except Exception as e:
                        logger.error(f"[LIVE] Callback error: {e}")
                        
                break
    
    async def unsubscribe(self, contract: Contract):
        """
        Unsubscribe from market data.
        
        Args:
            contract: Contract to unsubscribe from
        """
        if contract.conId not in self.subscriptions:
            logger.warning(f"[LIVE] Not subscribed to {contract.symbol}")
            return
            
        logger.info(f"[LIVE] Unsubscribing from {contract.symbol}")
        
        subscription = self.subscriptions[contract.conId]
        ticker = subscription.ticker
        
        # Cancel market data
        await self._ensure_connection()
        self.tws.ib.cancelMktData(contract)
        
        # Remove event handler
        ticker.updateEvent -= self._on_ticker_update
        
        # Clean up
        del self.subscriptions[contract.conId]
        del self.active_tickers[contract.conId]
        
        logger.info(f"[LIVE] Unsubscribed from {contract.symbol}")
    
    async def subscribe_portfolio(self, callback: Optional[Callable] = None):
        """
        Subscribe to live portfolio updates.
        
        Args:
            callback: Optional callback for portfolio updates
        """
        await self._ensure_connection()
        ib = self.tws.ib
        
        logger.info("[LIVE] Subscribing to portfolio updates")
        
        # Set up portfolio event handlers
        def on_position_update(position):
            """Handle position updates."""
            logger.debug(f"[LIVE] Position update: {position.contract.symbol} qty={position.position}")
            if callback:
                asyncio.create_task(callback('position', position))
                
        def on_pnl_update(pnl):
            """Handle P&L updates."""
            logger.debug(f"[LIVE] P&L update: ${pnl.dailyPnL:.2f} / ${pnl.unrealizedPnL:.2f}")
            if callback:
                asyncio.create_task(callback('pnl', pnl))
                
        # Register handlers
        ib.positionEvent += on_position_update
        ib.pnlEvent += on_pnl_update
        
        # Request updates
        ib.reqPositions()
        ib.reqPnL(ib.wrapper.accounts[0]) if ib.wrapper.accounts else None
        
        logger.info("[LIVE] Portfolio updates started")
    
    async def get_live_greeks(self, contract: Contract) -> Optional[Dict[str, float]]:
        """
        Get live Greeks for an option contract.
        
        Args:
            contract: Option contract
            
        Returns:
            Greeks dictionary or None
        """
        if contract.secType != 'OPT':
            return None
            
        # Subscribe with Greeks tick types
        ticker = await self.subscribe(contract, generic_ticks="106")
        
        # Wait a bit for Greeks to arrive
        await asyncio.sleep(1)
        
        if ticker.modelGreeks:
            return {
                'delta': ticker.modelGreeks.delta,
                'gamma': ticker.modelGreeks.gamma,
                'theta': ticker.modelGreeks.theta,
                'vega': ticker.modelGreeks.vega,
                'iv': ticker.modelGreeks.impliedVol
            }
        else:
            logger.warning(f"[LIVE] No Greeks available for {contract.symbol}")
            return None
    
    async def start_monitoring(self, symbols: list, callback: Callable):
        """
        Start monitoring a list of symbols with live updates.
        
        Args:
            symbols: List of symbols to monitor
            callback: Callback for all updates
        """
        logger.info(f"[LIVE] Starting monitoring for {len(symbols)} symbols")
        
        from ib_async import Stock
        
        for symbol in symbols:
            contract = Stock(symbol, 'SMART', 'USD')
            await self.subscribe(contract, callback)
            
        logger.info(f"[LIVE] Monitoring started for {symbols}")
    
    def get_subscription_stats(self) -> Dict[str, Any]:
        """
        Get statistics about active subscriptions.
        
        Returns:
            Subscription statistics
        """
        total_updates = sum(s.update_count for s in self.subscriptions.values())
        
        stats = {
            'active_subscriptions': len(self.subscriptions),
            'total_updates': total_updates,
            'subscriptions': []
        }
        
        for conId, subscription in self.subscriptions.items():
            ticker = subscription.ticker
            stats['subscriptions'].append({
                'symbol': ticker.contract.symbol,
                'conId': conId,
                'update_count': subscription.update_count,
                'last_update': subscription.last_update.isoformat(),
                'bid': ticker.bid,
                'ask': ticker.ask,
                'last': ticker.last
            })
            
        return stats
    
    async def cleanup(self):
        """Clean up all subscriptions."""
        logger.info("[LIVE] Cleaning up all subscriptions")
        
        # Copy keys to avoid modification during iteration
        con_ids = list(self.subscriptions.keys())
        
        for conId in con_ids:
            contract = self.subscriptions[conId].contract
            await self.unsubscribe(contract)
            
        logger.info("[LIVE] All subscriptions cleaned up")