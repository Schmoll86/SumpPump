# TWS Connection Module Context

## Purpose
Manages all interactions with Interactive Brokers TWS API using ib_async.

## Key Components
- **TWSConnection**: Main connection manager with reconnection logic
- **Market Data**: Real-time subscriptions for options and stocks
- **Order Management**: Combo order creation and placement

## Critical Requirements
1. **Use ib_async** (NOT ib_insync - it's deprecated)
2. **Port 7497** for live trading (7496 for paper)
3. **Exponential backoff** for reconnection attempts
4. **Resource management** - Cancel subscriptions when done

## Common Patterns

### Connection Management
```python
async with tws_connection.session() as tws:
    # Operations here
    data = await tws.get_options_chain("AAPL")
```

### Error Handling
```python
try:
    await tws_connection.ensure_connected()
except TWSConnectionError as e:
    logger.error(f"Connection failed: {e}")
```

## API Limits
- Max 100 concurrent market data lines
- Rate limit: 50 messages/second
- Options chain requests: 1 per second

## Testing
```bash
python test_connection.py
```

## Known Issues
- Greeks may be None for far OTM options
- Market data delayed 15 min without subscription
- Connection may drop during high volume