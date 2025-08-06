"""
Cryptocurrency trading module via ZEROHASH/PAXOS.
Provides crypto quotes, trading, and market data.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from ib_async import Crypto, Contract, MarketOrder, LimitOrder
from loguru import logger

from src.core import (
    rate_limited,
    with_connection_retry,
    MarketDataError,
    TradingError,
    OrderValidationError
)


class CryptoExchange(Enum):
    """Available crypto exchanges through IBKR."""
    PAXOS = "PAXOS"          # Main crypto exchange
    ZEROHASH = "ZEROHASH"    # Alternative routing
    COINBASE = "COINBASE"    # Coinbase routing


@dataclass
class CryptoQuote:
    """Cryptocurrency quote data."""
    symbol: str
    base_currency: str
    quote_currency: str
    exchange: str
    bid: float
    ask: float
    last: float
    spread: float
    spread_pct: float
    volume_24h: float
    high_24h: float
    low_24h: float
    change_24h: float
    change_24h_pct: float
    timestamp: datetime
    
    @property
    def mid_price(self) -> float:
        """Calculate mid price."""
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last or 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "base": self.base_currency,
            "quote": self.quote_currency,
            "exchange": self.exchange,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": self.mid_price,
            "spread": self.spread,
            "spread_pct": self.spread_pct,
            "volume_24h": self.volume_24h,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "change_24h": self.change_24h,
            "change_24h_pct": self.change_24h_pct,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class CryptoPosition:
    """Crypto position data."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    pnl_pct: float


