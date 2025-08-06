# SumpPump Makefile

.PHONY: help install setup test run clean format lint type-check docs

# Default target
help:
	@echo "SumpPump - IBKR Trading Assistant"
	@echo ""
	@echo "Available targets:"
	@echo "  make install    - Install dependencies"
	@echo "  make setup      - Run setup script"
	@echo "  make test       - Run tests"
	@echo "  make run        - Start MCP server"
	@echo "  make clean      - Clean cache and logs"
	@echo "  make format     - Format code with black"
	@echo "  make lint       - Run linter"
	@echo "  make type-check - Run type checking"

# Install dependencies
install:
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt

# Run setup
setup:
	chmod +x setup.sh
	./setup.sh

# Run tests
test:
	./venv/bin/pytest tests/

# Start MCP server
run:
	./venv/bin/python src/mcp/server.py

# Clean cache and logs
clean:
	rm -rf cache/*.db
	rm -rf logs/*.log
	rm -rf __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Format code
format:
	./venv/bin/black src/ tests/

# Lint code
lint:
	./venv/bin/ruff check src/ tests/

# Type checking
type-check:
	./venv/bin/mypy src/

# Create documentation
docs:
	@echo "Documentation is in docs/ and CLAUDE.md"
	@echo "Run 'make run' to start the MCP server"

# Development setup
dev: install setup
	@echo "Development environment ready!"
	@echo "Edit .env file with your IBKR credentials"
	@echo "Start TWS and run 'make run' to begin"
