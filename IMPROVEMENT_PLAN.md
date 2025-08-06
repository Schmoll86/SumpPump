# SumpPump Improvement Plan

## Current Working State ✅
- MCP server connects to Claude Desktop
- TWS connection established with Client ID 5
- Options chain fetching works (during market hours)
- SMART routing and bracket orders implemented
- Safety controls in place

## Proposed Improvements (Safe Approach)

### Priority 1: Fix Remaining Critical Issues (Low Risk)

#### 1.1 Event Loop in Strategy Calculations
**Issue**: `asyncio.run()` called inside async functions causes nested event loops
**Location**: `src/modules/strategies/base.py` lines 417-426
**Safe Fix**: 
```python
# Instead of asyncio.run() inside async function
# Make the pnl_function synchronous or fully async
```
**Risk**: Low - isolated to breakeven calculations

#### 1.2 Market Data Cleanup
**Issue**: Subscriptions may leak if exceptions occur
**Location**: `src/modules/tws/connection.py` lines 270-370
**Safe Fix**: Add finally block for cleanup
**Risk**: Low - improves reliability

### Priority 2: Add Robustness (Medium Risk)

#### 2.1 Connection Recovery
**Current**: Single connection, no auto-reconnect
**Improvement**: Add connection monitoring and auto-recovery
```python
async def monitor_connection(self):
    """Background task to monitor and recover connection."""
    while True:
        if not self.ib.isConnected():
            await self.connect()
        await asyncio.sleep(30)
```
**Risk**: Medium - test thoroughly before deploying

#### 2.2 Rate Limiting
**Current**: No limits on API calls
**Improvement**: Add rate limiter to prevent overwhelming TWS
```python
from asyncio import Semaphore
rate_limit = Semaphore(10)  # Max 10 concurrent TWS calls
```
**Risk**: Low - adds safety

### Priority 3: Testing Infrastructure (No Risk)

#### 3.1 Unit Tests
Create test suite that doesn't require TWS connection:
- `tests/unit/test_models.py` - Test data models
- `tests/unit/test_strategies.py` - Test calculations
- `tests/unit/test_risk.py` - Test risk validation

#### 3.2 Integration Tests
Tests that use paper trading account:
- `tests/integration/test_connection.py`
- `tests/integration/test_orders.py`

### Priority 4: Code Quality (Low Risk)

#### 4.1 Standardize Error Handling
**Current**: Mix of exceptions and dict with 'error' key
**Improvement**: Create custom exception hierarchy
```python
class SumpPumpError(Exception): pass
class TWSConnectionError(SumpPumpError): pass
class ValidationError(SumpPumpError): pass
```

#### 4.2 Configuration Validation
**Current**: No validation of .env values
**Improvement**: Add pydantic settings validation
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    tws_host: str = "127.0.0.1"
    tws_port: int = Field(ge=1, le=65535)
    # ... with validation
```

## Implementation Strategy

### Phase 1: Fix Critical Issues (Do Now)
1. Fix event loop in strategy calculations
2. Add market data cleanup in finally blocks
3. Create basic unit tests

### Phase 2: Add Monitoring (Next Week)
1. Implement connection monitoring
2. Add rate limiting
3. Improve logging

### Phase 3: Testing Suite (Later)
1. Build comprehensive test suite
2. Add CI/CD pipeline
3. Performance benchmarks

## What NOT to Change
- ✅ MCP server startup logic (working)
- ✅ TWS connection with Client ID 5 (working)
- ✅ Options chain fetching logic (working)
- ✅ Order execution with confirmations (critical safety)
- ✅ CLAUDE.md context (important for Claude)

## Backup Strategy
Before making changes:
1. Create git branch: `git checkout -b improvements`
2. Test each change in isolation
3. Keep rollback plan ready
4. Test during market hours

## Success Metrics
- No regression in current functionality
- Improved error recovery
- Better performance under load
- Comprehensive test coverage
- Clean code with consistent patterns