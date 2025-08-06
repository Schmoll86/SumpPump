"""
Options chain data module.
Handles fetching, caching, and real-time updates of options data.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import aiosqlite
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from src.config import config
from src.models import OptionContract, OptionRight, Greeks
from src.modules.tws.connection import tws_connection


class OptionsChainCache:
    """Manages caching of options chain data."""
    
    def __init__(self):
        """Initialize cache with SQLite backend."""
        self.db_path = config.cache.cache_db_path
        self.ttl_seconds = config.cache.options_chain_cache_ttl
        self._ensure_cache_dir()
        
    def _ensure_cache_dir(self):
        """Ensure cache directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
    async def init_db(self):
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS options_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    expiry TEXT,
                    cache_key TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    UNIQUE(symbol, expiry)
                )
            """)
            await db.commit()
            
    async def get(self, symbol: str, expiry: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached options chain data.
        
        Args:
            symbol: Stock symbol
            expiry: Optional expiry filter
            
        Returns:
            Cached data if valid, None otherwise
        """
        cache_key = f"{symbol}_{expiry or 'all'}"
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT data, timestamp FROM options_cache WHERE cache_key = ?",
                (cache_key,)
            )
            row = await cursor.fetchone()
            
            if row:
                data_str, timestamp = row
                # Check if cache is still valid
                if datetime.now().timestamp() - timestamp < self.ttl_seconds:
                    logger.debug(f"Cache hit for {cache_key}")
                    return json.loads(data_str)
                else:
                    logger.debug(f"Cache expired for {cache_key}")
                    # Clean up expired entry
                    await db.execute("DELETE FROM options_cache WHERE cache_key = ?", (cache_key,))
                    await db.commit()
                    
        return None
        
    async def set(self, symbol: str, expiry: Optional[str], data: List[OptionContract]):
        """
        Cache options chain data.
        
        Args:
            symbol: Stock symbol
            expiry: Optional expiry filter
            data: List of OptionContract objects
        """
        cache_key = f"{symbol}_{expiry or 'all'}"
        
        # Convert OptionContract objects to dicts for serialization
        data_dicts = []
        for opt in data:
            data_dicts.append({
                'symbol': opt.symbol,
                'strike': opt.strike,
                'expiry': opt.expiry.isoformat(),
                'right': opt.right.value,
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
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO options_cache (symbol, expiry, cache_key, data, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, expiry, cache_key, json.dumps(data_dicts), datetime.now().timestamp())
            )
            await db.commit()
            logger.debug(f"Cached data for {cache_key}")
            
    async def clear(self, symbol: Optional[str] = None):
        """
        Clear cache for a symbol or all symbols.
        
        Args:
            symbol: Optional symbol to clear, clears all if None
        """
        async with aiosqlite.connect(self.db_path) as db:
            if symbol:
                await db.execute("DELETE FROM options_cache WHERE symbol = ?", (symbol,))
                logger.info(f"Cleared cache for {symbol}")
            else:
                await db.execute("DELETE FROM options_cache")
                logger.info("Cleared all cache")
            await db.commit()


class OptionsChainData:
    """Main options chain data handler."""
    
    def __init__(self):
        """Initialize data handler with cache."""
        self.cache = OptionsChainCache()
        self._subscriptions: Dict[str, Any] = {}
        
    async def initialize(self):
        """Initialize the data module."""
        await self.cache.init_db()
        logger.info("Options chain data module initialized")
        
    async def fetch_chain(
        self, 
        symbol: str, 
        expiry: Optional[str] = None,
        use_cache: bool = True
    ) -> List[OptionContract]:
        """
        Fetch options chain with caching support.
        
        Args:
            symbol: Stock symbol
            expiry: Optional expiry filter (YYYY-MM-DD)
            use_cache: Whether to use cache
            
        Returns:
            List of OptionContract objects
        """
        # Check cache first if enabled
        if use_cache:
            cached_data = await self.cache.get(symbol, expiry)
            if cached_data:
                # Convert cached dicts back to OptionContract objects
                options = []
                for data in cached_data:
                    greeks = Greeks(
                        delta=data['greeks']['delta'],
                        gamma=data['greeks']['gamma'],
                        theta=data['greeks']['theta'],
                        vega=data['greeks']['vega'],
                        rho=data['greeks']['rho']
                    )
                    
                    opt = OptionContract(
                        symbol=data['symbol'],
                        strike=data['strike'],
                        expiry=datetime.fromisoformat(data['expiry']),
                        right=OptionRight.CALL if data['right'] == 'C' else OptionRight.PUT,
                        bid=data['bid'],
                        ask=data['ask'],
                        last=data['last'],
                        volume=data['volume'],
                        open_interest=data['open_interest'],
                        iv=data['iv'],
                        greeks=greeks,
                        underlying_price=data['underlying_price']
                    )
                    options.append(opt)
                    
                return options
        
        # Fetch fresh data from TWS with limited market data lines
        logger.info(f"Fetching fresh options chain for {symbol} (limited to avoid 100 line limit)")
        # Use limited parameters to stay within IBKR's constraints
        options = await tws_connection.get_options_chain(
            symbol, 
            expiry,
            max_strikes=5,  # Limit strikes to 5 around ATM
            strike_range_pct=0.10  # Only ±10% from spot
        )
        
        # Cache the results
        if use_cache and options:
            await self.cache.set(symbol, expiry, options)
        
        return options
    
    async def get_statistics(self, symbol: str) -> Dict[str, Any]:
        """
        Get options statistics for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with put/call ratios, IV rank, etc.
        """
        # Fetch full chain for statistics
        options = await self.fetch_chain(symbol)
        
        if not options:
            return {
                'symbol': symbol,
                'error': 'No options data available'
            }
        
        # Calculate statistics
        total_call_volume = sum(opt.volume for opt in options if opt.right == OptionRight.CALL)
        total_put_volume = sum(opt.volume for opt in options if opt.right == OptionRight.PUT)
        total_call_oi = sum(opt.open_interest for opt in options if opt.right == OptionRight.CALL)
        total_put_oi = sum(opt.open_interest for opt in options if opt.right == OptionRight.PUT)
        
        # Calculate average IV by expiry
        iv_by_expiry = {}
        for opt in options:
            expiry_str = opt.expiry.strftime('%Y-%m-%d')
            if expiry_str not in iv_by_expiry:
                iv_by_expiry[expiry_str] = []
            if opt.iv > 0:  # Filter out zero IVs
                iv_by_expiry[expiry_str].append(opt.iv)
        
        avg_iv_by_expiry = {
            expiry: sum(ivs) / len(ivs) if ivs else 0
            for expiry, ivs in iv_by_expiry.items()
        }
        
        # Find ATM IV (closest strike to underlying price)
        underlying_price = options[0].underlying_price if options else 0
        atm_options = sorted(options, key=lambda x: abs(x.strike - underlying_price))
        atm_iv = atm_options[0].iv if atm_options else 0
        
        return {
            'symbol': symbol,
            'underlying_price': underlying_price,
            'put_call_ratio_volume': total_put_volume / total_call_volume if total_call_volume > 0 else 0,
            'put_call_ratio_oi': total_put_oi / total_call_oi if total_call_oi > 0 else 0,
            'total_volume': total_call_volume + total_put_volume,
            'total_open_interest': total_call_oi + total_put_oi,
            'atm_iv': atm_iv,
            'iv_by_expiry': avg_iv_by_expiry,
            'timestamp': datetime.now().isoformat()
        }
    
    async def subscribe_to_updates(
        self, 
        symbol: str, 
        strikes: List[float],
        expiry: str,
        callback: Optional[Any] = None
    ) -> str:
        """
        Subscribe to real-time updates for specific options.
        
        Args:
            symbol: Stock symbol
            strikes: List of strike prices to monitor
            expiry: Expiration date (YYYY-MM-DD)
            callback: Optional callback function for updates
            
        Returns:
            Subscription ID
        """
        subscription_id = f"{symbol}_{expiry}_{'_'.join(map(str, strikes))}"
        
        # Convert expiry to YYYYMMDD format
        expiry_yyyymmdd = datetime.strptime(expiry, '%Y-%m-%d').strftime('%Y%m%d')
        
        # Create contracts and subscribe
        tickers = []
        for strike in strikes:
            for right in ['C', 'P']:
                contract = tws_connection.create_option_contract(
                    symbol, expiry_yyyymmdd, strike, right
                )
                ticker = await tws_connection.subscribe_to_market_data(contract)
                tickers.append(ticker)
        
        self._subscriptions[subscription_id] = {
            'tickers': tickers,
            'callback': callback,
            'symbol': symbol,
            'strikes': strikes,
            'expiry': expiry
        }
        
        logger.info(f"Created subscription {subscription_id}")
        return subscription_id
    
    async def unsubscribe(self, subscription_id: str):
        """
        Unsubscribe from real-time updates.
        
        Args:
            subscription_id: Subscription ID to cancel
        """
        if subscription_id in self._subscriptions:
            # Cancel market data for all tickers
            for ticker in self._subscriptions[subscription_id]['tickers']:
                tws_connection.ib.cancelMktData(ticker.contract)
            
            del self._subscriptions[subscription_id]
            logger.info(f"Cancelled subscription {subscription_id}")
    
    async def clear_symbol_cache(self, symbol: str):
        """
        Clear cache for a specific symbol.
        
        Args:
            symbol: Stock symbol to clear
        """
        await self.cache.clear(symbol)
        logger.info(f"Cleared cache for {symbol}")


# Global instance
options_data = OptionsChainData()