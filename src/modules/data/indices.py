"""
Index trading module for NASDAQ, CME S&P, and other indices.
Provides access to index options and futures.
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass
from enum import Enum

from ib_async import Index, FuturesOption, Option, Contract
from loguru import logger

from src.core import (
    rate_limited,
    with_connection_retry,
    MarketDataError,
    InvalidStrategyError
)
from src.models import OptionContract, OptionRight, Greeks


class IndexExchange(Enum):
    """Major index exchanges."""
    CBOE = "CBOE"      # SPX, VIX
    CME = "CME"        # ES futures
    NASDAQ = "NASDAQ"  # NDX
    ONE = "ONE"        # Cboe One
    GLOBEX = "GLOBEX"  # Futures


@dataclass
class IndexData:
    """Index market data."""
    symbol: str
    exchange: str
    last_price: float
    change: float
    change_pct: float
    volume: int
    high: float
    low: float
    open: float
    close: float
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "last_price": self.last_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "high": self.high,
            "low": self.low,
            "open": self.open,
            "close": self.close,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class IndexOption:
    """Index option contract."""
    symbol: str
    strike: float
    expiry: date
    right: OptionRight
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    iv: float
    greeks: Optional[Greeks]
    multiplier: int
    exchange: str
    
    @property
    def mid_price(self) -> float:
        """Calculate mid price."""
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last or 0


class IndexTrading:
    """
    Index trading module for major indices.
    Supports SPX, NDX, VIX, RUT, DJX options and futures.
    """
    
    # Major index configurations
    INDEX_CONFIG = {
        "SPX": {
            "exchange": "CBOE",
            "multiplier": 100,
            "currency": "USD",
            "description": "S&P 500 Index"
        },
        "NDX": {
            "exchange": "NASDAQ",
            "multiplier": 100,
            "currency": "USD",
            "description": "NASDAQ-100 Index"
        },
        "RUT": {
            "exchange": "RUSSELL",
            "multiplier": 100,
            "currency": "USD",
            "description": "Russell 2000 Index"
        },
        "VIX": {
            "exchange": "CBOE",
            "multiplier": 100,
            "currency": "USD",
            "description": "CBOE Volatility Index"
        },
        "DJX": {
            "exchange": "CBOE",
            "multiplier": 100,
            "currency": "USD",
            "description": "Dow Jones Index (1/100)"
        },
        "XSP": {
            "exchange": "CBOE",
            "multiplier": 100,
            "currency": "USD",
            "description": "Mini-SPX Index (1/10)"
        }
    }
    
    def __init__(self, tws_connection):
        """
        Initialize index trading module.
        
        Args:
            tws_connection: Active TWS connection
        """
        self.tws = tws_connection
        self.subscriptions: Dict[str, Any] = {}
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data")
    async def get_index_quote(self, symbol: str) -> IndexData:
        """
        Get current index quote.
        
        Args:
            symbol: Index symbol (SPX, NDX, etc.)
            
        Returns:
            IndexData with current quote
        """
        try:
            await self.tws.ensure_connected()
            
            # Get index configuration
            config = self.INDEX_CONFIG.get(symbol.upper())
            if not config:
                raise ValueError(f"Unknown index symbol: {symbol}")
            
            # Create index contract
            contract = Index(symbol, config["exchange"], config["currency"])
            await self.tws.ib.qualifyContractsAsync(contract)
            
            # Request market data
            ticker = self.tws.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(2)  # Wait for data
            
            # Get quote data
            last_price = ticker.last or ticker.close or 0
            prev_close = ticker.close or last_price
            
            index_data = IndexData(
                symbol=symbol,
                exchange=config["exchange"],
                last_price=last_price,
                change=last_price - prev_close if prev_close else 0,
                change_pct=((last_price - prev_close) / prev_close * 100) if prev_close else 0,
                volume=ticker.volume or 0,
                high=ticker.high or last_price,
                low=ticker.low or last_price,
                open=ticker.open or prev_close,
                close=ticker.close or last_price,
                timestamp=datetime.now()
            )
            
            # Cancel market data
            self.tws.ib.cancelMktData(contract)
            
            logger.info(f"Index quote for {symbol}: {last_price:.2f} ({index_data.change_pct:+.2f}%)")
            
            return index_data
            
        except Exception as e:
            logger.error(f"Error getting index quote for {symbol}: {e}")
            raise MarketDataError(f"Failed to get index quote: {e}")
    
    @with_connection_retry()
    @rate_limited(operation_type="market_data", weight=5)
    async def get_index_options(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        strike_range_pct: float = 0.1,
        max_strikes: int = 20
    ) -> List[IndexOption]:
        """
        Get index options chain.
        
        Args:
            symbol: Index symbol (SPX, NDX, etc.)
            expiry: Optional expiry date (YYYY-MM-DD)
            strike_range_pct: Strike range as percentage of spot
            max_strikes: Maximum strikes to return
            
        Returns:
            List of IndexOption contracts
        """
        try:
            await self.tws.ensure_connected()
            
            # Get index configuration
            config = self.INDEX_CONFIG.get(symbol.upper())
            if not config:
                raise ValueError(f"Unknown index symbol: {symbol}")
            
            # Get current index price
            index_quote = await self.get_index_quote(symbol)
            spot_price = index_quote.last_price
            
            logger.info(f"Fetching index options for {symbol} at {spot_price:.2f}")
            
            # Get option chain parameters
            underlying = Index(symbol, config["exchange"], config["currency"])
            await self.tws.ib.qualifyContractsAsync(underlying)
            
            chains = await self.tws.ib.reqSecDefOptParamsAsync(
                symbol, config["exchange"], "IND", underlying.conId
            )
            
            if not chains:
                logger.warning(f"No option chains found for {symbol}")
                return []
            
            options_list = []
            
            # Get available expiries
            all_expiries = set()
            for chain in chains:
                all_expiries.update(chain.expirations)
            sorted_expiries = sorted(all_expiries)
            
            # Filter expiries
            if expiry:
                target_expiry = datetime.strptime(expiry, '%Y-%m-%d').strftime('%Y%m%d')
                expiries_to_fetch = [target_expiry] if target_expiry in sorted_expiries else []
            else:
                # Get next 3 expiries
                expiries_to_fetch = sorted_expiries[:3]
            
            # Calculate strike range
            min_strike = spot_price * (1 - strike_range_pct)
            max_strike = spot_price * (1 + strike_range_pct)
            
            for expiry_str in expiries_to_fetch:
                # Find chain with this expiry
                chain_to_use = None
                for chain in chains:
                    if expiry_str in chain.expirations:
                        chain_to_use = chain
                        break
                
                if not chain_to_use:
                    continue
                
                # Get relevant strikes
                strikes = [s for s in chain_to_use.strikes if min_strike <= s <= max_strike]
                strikes.sort(key=lambda x: abs(x - spot_price))
                strikes = strikes[:max_strikes]
                
                logger.info(f"Processing {len(strikes)} strikes for {expiry_str}")
                
                # Fetch option data for each strike
                for strike in strikes:
                    for right in ['C', 'P']:
                        try:
                            # Create option contract
                            option = Option(
                                symbol,
                                expiry_str,
                                strike,
                                right,
                                config["exchange"],
                                multiplier=config["multiplier"],
                                currency=config["currency"]
                            )
                            
                            # Qualify contract
                            qualified = await self.tws.ib.qualifyContractsAsync(option)
                            if not qualified:
                                continue
                            option = qualified[0]
                            
                            # Request market data
                            ticker = self.tws.ib.reqMktData(option, '', False, False)
                            await asyncio.sleep(0.5)  # Brief wait for data
                            
                            # Parse expiry
                            expiry_date = datetime.strptime(expiry_str, '%Y%m%d').date()
                            
                            # Create Greeks object if available
                            greeks = None
                            if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks:
                                mg = ticker.modelGreeks
                                greeks = Greeks()
                                if hasattr(mg, 'delta'): greeks.delta = mg.delta
                                if hasattr(mg, 'gamma'): greeks.gamma = mg.gamma
                                if hasattr(mg, 'vega'): greeks.vega = mg.vega
                                if hasattr(mg, 'theta'): greeks.theta = mg.theta
                            
                            # Create index option
                            index_option = IndexOption(
                                symbol=symbol,
                                strike=strike,
                                expiry=expiry_date,
                                right=OptionRight.CALL if right == 'C' else OptionRight.PUT,
                                bid=ticker.bid or 0,
                                ask=ticker.ask or 0,
                                last=ticker.last or 0,
                                volume=ticker.volume or 0,
                                open_interest=0,  # Would need historical data request
                                iv=ticker.modelGreeks.impliedVol if hasattr(ticker, 'modelGreeks') and ticker.modelGreeks else 0,
                                greeks=greeks,
                                multiplier=config["multiplier"],
                                exchange=config["exchange"]
                            )
                            
                            options_list.append(index_option)
                            
                            # Cancel market data
                            self.tws.ib.cancelMktData(option)
                            
                        except Exception as e:
                            logger.debug(f"Error fetching {symbol} {expiry_str} {strike} {right}: {e}")
                            continue
            
            logger.info(f"Retrieved {len(options_list)} index options for {symbol}")
            return options_list
            
        except Exception as e:
            logger.error(f"Error getting index options for {symbol}: {e}")
            raise MarketDataError(f"Failed to get index options: {e}")
    
    async def get_index_futures(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get index futures contracts.
        
        Args:
            symbol: Index symbol (ES for S&P, NQ for NASDAQ, etc.)
            
        Returns:
            List of futures contracts
        """
        # Map index to futures symbols
        futures_map = {
            "SPX": "ES",  # E-mini S&P 500
            "NDX": "NQ",  # E-mini NASDAQ-100
            "RUT": "RTY", # E-mini Russell 2000
            "DJX": "YM"   # E-mini Dow
        }
        
        futures_symbol = futures_map.get(symbol, symbol)
        
        try:
            await self.tws.ensure_connected()
            
            # Create futures contract
            from ib_async import Future
            
            # Get front month future
            contract = Future(futures_symbol, exchange='GLOBEX')
            contracts = await self.tws.ib.reqContractDetailsAsync(contract)
            
            futures_data = []
            for contract_details in contracts[:5]:  # Get next 5 expiries
                contract = contract_details.contract
                
                # Get market data
                ticker = self.tws.ib.reqMktData(contract, '', False, False)
                await asyncio.sleep(1)
                
                futures_data.append({
                    "symbol": futures_symbol,
                    "expiry": contract.lastTradeDateOrContractMonth,
                    "exchange": "GLOBEX",
                    "multiplier": contract_details.multiplier,
                    "bid": ticker.bid or 0,
                    "ask": ticker.ask or 0,
                    "last": ticker.last or 0,
                    "volume": ticker.volume or 0,
                    "open_interest": 0  # Would need additional request
                })
                
                self.tws.ib.cancelMktData(contract)
            
            return futures_data
            
        except Exception as e:
            logger.error(f"Error getting futures for {symbol}: {e}")
            raise MarketDataError(f"Failed to get futures: {e}")
    
    async def calculate_index_spread(
        self,
        symbol: str,
        expiry: str,
        call_strike: float,
        put_strike: float
    ) -> Dict[str, Any]:
        """
        Calculate index spread strategy (bull call, bear put, etc).
        
        Args:
            symbol: Index symbol
            expiry: Expiry date (YYYY-MM-DD)
            call_strike: Call option strike
            put_strike: Put option strike
            
        Returns:
            Spread analysis
        """
        try:
            # Get options data
            options = await self.get_index_options(symbol, expiry)
            
            # Find specific options
            call_option = None
            put_option = None
            
            for opt in options:
                if opt.strike == call_strike and opt.right == OptionRight.CALL:
                    call_option = opt
                if opt.strike == put_strike and opt.right == OptionRight.PUT:
                    put_option = opt
            
            if not call_option or not put_option:
                raise InvalidStrategyError(
                    f"Could not find options for spread",
                    f"Missing strikes: Call={call_strike}, Put={put_strike}"
                )
            
            # Calculate spread metrics
            config = self.INDEX_CONFIG[symbol]
            multiplier = config["multiplier"]
            
            # Example: Iron Condor
            spread_analysis = {
                "symbol": symbol,
                "expiry": expiry,
                "multiplier": multiplier,
                "call_strike": call_strike,
                "put_strike": put_strike,
                "call_premium": call_option.mid_price,
                "put_premium": put_option.mid_price,
                "total_credit": (call_option.bid + put_option.bid) * multiplier,
                "total_debit": (call_option.ask + put_option.ask) * multiplier,
                "max_profit": (call_option.bid + put_option.bid) * multiplier,
                "max_loss": abs(call_strike - put_strike) * multiplier - (call_option.bid + put_option.bid) * multiplier,
                "breakeven_upper": call_strike + call_option.bid + put_option.bid,
                "breakeven_lower": put_strike - call_option.bid - put_option.bid,
                "call_iv": call_option.iv,
                "put_iv": put_option.iv,
                "call_delta": call_option.greeks.delta if call_option.greeks else None,
                "put_delta": put_option.greeks.delta if put_option.greeks else None
            }
            
            return spread_analysis
            
        except Exception as e:
            logger.error(f"Error calculating index spread: {e}")
            raise
    
    async def get_vix_term_structure(self) -> List[Dict[str, Any]]:
        """
        Get VIX term structure for volatility analysis.
        
        Returns:
            VIX futures term structure
        """
        try:
            # Get VIX futures
            vix_futures = await self.get_index_futures("VIX")
            
            # Sort by expiry
            vix_futures.sort(key=lambda x: x["expiry"])
            
            # Calculate term structure metrics
            term_structure = []
            spot_vix = await self.get_index_quote("VIX")
            
            for i, future in enumerate(vix_futures):
                days_to_expiry = (datetime.strptime(future["expiry"], '%Y%m%d') - datetime.now()).days
                
                term_structure.append({
                    "expiry": future["expiry"],
                    "days_to_expiry": days_to_expiry,
                    "price": future["last"],
                    "contango": future["last"] - spot_vix.last_price,
                    "contango_pct": (future["last"] - spot_vix.last_price) / spot_vix.last_price * 100,
                    "bid": future["bid"],
                    "ask": future["ask"],
                    "volume": future["volume"]
                })
            
            return term_structure
            
        except Exception as e:
            logger.error(f"Error getting VIX term structure: {e}")
            raise MarketDataError(f"Failed to get VIX term structure: {e}")