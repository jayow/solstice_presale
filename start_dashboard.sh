#!/bin/bash

echo "=========================================="
echo "USDC Transfers Dashboard"
echo "=========================================="
echo ""
echo "Installing dependencies..."
pip3 install -q -r requirements.txt

echo ""
echo "Starting server..."
echo "Open http://localhost:5000 in your browser"
echo ""
echo "Press Ctrl+C to stop"
echo "=========================================="
echo ""

python3 usdc_transfers_api.py

