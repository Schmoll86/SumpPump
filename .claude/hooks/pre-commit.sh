#!/bin/bash
# Pre-commit hook for SumpPump
# Ensures code quality before committing

echo "🔍 Running pre-commit checks..."

# Check if we're in the virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    source venv/bin/activate
fi

# Run type checking on modified Python files
echo "📝 Type checking..."
modified_files=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')
if [ ! -z "$modified_files" ]; then
    mypy $modified_files --ignore-missing-imports
    if [ $? -ne 0 ]; then
        echo "❌ Type checking failed"
        exit 1
    fi
fi

# Run linting
echo "🧹 Linting..."
if [ ! -z "$modified_files" ]; then
    ruff check $modified_files
    if [ $? -ne 0 ]; then
        echo "❌ Linting failed"
        exit 1
    fi
fi

# Check for hardcoded credentials
echo "🔐 Security check..."
if grep -r "TWS_ACCOUNT\|password\|secret\|api_key" --include="*.py" src/ | grep -v "os.getenv\|config\|Field"; then
    echo "❌ Found hardcoded credentials!"
    exit 1
fi

echo "✅ Pre-commit checks passed!"