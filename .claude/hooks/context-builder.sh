#!/bin/bash
# Context builder hook
# Aggregates relevant context before AI assistance

echo "📚 Building context for AI assistance..."

# Determine which module is being worked on
CURRENT_FILE=$1
MODULE=""

if [[ $CURRENT_FILE == *"tws"* ]]; then
    MODULE="tws"
elif [[ $CURRENT_FILE == *"data"* ]]; then
    MODULE="data"
elif [[ $CURRENT_FILE == *"strategies"* ]]; then
    MODULE="strategies"
elif [[ $CURRENT_FILE == *"risk"* ]]; then
    MODULE="risk"
elif [[ $CURRENT_FILE == *"execution"* ]]; then
    MODULE="execution"
elif [[ $CURRENT_FILE == *"mcp"* ]]; then
    MODULE="mcp"
fi

# Build context based on module
CONTEXT_FILES="CLAUDE.md"

case $MODULE in
    "tws")
        CONTEXT_FILES="$CONTEXT_FILES src/config.py"
        echo "Context: TWS Connection & Market Data"
        ;;
    "data")
        CONTEXT_FILES="$CONTEXT_FILES src/models.py"
        echo "Context: Options Chain & Data Management"
        ;;
    "strategies")
        CONTEXT_FILES="$CONTEXT_FILES src/models.py"
        echo "Context: Options Strategy Calculations"
        ;;
    "risk")
        CONTEXT_FILES="$CONTEXT_FILES src/config.py"
        echo "Context: Risk Management & Validation"
        ;;
    "execution")
        CONTEXT_FILES="$CONTEXT_FILES src/models.py"
        echo "Context: Order Execution & Confirmation"
        ;;
    "mcp")
        CONTEXT_FILES="$CONTEXT_FILES"
        echo "Context: MCP Server & Tool Integration"
        ;;
    *)
        CONTEXT_FILES="$CONTEXT_FILES docs/ai-context/handoff.md"
        echo "Context: General Project"
        ;;
esac

echo "📎 Relevant files: $CONTEXT_FILES"
echo ""
echo "💡 Tips for this module:"

case $MODULE in
    "tws")
        echo "- Use ib_async (NOT ib_insync)"
        echo "- Handle reconnection with exponential backoff"
        echo "- Always check connection before operations"
        ;;
    "strategies")
        echo "- All strategies need max loss/profit calculations"
        echo "- Include breakeven points"
        echo "- Use py_vollib for Greeks"
        ;;
    "risk")
        echo "- ALWAYS require confirmation for trades"
        echo "- Calculate position size based on account %"
        echo "- Validate margin requirements"
        ;;
    "execution")
        echo "- Mandatory confirmation token check"
        echo "- Prompt for stop loss after fills"
        echo "- Use combo orders for multi-leg strategies"
        ;;
esac