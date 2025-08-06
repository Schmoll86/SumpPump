#!/bin/bash

# SumpPump Setup Script
# Helps configure the environment and verify TWS settings

echo "╔══════════════════════════════════════════════╗"
echo "║     SumpPump - IBKR Trading Assistant       ║"
echo "║            Setup & Configuration             ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo "🔍 Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION found"
else
    echo -e "${RED}✗${NC} Python 3 not found. Please install Python 3.10+"
    exit 1
fi

# Create virtual environment
echo ""
echo "🔧 Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${YELLOW}!${NC} Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo ""
echo "📦 Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo ""
echo "📚 Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo ""
echo "📁 Creating project directories..."
mkdir -p cache logs config

# Copy environment file
echo ""
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓${NC} Created .env file from template"
    echo -e "${YELLOW}!${NC} Please edit .env with your IBKR account details"
else
    echo -e "${YELLOW}!${NC} .env file already exists"
fi

# TWS Configuration Reminder
echo ""
echo "═══════════════════════════════════════════════"
echo "📊 TWS Configuration Checklist"
echo "═══════════════════════════════════════════════"
echo ""
echo "Please ensure TWS is configured with:"
echo "  ✓ API enabled (File → Global Configuration → API → Settings)"
echo "  ✓ Socket port: 7497"
echo "  ✓ Trusted IP: 127.0.0.1"
echo "  ✓ 'Download open orders on connection' checked"
echo "  ✓ Memory allocation: 4096 MB minimum"
echo ""
echo "Market Data Requirements:"
echo "  ✓ US Options Level 1 subscription (minimum)"
echo "  ✓ Real-time data enabled (not delayed)"
echo ""

# MCP Registration
echo "═══════════════════════════════════════════════"
echo "🔌 Claude Desktop MCP Registration"
echo "═══════════════════════════════════════════════"
echo ""
echo "To register with Claude Desktop, run:"
echo "  python src/mcp/server.py"
echo ""
echo -e "${GREEN}✓${NC} Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your IBKR credentials"
echo "  2. Start TWS and verify API settings"
echo "  3. Run: python src/mcp/server.py"
echo "  4. Connect from Claude Desktop"

# Make script executable
chmod +x setup.sh