class CryptoTrading:
    """
    Cryptocurrency trading via IBKR's crypto exchanges.
    Supports BTC, ETH, and other major cryptocurrencies.
    """
    
    # Supported crypto pairs
    SUPPORTED_CRYPTOS = {
        "BTC": {"base": "BTC", "quote": "USD", "min_size": 0.0001},
        "ETH": {"base": "ETH", "quote": "USD", "min_size": 0.001},
        "LTC": {"base": "LTC", "quote": "USD", "min_size": 0.01},
        "BCH": {"base": "BCH", "quote": "USD", "min_size": 0.01},
        "LINK": {"base": "LINK", "quote": "USD", "min_size": 0.1},
        "UNI": {"base": "UNI", "quote": "USD", "min_size": 0.1},
        "MATIC": {"base": "MATIC", "quote": "USD", "min_size": 1.0},
        "ADA": {"base": "ADA", "quote": "USD", "min_size": 1.0},
        "DOT": {"base": "DOT", "quote": "USD", "min_size": 0.1},
        "AVAX": {"base": "AVAX", "quote": "USD", "min_size": 0.1},
        "SOL": {"base": "SOL", "quote": "USD", "min_size": 0.01},
        "DOGE": {"base": "DOGE", "quote": "USD", "min_size": 10.0}
    }
    
    def __init__(self, tws_connection, default_exchange: CryptoExchange = CryptoExchange.PAXOS):
        """
        Initialize crypto trading module.
        
        Args:
            tws_connection: Active TWS connection
            default_exchange: Default crypto exchange to use
        """
        self.tws = tws_connection
        self.default_exchange = default_exchange
        self.active_subscriptions: Dict[str, Any] = {}
        self.positions: Dict[str, CryptoPosition] = {}
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data")
    async def get_crypto_quote(
        self,
        symbol: str,
        quote_currency: str = "USD",
        exchange: Optional[CryptoExchange] = None
    ) -> CryptoQuote:
        """
        Get cryptocurrency quote.
        
        Args:
            symbol: Crypto symbol (BTC, ETH, etc.)
            quote_currency: Quote currency (USD, EUR, etc.)
            exchange: Exchange to use (defaults to configured)
            
        Returns:
            CryptoQuote with current market data
        """
        try:
            await self.tws.ensure_connected()
            
            # Validate symbol
            symbol = symbol.upper()
            if symbol not in self.SUPPORTED_CRYPTOS:
                raise ValueError(f"Unsupported crypto: {symbol}. Supported: {list(self.SUPPORTED_CRYPTOS.keys())}")
            
            crypto_info = self.SUPPORTED_CRYPTOS[symbol]
            exchange = exchange or self.default_exchange
            
            # Create crypto contract
            contract = Crypto(
                symbol=crypto_info["base"],
                exchange=exchange.value,
                currency=quote_currency
            )
            
            # Qualify contract
            qualified = await self.tws.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise MarketDataError(f"Could not qualify crypto contract {symbol}")
            contract = qualified[0]
            
            # Request market data
            ticker = self.tws.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(2)  # Wait for data
            
            # Calculate metrics
            bid = ticker.bid or 0
            ask = ticker.ask or 0
            last = ticker.last or 0
            spread = ask - bid if bid and ask else 0
            spread_pct = (spread / ((bid + ask) / 2) * 100) if bid and ask else 0
            
            # 24h change (would need historical data for accurate calculation)
            high_24h = ticker.high or last
            low_24h = ticker.low or last
            prev_close = ticker.close or last
            change_24h = last - prev_close if prev_close else 0
            change_24h_pct = (change_24h / prev_close * 100) if prev_close else 0
            
            crypto_quote = CryptoQuote(
                symbol=symbol,
                base_currency=crypto_info["base"],
                quote_currency=quote_currency,
                exchange=exchange.value,
                bid=bid,
                ask=ask,
                last=last,
                spread=spread,
                spread_pct=spread_pct,
                volume_24h=ticker.volume or 0,
                high_24h=high_24h,
                low_24h=low_24h,
                change_24h=change_24h,
                change_24h_pct=change_24h_pct,
                timestamp=datetime.now()
            )
            
            # Cancel market data
            self.tws.ib.cancelMktData(contract)
            
            logger.info(f"Crypto quote {symbol}: ${last:.2f} ({change_24h_pct:+.2f}%)")
            
            return crypto_quote
            
        except Exception as e:
            logger.error(f"Error getting crypto quote for {symbol}: {e}")
            raise MarketDataError(f"Failed to get crypto quote: {e}")
    
    @with_connection_retry()
    @rate_limited(operation_type="order")
    async def place_crypto_order(
        self,
        symbol: str,
        quantity: float,
        side: str,  # "BUY" or "SELL"
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Place cryptocurrency order.
        
        Args:
            symbol: Crypto symbol (BTC, ETH, etc.)
            quantity: Amount to trade
            side: BUY or SELL
            order_type: MARKET, LIMIT, or STOP_LIMIT
            limit_price: Limit price for LIMIT orders
            stop_price: Stop price for STOP orders
            
        Returns:
            Order execution details
        """
        try:
            await self.tws.ensure_connected()
            
            # Validate symbol and quantity
            symbol = symbol.upper()
            if symbol not in self.SUPPORTED_CRYPTOS:
                raise OrderValidationError(f"Unsupported crypto: {symbol}")
            
            crypto_info = self.SUPPORTED_CRYPTOS[symbol]
            min_size = crypto_info["min_size"]
            
            if quantity < min_size:
                raise OrderValidationError(
                    f"Quantity {quantity} below minimum {min_size} for {symbol}",
                    field="quantity",
                    value=quantity
                )
            
            # Create crypto contract
            contract = Crypto(
                symbol=crypto_info["base"],
                exchange=self.default_exchange.value,
                currency="USD"
            )
            
            # Qualify contract
            qualified = await self.tws.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise TradingError(f"Could not qualify crypto contract {symbol}")
            contract = qualified[0]
            
            # Create order based on type
            if order_type == "MARKET":
                order = MarketOrder(
                    action="BUY" if side.upper() == "BUY" else "SELL",
                    totalQuantity=quantity
                )
            elif order_type == "LIMIT":
                if not limit_price:
                    raise OrderValidationError("Limit price required for LIMIT order")
                order = LimitOrder(
                    action="BUY" if side.upper() == "BUY" else "SELL",
                    totalQuantity=quantity,
                    lmtPrice=limit_price
                )
            else:
                raise OrderValidationError(f"Unsupported order type: {order_type}")
            
            # Place order
            logger.info(f"Placing crypto {side} order: {quantity} {symbol} @ {order_type}")
            trade = self.tws.ib.placeOrder(contract, order)
            
            # Wait for fill
            await asyncio.sleep(2)
            
            # Check order status
            if trade.orderStatus.status == 'Filled':
                avg_price = trade.orderStatus.avgFillPrice
                filled_qty = trade.orderStatus.filled
                
                result = {
                    "status": "filled",
                    "symbol": symbol,
                    "side": side,
                    "quantity": filled_qty,
                    "avg_price": avg_price,
                    "total_value": avg_price * filled_qty,
                    "order_id": trade.order.orderId,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Update positions
                await self._update_position(symbol, filled_qty if side == "BUY" else -filled_qty, avg_price)
                
                logger.info(f"Crypto order filled: {filled_qty} {symbol} @ ${avg_price:.2f}")
                
            else:
                result = {
                    "status": trade.orderStatus.status.lower(),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_id": trade.order.orderId,
                    "message": f"Order {trade.orderStatus.status}"
                }
                
                logger.warning(f"Crypto order not filled: {trade.orderStatus.status}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error placing crypto order: {e}")
            raise TradingError(f"Failed to place crypto order: {e}")
    
    async def get_crypto_positions(self) -> List[CryptoPosition]:
        """
        Get current crypto positions.
        
        Returns:
            List of CryptoPosition objects
        """
        try:
            await self.tws.ensure_connected()
            
            # Get account positions
            positions = self.tws.ib.positions()
            crypto_positions = []
            
            for pos in positions:
                # Check if it's a crypto position
                if pos.contract.secType == 'CRYPTO':
                    symbol = pos.contract.symbol
                    
                    # Get current price
                    quote = await self.get_crypto_quote(symbol)
                    current_price = quote.last
                    
                    # Calculate P&L
                    market_value = pos.position * current_price
                    unrealized_pnl = market_value - (pos.position * pos.avgCost)
                    pnl_pct = (unrealized_pnl / (pos.position * pos.avgCost) * 100) if pos.avgCost else 0
                    
                    crypto_pos = CryptoPosition(
                        symbol=symbol,
                        quantity=pos.position,
                        avg_cost=pos.avgCost,
                        current_price=current_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=0,  # Would need to track trades
                        pnl_pct=pnl_pct
                    )
                    
                    crypto_positions.append(crypto_pos)
                    self.positions[symbol] = crypto_pos
            
            return crypto_positions
            
        except Exception as e:
            logger.error(f"Error getting crypto positions: {e}")
            raise
    
    async def get_crypto_history(
        self,
        symbol: str,
        period: str = "1d",
        interval: str = "5m"
    ) -> List[Dict[str, Any]]:
        """
        Get historical crypto data.
        
        Args:
            symbol: Crypto symbol
            period: Time period (1d, 1w, 1m, etc.)
            interval: Bar interval (1m, 5m, 1h, 1d, etc.)
            
        Returns:
            List of historical bars
        """
        try:
            await self.tws.ensure_connected()
            
            # Validate symbol
            symbol = symbol.upper()
            if symbol not in self.SUPPORTED_CRYPTOS:
                raise ValueError(f"Unsupported crypto: {symbol}")
            
            crypto_info = self.SUPPORTED_CRYPTOS[symbol]
            
            # Create contract
            contract = Crypto(
                symbol=crypto_info["base"],
                exchange=self.default_exchange.value,
                currency="USD"
            )
            
            # Get historical data
            bars = await self.tws.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr=period,
                barSizeSetting=interval,
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=1
            )
            
            # Convert to list of dicts
            history = []
            for bar in bars:
                history.append({
                    "timestamp": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting crypto history: {e}")
            raise MarketDataError(f"Failed to get crypto history: {e}")
    
    async def get_crypto_analysis(self, symbol: str) -> Dict[str, Any]:
        """
        Get comprehensive crypto analysis.
        
        Args:
            symbol: Crypto symbol
            
        Returns:
            Analysis including technicals and metrics
        """
        try:
            # Get quote
            quote = await self.get_crypto_quote(symbol)
            
            # Get recent history for technical analysis
            history = await self.get_crypto_history(symbol, "1d", "5m")
            
            # Calculate technical indicators
            closes = [bar["close"] for bar in history]
            
            # Simple moving averages
            sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
            sma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
            
            # Volatility (simple standard deviation)
            if len(closes) >= 20:
                mean = sum(closes[-20:]) / 20
                variance = sum((x - mean) ** 2 for x in closes[-20:]) / 20
                volatility = variance ** 0.5
            else:
                volatility = None
            
            # RSI calculation (simplified)
            if len(closes) >= 14:
                gains = []
                losses = []
                for i in range(1, 14):
                    change = closes[-i] - closes[-i-1]
                    if change > 0:
                        gains.append(change)
                    else:
                        losses.append(abs(change))
                
                avg_gain = sum(gains) / 14 if gains else 0
                avg_loss = sum(losses) / 14 if losses else 0
                
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100 if avg_gain > 0 else 50
            else:
                rsi = None
            
            analysis = {
                "symbol": symbol,
                "current_price": quote.last,
                "bid": quote.bid,
                "ask": quote.ask,
                "spread_pct": quote.spread_pct,
                "change_24h_pct": quote.change_24h_pct,
                "volume_24h": quote.volume_24h,
                "technical": {
                    "sma_20": sma_20,
                    "sma_50": sma_50,
                    "rsi": rsi,
                    "volatility": volatility,
                    "trend": "bullish" if quote.last > sma_20 else "bearish" if sma_20 else "neutral"
                },
                "levels": {
                    "support": quote.low_24h,
                    "resistance": quote.high_24h,
                    "pivot": (quote.high_24h + quote.low_24h + quote.last) / 3
                },
                "recommendation": self._get_crypto_recommendation(quote, rsi, sma_20)
            }
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing crypto {symbol}: {e}")
            raise
    
    def _get_crypto_recommendation(
        self,
        quote: CryptoQuote,
        rsi: Optional[float],
        sma: Optional[float]
    ) -> str:
        """Generate trading recommendation based on indicators."""
        signals = []
        
        # RSI signals
        if rsi:
            if rsi < 30:
                signals.append("oversold")
            elif rsi > 70:
                signals.append("overbought")
        
        # Trend signals
        if sma and quote.last > sma:
            signals.append("above_ma")
        elif sma and quote.last < sma:
            signals.append("below_ma")
        
        # Volume signals
        if quote.volume_24h > 0:  # Would need average volume for comparison
            signals.append("active")
        
        # Generate recommendation
        if "oversold" in signals and "above_ma" in signals:
            return "Strong Buy"
        elif "oversold" in signals:
            return "Buy"
        elif "overbought" in signals and "below_ma" in signals:
            return "Strong Sell"
        elif "overbought" in signals:
            return "Sell"
        else:
            return "Hold"
    
    async def _update_position(self, symbol: str, quantity: float, price: float) -> None:
        """Update internal position tracking."""
        if symbol in self.positions:
            pos = self.positions[symbol]
            # Update average cost
            if quantity > 0:  # Buy
                total_cost = (pos.quantity * pos.avg_cost) + (quantity * price)
                pos.quantity += quantity
                pos.avg_cost = total_cost / pos.quantity if pos.quantity > 0 else 0
            else:  # Sell
                pos.quantity += quantity  # quantity is negative
                if pos.quantity <= 0:
                    del self.positions[symbol]
        else:
            # New position
            if quantity > 0:
                self.positions[symbol] = CryptoPosition(
                    symbol=symbol,
                    quantity=quantity,
                    avg_cost=price,
                    current_price=price,
                    market_value=quantity * price,
                    unrealized_pnl=0,
                    realized_pnl=0,
                    pnl_pct=0
                )