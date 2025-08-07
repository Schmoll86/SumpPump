"""
Level 2 Depth of Book module using IEX and other depth feeds.
Provides market depth data for better order execution insights.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from ib_async import Stock, Contract, MktDepthData
from loguru import logger

from src.core import (
    rate_limited,
    with_connection_retry,
    MarketDataError,
    NoMarketDataError
)


class DepthProvider(Enum):
    """Available depth providers."""
    IEX = "IEX"
    ARCA = "ARCA"
    ISLAND = "ISLAND"
    SMART = "SMART"


@dataclass
class BookLevel:
    """Single level in order book."""
    price: float
    size: int
    mm_id: Optional[str] = None  # Market maker ID
    cum_size: Optional[int] = None  # Cumulative size
    avg_price: Optional[float] = None  # Average price to this level


@dataclass
class OrderBook:
    """Complete order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: List[BookLevel]
    asks: List[BookLevel]
    spread: float
    mid_price: float
    bid_depth: int  # Total bid volume
    ask_depth: int  # Total ask volume
    imbalance: float  # Bid/ask imbalance ratio
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP response."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "spread": self.spread,
            "mid_price": self.mid_price,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "imbalance": self.imbalance,
            "bids": [
                {
                    "price": level.price,
                    "size": level.size,
                    "mm_id": level.mm_id,
                    "cum_size": level.cum_size
                }
                for level in self.bids
            ],
            "asks": [
                {
                    "price": level.price,
                    "size": level.size,
                    "mm_id": level.mm_id,
                    "cum_size": level.cum_size
                }
                for level in self.asks
            ]
        }
    
    def get_vwap(self, side: str, size: int) -> Optional[float]:
        """
        Calculate volume-weighted average price for given size.
        
        Args:
            side: 'bid' or 'ask'
            size: Total size to execute
            
        Returns:
            VWAP for the order size
        """
        levels = self.bids if side == 'bid' else self.asks
        
        remaining = size
        total_cost = 0.0
        
        for level in levels:
            if remaining <= 0:
                break
            
            fill_size = min(remaining, level.size)
            total_cost += fill_size * level.price
            remaining -= fill_size
        
        if remaining > 0:
            return None  # Not enough depth
        
        return total_cost / size


