"""
Market scanner module for finding trading opportunities.
Scans for high IV stocks, unusual options activity, and potential setups.
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger

from ib_async import Stock, Option, ScannerSubscription, TagValue


class MarketScanner:
    """Scans market for trading opportunities."""
    
    def __init__(self, tws_connection):
        """Initialize scanner with TWS connection."""
        self.tws = tws_connection
        self.ib = None
        
    async def ensure_connected(self):
        """Ensure TWS is connected."""
        if not self.tws.connected:
            await self.tws.connect()
        self.ib = self.tws.ib
        
    async def scan_high_iv_stocks(self, min_iv_rank: float = 50) -> List[Dict[str, Any]]:
        """
        Scan for stocks with high implied volatility.
        
        Args:
            min_iv_rank: Minimum IV rank to include (0-100)
            
        Returns:
            List of high IV stocks with details
        """
        try:
            await self.ensure_connected()
            
            # Use TWS scanner for high IV stocks
            sub = ScannerSubscription(
                instrument='STK',
                locationCode='STK.US.MAJOR',
                scanCode='HIGH_OPT_IMP_VOLAT'
            )
            
            # Request scanner data
            scan_data = await self.ib.reqScannerDataAsync(sub)
            
            results = []
            for item in scan_data[:20]:  # Limit to top 20
                contract = item.contractDetails.contract
                
                # Get current quote
                ticker = self.ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(0.5)
                
                results.append({
                    'symbol': contract.symbol,
                    'price': ticker.last if ticker.last > 0 else ticker.close,
                    'volume': ticker.volume,
                    'rank': item.rank,
                    'distance': item.distance,
                    'benchmark': item.benchmark,
                    'projection': item.projection,
                    'iv_indication': 'HIGH'
                })
                
                self.ib.cancelMktData(contract)
                
            logger.info(f"Found {len(results)} high IV stocks")
            return results
            
        except Exception as e:
            logger.error(f"Error scanning high IV stocks: {e}")
            return []
    
    async def scan_unusual_options_volume(self, min_volume_ratio: float = 2.0) -> List[Dict[str, Any]]:
        """
        Scan for unusual options activity.
        
        Args:
            min_volume_ratio: Minimum volume/OI ratio
            
        Returns:
            List of options with unusual volume
        """
        try:
            await self.ensure_connected()
            
            # Use TWS scanner for high options volume
            sub = ScannerSubscription(
                instrument='OPT.US',
                locationCode='OPT.US',
                scanCode='HIGH_OPT_VOLUME_PUT_CALL_RATIO'
            )
            
            scan_data = await self.ib.reqScannerDataAsync(sub)
            
            results = []
            for item in scan_data[:15]:  # Top 15 unusual activity
                contract = item.contractDetails.contract
                
                # Get option details
                ticker = self.ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(0.5)
                
                if ticker.volume and ticker.volume > 0:
                    volume_oi_ratio = ticker.volume / max(ticker.openInterest, 1)
                    
                    if volume_oi_ratio >= min_volume_ratio:
                        results.append({
                            'symbol': contract.symbol,
                            'strike': contract.strike,
                            'right': contract.right,
                            'expiry': contract.lastTradeDateOrContractMonth,
                            'volume': ticker.volume,
                            'open_interest': ticker.openInterest,
                            'volume_ratio': round(volume_oi_ratio, 2),
                            'bid': ticker.bid,
                            'ask': ticker.ask,
                            'last': ticker.last
                        })
                
                self.ib.cancelMktData(contract)
                
            logger.info(f"Found {len(results)} options with unusual volume")
            return results
            
        except Exception as e:
            logger.error(f"Error scanning unusual options: {e}")
            return []
    
    async def scan_momentum_stocks(self, min_change_pct: float = 3.0) -> List[Dict[str, Any]]:
        """
        Scan for stocks with strong momentum.
        
        Args:
            min_change_pct: Minimum % change to include
            
        Returns:
            List of momentum stocks
        """
        try:
            await self.ensure_connected()
            
            # Top gainers scan
            sub = ScannerSubscription(
                instrument='STK',
                locationCode='STK.US.MAJOR',
                scanCode='TOP_PERC_GAIN'
            )
            
            scan_data = await self.ib.reqScannerDataAsync(sub)
            
            results = []
            for item in scan_data[:20]:
                contract = item.contractDetails.contract
                
                ticker = self.ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(0.5)
                
                if ticker.last and ticker.close:
                    change_pct = ((ticker.last - ticker.close) / ticker.close) * 100
                    
                    if abs(change_pct) >= min_change_pct:
                        results.append({
                            'symbol': contract.symbol,
                            'price': ticker.last,
                            'change_pct': round(change_pct, 2),
                            'volume': ticker.volume,
                            'bid': ticker.bid,
                            'ask': ticker.ask,
                            'high': ticker.high,
                            'low': ticker.low
                        })
                
                self.ib.cancelMktData(contract)
                
            logger.info(f"Found {len(results)} momentum stocks")
            return results
            
        except Exception as e:
            logger.error(f"Error scanning momentum stocks: {e}")
            return []
    
    async def scan_options_opportunities(
        self,
        symbols: List[str],
        min_premium: float = 0.50,
        max_days_to_expiry: int = 45
    ) -> List[Dict[str, Any]]:
        """
        Scan specific symbols for options opportunities.
        
        Args:
            symbols: List of symbols to scan
            min_premium: Minimum option premium
            max_days_to_expiry: Maximum days to expiration
            
        Returns:
            List of options opportunities
        """
        try:
            await self.ensure_connected()
            
            opportunities = []
            max_date = datetime.now() + timedelta(days=max_days_to_expiry)
            
            for symbol in symbols:
                logger.info(f"Scanning options for {symbol}")
                
                # Get stock price
                stock = Stock(symbol, 'SMART', 'USD')
                stock_ticker = self.ib.reqMktData(stock, snapshot=True)
                await asyncio.sleep(1)
                
                stock_price = stock_ticker.last if stock_ticker.last > 0 else stock_ticker.close
                
                if not stock_price:
                    logger.warning(f"No price for {symbol}, skipping")
                    self.ib.cancelMktData(stock)
                    continue
                
                # Get options chain
                chains = await self.ib.reqSecDefOptParamsAsync(
                    stock.symbol,
                    '',
                    stock.secType,
                    stock.conId
                )
                
                if not chains:
                    logger.warning(f"No options chain for {symbol}")
                    self.ib.cancelMktData(stock)
                    continue
                
                chain = chains[0]
                
                # Look for ATM options
                atm_strike = min(chain.strikes, key=lambda x: abs(x - stock_price))
                near_strikes = [s for s in chain.strikes if abs(s - atm_strike) <= 5]
                
                # Check next monthly expiry
                expirations = sorted([e for e in chain.expirations if datetime.strptime(e, '%Y%m%d') <= max_date])
                
                if expirations:
                    next_expiry = expirations[0]
                    
                    for strike in near_strikes[:5]:  # Check up to 5 strikes
                        for right in ['C', 'P']:
                            option = Option(symbol, next_expiry, strike, right, 'SMART')
                            
                            # Qualify the contract
                            qualified = await self.ib.qualifyContractsAsync(option)
                            if qualified:
                                option = qualified[0]
                                
                                opt_ticker = self.ib.reqMktData(option, snapshot=True)
                                await asyncio.sleep(0.5)
                                
                                if opt_ticker.bid and opt_ticker.bid >= min_premium:
                                    # Calculate metrics
                                    moneyness = 'ITM' if (right == 'C' and strike < stock_price) or \
                                                        (right == 'P' and strike > stock_price) else 'OTM'
                                    
                                    opportunities.append({
                                        'symbol': symbol,
                                        'stock_price': round(stock_price, 2),
                                        'strike': strike,
                                        'right': right,
                                        'expiry': next_expiry,
                                        'bid': opt_ticker.bid,
                                        'ask': opt_ticker.ask,
                                        'mid': round((opt_ticker.bid + opt_ticker.ask) / 2, 2),
                                        'volume': opt_ticker.volume,
                                        'open_interest': opt_ticker.openInterest,
                                        'moneyness': moneyness,
                                        'iv': opt_ticker.impliedVolatility if hasattr(opt_ticker, 'impliedVolatility') else None
                                    })
                                
                                self.ib.cancelMktData(option)
                
                self.ib.cancelMktData(stock)
                
            logger.info(f"Found {len(opportunities)} options opportunities")
            return opportunities
            
        except Exception as e:
            logger.error(f"Error scanning options opportunities: {e}")
            return []
    
    async def get_market_overview(self) -> Dict[str, Any]:
        """
        Get overall market overview including indices and VIX.
        
        Returns:
            Market overview data
        """
        try:
            await self.ensure_connected()
            
            indices = {
                'SPY': Stock('SPY', 'SMART', 'USD'),
                'QQQ': Stock('QQQ', 'SMART', 'USD'),
                'IWM': Stock('IWM', 'SMART', 'USD'),
                'VIX': Stock('VIX', 'CBOE', 'USD')
            }
            
            overview = {}
            
            for name, contract in indices.items():
                ticker = self.ib.reqMktData(contract, snapshot=True)
                await asyncio.sleep(1)
                
                if ticker.last or ticker.close:
                    price = ticker.last if ticker.last > 0 else ticker.close
                    prev_close = ticker.close if ticker.close else price
                    change = price - prev_close
                    change_pct = (change / prev_close * 100) if prev_close else 0
                    
                    overview[name] = {
                        'price': round(price, 2),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 2),
                        'volume': ticker.volume,
                        'bid': ticker.bid,
                        'ask': ticker.ask,
                        'high': ticker.high,
                        'low': ticker.low
                    }
                
                self.ib.cancelMktData(contract)
            
            # Add market status
            overview['market_status'] = 'OPEN' if self._is_market_open() else 'CLOSED'
            overview['timestamp'] = datetime.now().isoformat()
            
            return overview
            
        except Exception as e:
            logger.error(f"Error getting market overview: {e}")
            return {}
    
    def _is_market_open(self) -> bool:
        """Check if US market is open."""
        now = datetime.now()
        weekday = now.weekday()
        
        # Market closed on weekends
        if weekday >= 5:
            return False
        
        # Simple check for regular hours (9:30 AM - 4:00 PM ET)
        # This should be enhanced with proper timezone handling
        hour = now.hour
        minute = now.minute
        
        if hour < 9 or hour >= 16:
            return False
        if hour == 9 and minute < 30:
            return False
            
        return True