#!/bin/bash

echo "=========================================="
echo "PostgreSQL Database Setup"
echo "=========================================="
echo ""

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL is not installed."
    echo ""
    echo "Install PostgreSQL:"
    echo "  macOS: brew install postgresql@14"
    echo "  Ubuntu: sudo apt-get install postgresql"
    echo "  Or download from: https://www.postgresql.org/download/"
    exit 1
fi

# Check if PostgreSQL is running
if ! pg_isready &> /dev/null; then
    echo "PostgreSQL is not running."
    echo "Starting PostgreSQL..."
    
    # Try to start PostgreSQL (macOS with Homebrew)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew services start postgresql@14 2>/dev/null || brew services start postgresql 2>/dev/null || echo "Please start PostgreSQL manually"
    fi
    
    sleep 2
    
    if ! pg_isready &> /dev/null; then
        echo "Please start PostgreSQL manually and run this script again"
        exit 1
    fi
fi

echo "✓ PostgreSQL is running"
echo ""

# Create database
echo "Creating database 'usdc_transfers'..."
createdb usdc_transfers 2>/dev/null || echo "Database may already exist (this is OK)"

echo ""
echo "✓ Database setup complete!"
echo ""
echo "Default connection settings:"
echo "  Host: localhost"
echo "  Port: 5432"
echo "  Database: usdc_transfers"
echo "  User: $(whoami)"
echo ""
echo "To use custom settings, set environment variables:"
echo "  export DB_HOST=localhost"
echo "  export DB_PORT=5432"
echo "  export DB_NAME=usdc_transfers"
echo "  export DB_USER=postgres"
echo "  export DB_PASSWORD=your_password"
echo ""

