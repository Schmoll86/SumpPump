"""
Forex trading module via IDEALPRO.
Provides FX quotes, trading, and currency pair analysis.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from ib_async import Forex, Contract, MarketOrder, LimitOrder
from loguru import logger

from src.core import (
    rate_limited,
    with_connection_retry,
    MarketDataError,
    TradingError,
    OrderValidationError
)


class FXVenue(Enum):
    """FX trading venues."""
    IDEALPRO = "IDEALPRO"    # Main FX venue for large orders
    IDEALFX = "IDEALFX"      # Venue for smaller FX orders
    FXCONV = "FXCONV"        # Currency conversion


@dataclass
class FXQuote:
    """Forex quote data."""
    pair: str
    base: str
    quote: str
    bid: float
    ask: float
    mid: float
    spread: float
    spread_pips: float
    bid_size: float
    ask_size: float
    timestamp: datetime
    venue: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pair": self.pair,
            "base": self.base,
            "quote": self.quote,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread": self.spread,
            "spread_pips": self.spread_pips,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "timestamp": self.timestamp.isoformat(),
            "venue": self.venue
        }


@dataclass 
class FXPosition:
    """Forex position data."""
    pair: str
    position: float  # Positive = long base, negative = short base
    avg_rate: float
    current_rate: float
    unrealized_pnl: float
    realized_pnl: float
    pnl_pips: float


class ForexTrading:
    """
    Forex trading via IDEALPRO and IDEALFX.
    Supports major, minor, and exotic currency pairs.
    """
    
    # Major currency pairs
    MAJOR_PAIRS = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD"
    ]
    
    # Minor pairs
    MINOR_PAIRS = [
        "EURGBP", "EURJPY", "GBPJPY", "EURCHF",
        "AUDJPY", "NZDJPY", "GBPAUD", "EURAUD",
        "CADJPY", "AUDNZD"
    ]
    
    # Pip values (4 decimal places for most, 2 for JPY pairs)
    PIP_VALUES = {
        "JPY": 0.01,    # Pairs with JPY
        "DEFAULT": 0.0001  # Most other pairs
    }
    
    # Minimum order sizes by venue
    MIN_ORDER_SIZE = {
        FXVenue.IDEALPRO: 25000,   # $25K minimum
        FXVenue.IDEALFX: 1,         # No minimum
        FXVenue.FXCONV: 1           # No minimum
    }
    
    def __init__(self, tws_connection, default_venue: FXVenue = FXVenue.IDEALPRO):
        """
        Initialize forex trading module.
        
        Args:
            tws_connection: Active TWS connection
            default_venue: Default FX trading venue
        """
        self.tws = tws_connection
        self.default_venue = default_venue
        self.active_subscriptions: Dict[str, Any] = {}
        self.positions: Dict[str, FXPosition] = {}
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data")
    async def get_fx_quote(
        self,
        pair: str,
        venue: Optional[FXVenue] = None
    ) -> FXQuote:
        """
        Get forex quote.
        
        Args:
            pair: Currency pair (e.g., "EURUSD" or "EUR/USD")
            venue: Trading venue (defaults to configured)
            
        Returns:
            FXQuote with current market data
        """
        try:
            await self.tws.ensure_connected()
            
            # Parse pair
            pair = pair.replace("/", "").upper()
            if len(pair) != 6:
                raise ValueError(f"Invalid currency pair: {pair}")
            
            base = pair[:3]
            quote = pair[3:]
            venue = venue or self.default_venue
            
            # Create forex contract
            contract = Forex(
                pair=f"{base}.{quote}",
                exchange=venue.value
            )
            
            # Qualify contract
            qualified = await self.tws.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise MarketDataError(f"Could not qualify FX contract {pair}")
            contract = qualified[0]
            
            # Request market data
            ticker = self.tws.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(1.5)  # Wait for data
            
            # Get quote data
            bid = ticker.bid or 0
            ask = ticker.ask or 0
            mid = (bid + ask) / 2 if bid and ask else 0
            spread = ask - bid if bid and ask else 0
            
            # Calculate spread in pips
            pip_value = self.PIP_VALUES.get("JPY" if "JPY" in pair else "DEFAULT")
            spread_pips = spread / pip_value if pip_value else 0
            
            fx_quote = FXQuote(
                pair=pair,
                base=base,
                quote=quote,
                bid=bid,
                ask=ask,
                mid=mid,
                spread=spread,
                spread_pips=spread_pips,
                bid_size=ticker.bidSize or 0,
                ask_size=ticker.askSize or 0,
                timestamp=datetime.now(),
                venue=venue.value
            )
            
            # Cancel market data
            self.tws.ib.cancelMktData(contract)
            
            logger.info(f"FX quote {pair}: {bid:.5f}/{ask:.5f} (spread: {spread_pips:.1f} pips)")
            
            return fx_quote
            
        except Exception as e:
            logger.error(f"Error getting FX quote for {pair}: {e}")
            raise MarketDataError(f"Failed to get FX quote: {e}")
    
    async def get_multiple_quotes(
        self,
        pairs: List[str]
    ) -> Dict[str, FXQuote]:
        """
        Get quotes for multiple currency pairs.
        
        Args:
            pairs: List of currency pairs
            
        Returns:
            Dictionary of pair -> FXQuote
        """
        quotes = {}
        
        for pair in pairs:
            try:
                quote = await self.get_fx_quote(pair)
                quotes[pair] = quote
            except Exception as e:
                logger.error(f"Failed to get quote for {pair}: {e}")
                quotes[pair] = None
        
        return quotes
    
    @with_connection_retry()
    @rate_limited(operation_type="order")
    async def place_fx_order(
        self,
        pair: str,
        amount: float,
        side: str,  # "BUY" or "SELL"
        order_type: str = "MARKET",
        limit_rate: Optional[float] = None,
        stop_rate: Optional[float] = None,
        venue: Optional[FXVenue] = None
    ) -> Dict[str, Any]:
        """
        Place forex order.
        
        Args:
            pair: Currency pair (e.g., "EURUSD")
            amount: Amount in base currency
            side: BUY or SELL (of base currency)
            order_type: MARKET, LIMIT, or STOP
            limit_rate: Limit rate for LIMIT orders
            stop_rate: Stop rate for STOP orders
            venue: Trading venue
            
        Returns:
            Order execution details
        """
        try:
            await self.tws.ensure_connected()
            
            # Parse pair
            pair = pair.replace("/", "").upper()
            base = pair[:3]
            quote = pair[3:]
            venue = venue or self.default_venue
            
            # Check minimum order size
            min_size = self.MIN_ORDER_SIZE[venue]
            if venue == FXVenue.IDEALPRO and amount < min_size:
                logger.info(f"Order size {amount} below IDEALPRO minimum, switching to IDEALFX")
                venue = FXVenue.IDEALFX
            
            # Create forex contract
            contract = Forex(
                pair=f"{base}.{quote}",
                exchange=venue.value
            )
            
            # Qualify contract
            qualified = await self.tws.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise TradingError(f"Could not qualify FX contract {pair}")
            contract = qualified[0]
            
            # Create order
            if order_type == "MARKET":
                order = MarketOrder(
                    action="BUY" if side.upper() == "BUY" else "SELL",
                    totalQuantity=amount
                )
            elif order_type == "LIMIT":
                if not limit_rate:
                    raise OrderValidationError("Limit rate required for LIMIT order")
                order = LimitOrder(
                    action="BUY" if side.upper() == "BUY" else "SELL",
                    totalQuantity=amount,
                    lmtPrice=limit_rate
                )
            else:
                raise OrderValidationError(f"Unsupported order type: {order_type}")
            
            # CRITICAL FIX: Add explicit account and time_in_force
            order.account = "U16348403"
            order.tif = "GTC"
            
            # Place order
            logger.info(f"Placing FX {side} order: {amount:,.0f} {base} vs {quote} @ {order_type}")
            trade = self.tws.ib.placeOrder(contract, order)
            
            # Wait for fill
            await asyncio.sleep(2)
            
            # Check order status
            if trade.orderStatus.status == 'Filled':
                avg_rate = trade.orderStatus.avgFillPrice
                filled_amt = trade.orderStatus.filled
                
                result = {
                    "status": "filled",
                    "pair": pair,
                    "side": side,
                    "amount": filled_amt,
                    "avg_rate": avg_rate,
                    "quote_amount": avg_rate * filled_amt,
                    "order_id": trade.order.orderId,
                    "venue": venue.value,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Update positions
                await self._update_position(pair, filled_amt if side == "BUY" else -filled_amt, avg_rate)
                
                logger.info(f"FX order filled: {filled_amt:,.0f} {base} @ {avg_rate:.5f}")
                
            else:
                result = {
                    "status": trade.orderStatus.status.lower(),
                    "pair": pair,
                    "side": side,
                    "amount": amount,
                    "order_id": trade.order.orderId,
                    "message": f"Order {trade.orderStatus.status}"
                }
                
                logger.warning(f"FX order not filled: {trade.orderStatus.status}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error placing FX order: {e}")
            raise TradingError(f"Failed to place FX order: {e}")
    
    async def get_fx_positions(self) -> List[FXPosition]:
        """
        Get current FX positions.
        
        Returns:
            List of FXPosition objects
        """
        try:
            await self.tws.ensure_connected()
            
            # Get account positions
            positions = self.tws.ib.positions()
            fx_positions = []
            
            for pos in positions:
                # Check if it's an FX position
                if pos.contract.secType == 'CASH':  # Forex positions
                    pair = pos.contract.symbol + pos.contract.currency
                    
                    # Get current rate
                    quote = await self.get_fx_quote(pair)
                    current_rate = quote.mid
                    
                    # Calculate P&L
                    position_value = pos.position * current_rate
                    cost_basis = pos.position * pos.avgCost
                    unrealized_pnl = position_value - cost_basis
                    
                    # Calculate P&L in pips
                    pip_value = self.PIP_VALUES.get("JPY" if "JPY" in pair else "DEFAULT")
                    rate_diff = current_rate - pos.avgCost
                    pnl_pips = rate_diff / pip_value if pip_value else 0
                    
                    fx_pos = FXPosition(
                        pair=pair,
                        position=pos.position,
                        avg_rate=pos.avgCost,
                        current_rate=current_rate,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=0,  # Would need to track trades
                        pnl_pips=pnl_pips
                    )
                    
                    fx_positions.append(fx_pos)
                    self.positions[pair] = fx_pos
            
            return fx_positions
            
        except Exception as e:
            logger.error(f"Error getting FX positions: {e}")
            raise
    
    async def calculate_fx_exposure(self) -> Dict[str, float]:
        """
        Calculate currency exposure across all positions.
        
        Returns:
            Dictionary of currency -> net exposure
        """
        exposures = {}
        positions = await self.get_fx_positions()
        
        for pos in positions:
            # Add base currency exposure
            base = pos.pair[:3]
            quote = pos.pair[3:]
            
            exposures[base] = exposures.get(base, 0) + pos.position
            exposures[quote] = exposures.get(quote, 0) - (pos.position * pos.current_rate)
        
        return exposures
    
    async def get_fx_analytics(self, pair: str) -> Dict[str, Any]:
        """
        Get comprehensive FX pair analysis.
        
        Args:
            pair: Currency pair
            
        Returns:
            Analysis including technicals and fundamentals
        """
        try:
            # Get current quote
            quote = await self.get_fx_quote(pair)
            
            # Get historical data for technical analysis
            base = pair[:3]
            quote_currency = pair[3:]
            
            contract = Forex(
                pair=f"{base}.{quote_currency}",
                exchange=self.default_venue.value
            )
            
            # Get daily bars for trend analysis
            bars = await self.tws.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr='30 D',
                barSizeSetting='1 day',
                whatToShow='MIDPOINT',
                useRTH=False
            )
            
            # Calculate technical indicators
            closes = [bar.close for bar in bars]
            
            # Moving averages
            sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
            sma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
            
            # ATR (Average True Range) for volatility
            if len(bars) >= 14:
                true_ranges = []
                for i in range(1, 15):
                    high = bars[-i].high
                    low = bars[-i].low
                    prev_close = bars[-i-1].close
                    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                    true_ranges.append(tr)
                atr = sum(true_ranges) / 14
                atr_pips = atr / self.PIP_VALUES.get("JPY" if "JPY" in pair else "DEFAULT")
            else:
                atr = None
                atr_pips = None
            
            # Support and resistance levels
            recent_highs = [bar.high for bar in bars[-20:]]
            recent_lows = [bar.low for bar in bars[-20:]]
            
            analytics = {
                "pair": pair,
                "current": {
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "mid": quote.mid,
                    "spread_pips": quote.spread_pips
                },
                "technicals": {
                    "sma_20": sma_20,
                    "sma_50": sma_50,
                    "atr": atr,
                    "atr_pips": atr_pips,
                    "trend": self._determine_trend(quote.mid, sma_20, sma_50)
                },
                "levels": {
                    "resistance": max(recent_highs) if recent_highs else None,
                    "support": min(recent_lows) if recent_lows else None,
                    "pivot": (max(recent_highs) + min(recent_lows) + quote.mid) / 3 if recent_highs and recent_lows else None
                },
                "recommendation": self._get_fx_recommendation(quote, sma_20, sma_50, atr_pips)
            }
            
            return analytics
            
        except Exception as e:
            logger.error(f"Error analyzing FX pair {pair}: {e}")
            raise
    
    def _determine_trend(
        self,
        current: float,
        sma_20: Optional[float],
        sma_50: Optional[float]
    ) -> str:
        """Determine trend direction."""
        if not sma_20 or not sma_50:
            return "neutral"
        
        if current > sma_20 > sma_50:
            return "strong_bullish"
        elif current > sma_20:
            return "bullish"
        elif current < sma_20 < sma_50:
            return "strong_bearish"
        elif current < sma_20:
            return "bearish"
        else:
            return "neutral"
    
    def _get_fx_recommendation(
        self,
        quote: FXQuote,
        sma_20: Optional[float],
        sma_50: Optional[float],
        atr_pips: Optional[float]
    ) -> Dict[str, Any]:
        """Generate FX trading recommendation."""
        trend = self._determine_trend(quote.mid, sma_20, sma_50)
        
        # Base recommendation on trend
        if trend == "strong_bullish":
            action = "BUY"
            confidence = "high"
        elif trend == "bullish":
            action = "BUY"
            confidence = "medium"
        elif trend == "strong_bearish":
            action = "SELL"
            confidence = "high"
        elif trend == "bearish":
            action = "SELL"
            confidence = "medium"
        else:
            action = "HOLD"
            confidence = "low"
        
        # Calculate suggested levels
        if atr_pips and action != "HOLD":
            if action == "BUY":
                entry = quote.ask
                stop_loss = quote.bid - (atr_pips * 1.5 * self.PIP_VALUES.get("JPY" if "JPY" in quote.pair else "DEFAULT"))
                take_profit = quote.ask + (atr_pips * 2 * self.PIP_VALUES.get("JPY" if "JPY" in quote.pair else "DEFAULT"))
            else:  # SELL
                entry = quote.bid
                stop_loss = quote.ask + (atr_pips * 1.5 * self.PIP_VALUES.get("JPY" if "JPY" in quote.pair else "DEFAULT"))
                take_profit = quote.bid - (atr_pips * 2 * self.PIP_VALUES.get("JPY" if "JPY" in quote.pair else "DEFAULT"))
            
            risk_reward = abs(take_profit - entry) / abs(stop_loss - entry) if stop_loss != entry else 0
        else:
            entry = stop_loss = take_profit = risk_reward = None
        
        return {
            "action": action,
            "confidence": confidence,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": risk_reward,
            "reasoning": f"Trend is {trend}, ATR is {atr_pips:.1f} pips" if atr_pips else f"Trend is {trend}"
        }
    
    async def _update_position(self, pair: str, amount: float, rate: float) -> None:
        """Update internal position tracking."""
        if pair in self.positions:
            pos = self.positions[pair]
            # Update average rate
            if amount * pos.position > 0:  # Adding to position
                total_value = (pos.position * pos.avg_rate) + (amount * rate)
                pos.position += amount
                pos.avg_rate = total_value / pos.position if pos.position != 0 else 0
            else:  # Reducing or reversing position
                pos.position += amount
                if abs(amount) >= abs(pos.position):
                    # Position closed or reversed
                    pos.avg_rate = rate if pos.position != 0 else 0
        else:
            # New position
            self.positions[pair] = FXPosition(
                pair=pair,
                position=amount,
                avg_rate=rate,
                current_rate=rate,
                unrealized_pnl=0,
                realized_pnl=0,
                pnl_pips=0
            )