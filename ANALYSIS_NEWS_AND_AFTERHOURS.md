# News & After-Hours Trading Analysis

## Current News System Capabilities

### What's Working Now

The system uses IBKR's `reqHistoricalNews` API to fetch news:

```python
# Current implementation (line 744 in server.py)
historical_news = await tws_connection.ib.reqHistoricalNewsAsync(
    conId=contract.conId,
    providerCodes=provider,  # e.g., 'BRFG', 'BRFUPDN', 'DJNL'
    startDateTime=start_str,  # Last 7 days by default
    endDateTime=end_str,
    totalResults=num_articles
)
```

### Limitations

1. **Time Range**: Currently hardcoded to last 7 days
2. **No Persistence**: News is fetched fresh each time, not stored
3. **Limited Providers**: Only uses configured news providers
4. **No Real-Time Updates**: Uses historical API, not streaming

### To Get LLY News for Last 2 Days

Currently you can:
```python
# Use the existing tool
result = await trade_get_news(
    symbol="LLY",
    max_items=50  # Get more articles
)
```

But it will fetch 7 days, not 2 days specifically.

## After-Hours Trading Capabilities

### What's Partially Implemented

The system has **some** after-hours support:

1. **Conditional Orders** support `outside_rth` parameter:
```python
await trade_create_conditional_order(
    symbol="LLY",
    outside_rth=True,  # Allow trigger outside regular hours
    ...
)
```

2. **Stop Orders** can trigger after-hours:
```python
# In conditional orders (line 762)
action_order.conditionsIgnoreRth = True
```

### What's Missing

Regular orders (`trade_execute`, `trade_close_position`) **DON'T** have after-hours support:
- No `outsideRth` parameter on regular orders
- No time-in-force (TIF) options like "GTC" or "EXT"
- No extended hours validation

## Recommended Enhancements

### 1. Enhanced News Tool

```python
@mcp.tool(name="trade_get_news_detailed")
async def get_news_detailed(
    symbol: str,
    days_back: int = 2,  # Configurable time range
    include_after_hours: bool = True,
    providers: List[str] = None,
    cache_results: bool = True
) -> Dict[str, Any]:
    """
    Enhanced news with configurable time range and caching.
    """
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    # Check cache first
    if cache_results:
        cached = news_cache.get(symbol, days_back)
        if cached:
            return cached
    
    # Fetch from multiple providers
    all_news = []
    for provider in providers or ['BRFG', 'BRFUPDN', 'DJNL']:
        news = await fetch_provider_news(...)
        all_news.extend(news)
    
    # Filter for after-hours if needed
    if include_after_hours:
        all_news = filter_trading_hours(all_news)
    
    # Cache results
    if cache_results:
        news_cache.store(symbol, all_news, days_back)
    
    return {
        'symbol': symbol,
        'period': f'{days_back} days',
        'articles': all_news,
        'regular_hours': count_regular_hours(all_news),
        'after_hours': count_after_hours(all_news)
    }
```

### 2. After-Hours Order Support

```python
@mcp.tool(name="trade_execute_extended")
async def execute_extended(
    strategy: Dict[str, Any],
    outside_rth: bool = False,
    time_in_force: str = "DAY",  # DAY, GTC, IOC, GTD, EXT
    good_till_date: Optional[str] = None,
    confirm_token: str = None
) -> Dict[str, Any]:
    """
    Execute orders with extended hours support.
    """
    # Create order with extended parameters
    order = create_order(strategy)
    order.outsideRth = outside_rth
    order.tif = time_in_force
    
    if time_in_force == "GTD":
        order.goodTillDate = good_till_date
    
    # Validate extended hours eligibility
    if outside_rth:
        if not is_extended_hours_eligible(strategy['symbol']):
            return {'error': 'Symbol not eligible for extended hours'}
    
    # Execute with verification
    return await execute_with_verification(order, strategy)
```

### 3. News-Driven Trading Pipeline

```python
class NewsAnalysisPipeline:
    """
    Analyze news impact before trading.
    """
    
    async def analyze_news_sentiment(self, symbol: str, days: int = 2):
        # Get recent news
        news = await get_news_detailed(symbol, days_back=days)
        
        # Categorize by impact
        categories = {
            'earnings': [],
            'guidance': [],
            'fda': [],  # For pharma like LLY
            'analyst': [],
            'general': []
        }
        
        for article in news['articles']:
            category = self.categorize_article(article)
            categories[category].append(article)
        
        # Calculate sentiment score
        sentiment = self.calculate_sentiment(categories)
        
        return {
            'symbol': symbol,
            'sentiment_score': sentiment,
            'high_impact_count': len(categories['earnings'] + categories['fda']),
            'recommendation': self.get_trading_recommendation(sentiment)
        }
```

### 4. Real-Time News Monitoring

```python
class NewsMonitor:
    """
    Monitor news in real-time during trading session.
    """
    
    async def start_monitoring(self, symbols: List[str]):
        # Subscribe to real-time news
        for symbol in symbols:
            contract = Stock(symbol, 'SMART', 'USD')
            
            # Request streaming news
            news_req = tws_connection.ib.reqMktData(
                contract,
                genericTickList='292'  # News tick
            )
            
            # Set up callback
            news_req.updateEvent += self.on_news_update
    
    async def on_news_update(self, news_item):
        # Check if high impact
        if self.is_high_impact(news_item):
            # Alert user
            await self.send_alert(news_item)
            
            # Check positions
            affected_positions = self.check_affected_positions(news_item)
            
            if affected_positions:
                # Suggest protective action
                await self.suggest_protection(affected_positions)
```

## Implementation Priority

### Phase 1: Quick Fixes (Today)
1. ✅ Add `days_back` parameter to news tool
2. ✅ Add `outside_rth` to regular orders
3. ✅ Add time-in-force options

### Phase 2: Enhanced Features (This Week)
1. News caching system
2. After-hours validation
3. News categorization

### Phase 3: Advanced (Next Week)
1. Real-time news monitoring
2. News-driven alerts
3. Sentiment analysis

## Usage Examples

### Getting LLY News for 2 Days
```python
# With current system (gets 7 days)
news = await trade_get_news("LLY", max_items=20)

# With enhanced system (would get exactly 2 days)
news = await trade_get_news_detailed(
    symbol="LLY",
    days_back=2,
    include_after_hours=True
)
```

### After-Hours Trading
```python
# Current: Can't trade after-hours with regular orders

# Enhanced: Would support extended hours
result = await trade_execute_extended(
    strategy=strategy,
    outside_rth=True,
    time_in_force="EXT",  # Extended hours
    confirm_token="USER_CONFIRMED"
)
```

## Summary

**Current State:**
- Basic news fetching (7 days fixed)
- Limited after-hours support (conditional orders only)
- No news persistence or real-time monitoring

**Needed Improvements:**
1. Configurable news time ranges
2. Full after-hours order support
3. News caching and categorization
4. Real-time news monitoring

The system has the foundation but needs enhancement for professional news-driven and after-hours trading.