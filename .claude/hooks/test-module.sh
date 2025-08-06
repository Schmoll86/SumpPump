#!/bin/bash
# Test hook for module development
# Automatically tests modules after changes

MODULE=$1
if [ -z "$MODULE" ]; then
    echo "Usage: ./test-module.sh <module_name>"
    exit 1
fi

echo "🧪 Testing module: $MODULE"

# Activate virtual environment
source venv/bin/activate

# Run module-specific tests
case $MODULE in
    "tws")
        echo "Testing TWS connection..."
        python -c "
import asyncio
from src.modules.tws.connection import tws_connection
async def test():
    try:
        await tws_connection.connect()
        print('✅ TWS connection successful')
        await tws_connection.disconnect()
    except Exception as e:
        print(f'❌ Connection failed: {e}')
asyncio.run(test())
        "
        ;;
    "data")
        echo "Testing data module..."
        python -c "
import asyncio
from src.modules.data import options_data
async def test():
    await options_data.initialize()
    print('✅ Data module initialized')
asyncio.run(test())
        "
        ;;
    "strategies")
        echo "Testing strategies module..."
        pytest tests/unit/test_strategies.py -v
        ;;
    "risk")
        echo "Testing risk module..."
        pytest tests/unit/test_risk.py -v
        ;;
    *)
        echo "Unknown module: $MODULE"
        exit 1
        ;;
esac