class DepthOfBook:
    """
    Level 2 Depth of Book data provider.
    Integrates with IEX and other depth providers.
    """
    
    def __init__(self, tws_connection):
        """
        Initialize depth of book provider.
        
        Args:
            tws_connection: Active TWS connection instance
        """
        self.tws = tws_connection
        self.active_subscriptions: Dict[str, Any] = {}
        self.depth_cache: Dict[str, OrderBook] = {}
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data")
    async def get_depth(
        self,
        symbol: str,
        num_levels: int = 5,
        provider: DepthProvider = DepthProvider.IEX,
        smart_depth: bool = True
    ) -> OrderBook:
        """
        Get Level 2 depth of book data.
        
        Args:
            symbol: Stock symbol
            num_levels: Number of price levels (max 10)
            provider: Depth provider to use
            smart_depth: Use SMART routing for aggregated depth
            
        Returns:
            OrderBook with depth data
        """
        try:
            await self.tws.ensure_connected()
            
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            await self.tws.ib.qualifyContractsAsync(contract)
            
            # Check if already subscribed
            sub_key = f"{symbol}_{provider.value}"
            if sub_key in self.active_subscriptions:
                # Return cached data if fresh
                if sub_key in self.depth_cache:
                    cached = self.depth_cache[sub_key]
                    age = (datetime.now() - cached.timestamp).seconds
                    if age < 1:  # Less than 1 second old
                        return cached
            
            # Request market depth
            logger.info(f"Requesting Level 2 depth for {symbol} from {provider.value}")
            
            # Set up depth data collector
            depth_data = {'bids': [], 'asks': []}
            
            # Request depth (this returns immediately, data comes via events)
            req_id = self.tws.ib.reqMktDepth(
                contract,
                numRows=min(num_levels, 10),  # Max 10 levels
                isSmartDepth=smart_depth,
                mktDepthOptions=[]
            )
            
            # Store subscription
            self.active_subscriptions[sub_key] = req_id
            
            # Wait for depth data to populate (with timeout)
            await asyncio.sleep(1.0)  # Give time for initial data
            
            # Get the depth data from IB's cache
            market_depth = self.tws.ib.mktDepthData.get(req_id, [])
            
            # Process depth data
            bids = []
            asks = []
            
            for depth_item in market_depth:
                level = BookLevel(
                    price=depth_item.price,
                    size=depth_item.size,
                    mm_id=depth_item.marketMaker if hasattr(depth_item, 'marketMaker') else None
                )
                
                if depth_item.side == 0:  # Bid
                    bids.append(level)
                else:  # Ask
                    asks.append(level)
            
            # Sort bids descending, asks ascending
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)
            
            # Calculate cumulative sizes
            cum_bid = 0
            for bid in bids:
                cum_bid += bid.size
                bid.cum_size = cum_bid
            
            cum_ask = 0
            for ask in asks:
                cum_ask += ask.size
                ask.cum_size = cum_ask
            
            # Calculate metrics
            bid_price = bids[0].price if bids else 0
            ask_price = asks[0].price if asks else 0
            spread = ask_price - bid_price if bid_price and ask_price else 0
            mid_price = (bid_price + ask_price) / 2 if bid_price and ask_price else 0
            
            bid_depth = sum(b.size for b in bids)
            ask_depth = sum(a.size for a in asks)
            imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0
            
            # Create order book
            order_book = OrderBook(
                symbol=symbol,
                timestamp=datetime.now(),
                bids=bids,
                asks=asks,
                spread=spread,
                mid_price=mid_price,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                imbalance=imbalance
            )
            
            # Cache the result
            self.depth_cache[sub_key] = order_book
            
            logger.info(f"Depth data for {symbol}: "
                       f"Spread={spread:.3f}, "
                       f"Bid depth={bid_depth}, "
                       f"Ask depth={ask_depth}, "
                       f"Imbalance={imbalance:.2%}")
            
            return order_book
            
        except Exception as e:
            logger.error(f"Error getting depth for {symbol}: {e}")
            raise MarketDataError(f"Failed to get depth data for {symbol}: {e}")
    
    async def subscribe_depth_stream(
        self,
        symbol: str,
        callback,
        num_levels: int = 5,
        provider: DepthProvider = DepthProvider.IEX
    ) -> str:
        """
        Subscribe to streaming depth updates.
        
        Args:
            symbol: Stock symbol
            callback: Async callback function for updates
            num_levels: Number of price levels
            provider: Depth provider
            
        Returns:
            Subscription ID
        """
        try:
            await self.tws.ensure_connected()
            
            contract = Stock(symbol, 'SMART', 'USD')
            await self.tws.ib.qualifyContractsAsync(contract)
            
            # Set up event handler
            def on_depth_update(trade):
                # Process update and call callback
                asyncio.create_task(callback(trade))
            
            # Request streaming depth
            req_id = self.tws.ib.reqMktDepth(
                contract,
                numRows=min(num_levels, 10),
                isSmartDepth=True
            )
            
            sub_id = f"depth_{symbol}_{req_id}"
            self.active_subscriptions[sub_id] = {
                'req_id': req_id,
                'symbol': symbol,
                'callback': callback
            }
            
            logger.info(f"Started depth stream for {symbol}: {sub_id}")
            return sub_id
            
        except Exception as e:
            logger.error(f"Error subscribing to depth stream: {e}")
            raise
    
    async def unsubscribe_depth_stream(self, subscription_id: str) -> None:
        """
        Unsubscribe from depth stream.
        
        Args:
            subscription_id: Subscription ID to cancel
        """
        if subscription_id in self.active_subscriptions:
            sub_info = self.active_subscriptions[subscription_id]
            
            try:
                self.tws.ib.cancelMktDepth(sub_info['req_id'])
                del self.active_subscriptions[subscription_id]
                logger.info(f"Cancelled depth stream: {subscription_id}")
            except Exception as e:
                logger.error(f"Error cancelling depth stream: {e}")
    
    async def get_depth_analytics(self, symbol: str) -> Dict[str, Any]:
        """
        Get advanced depth analytics.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with depth analytics
        """
        order_book = await self.get_depth(symbol, num_levels=10)
        
        # Calculate various metrics
        analytics = {
            "symbol": symbol,
            "timestamp": order_book.timestamp.isoformat(),
            "spread": order_book.spread,
            "spread_bps": (order_book.spread / order_book.mid_price * 10000) if order_book.mid_price else 0,
            "mid_price": order_book.mid_price,
            "bid_ask_imbalance": order_book.imbalance,
            "total_bid_depth": order_book.bid_depth,
            "total_ask_depth": order_book.ask_depth,
            "bid_levels": len(order_book.bids),
            "ask_levels": len(order_book.asks),
            
            # Price impact estimates
            "buy_100_vwap": order_book.get_vwap('ask', 100),
            "buy_500_vwap": order_book.get_vwap('ask', 500),
            "buy_1000_vwap": order_book.get_vwap('ask', 1000),
            "sell_100_vwap": order_book.get_vwap('bid', 100),
            "sell_500_vwap": order_book.get_vwap('bid', 500),
            "sell_1000_vwap": order_book.get_vwap('bid', 1000),
            
            # Market maker presence
            "unique_mms": len(set(b.mm_id for b in order_book.bids + order_book.asks if b.mm_id)),
            
            # Depth concentration
            "bid_concentration": self._calculate_concentration(order_book.bids),
            "ask_concentration": self._calculate_concentration(order_book.asks)
        }
        
        # Add level-by-level data
        analytics["bid_levels_detail"] = [
            {
                "level": i + 1,
                "price": bid.price,
                "size": bid.size,
                "cum_size": bid.cum_size,
                "distance_bps": abs(bid.price - order_book.mid_price) / order_book.mid_price * 10000
            }
            for i, bid in enumerate(order_book.bids[:5])
        ]
        
        analytics["ask_levels_detail"] = [
            {
                "level": i + 1,
                "price": ask.price,
                "size": ask.size,
                "cum_size": ask.cum_size,
                "distance_bps": abs(ask.price - order_book.mid_price) / order_book.mid_price * 10000
            }
            for i, ask in enumerate(order_book.asks[:5])
        ]
        
        return analytics
    
    def _calculate_concentration(self, levels: List[BookLevel]) -> float:
        """
        Calculate concentration ratio (how concentrated is liquidity).
        
        Args:
            levels: List of book levels
            
        Returns:
            Concentration ratio (0-1, higher = more concentrated)
        """
        if not levels:
            return 0
        
        total_size = sum(l.size for l in levels)
        if total_size == 0:
            return 0
        
        # Calculate Herfindahl index
        hhi = sum((l.size / total_size) ** 2 for l in levels)
        return hhi
    
    async def cleanup(self) -> None:
        """Clean up all depth subscriptions."""
        for sub_id, sub_info in list(self.active_subscriptions.items()):
            try:
                if isinstance(sub_info, dict):
                    self.tws.ib.cancelMktDepth(sub_info['req_id'])
                else:
                    self.tws.ib.cancelMktDepth(sub_info)
            except Exception as e:
                logger.error(f"Error cleaning up depth subscription {sub_id}: {e}")
        
        self.active_subscriptions.clear()
        self.depth_cache.clear()
        logger.info("Cleaned up all depth subscriptions")