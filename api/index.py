"""
Vercel serverless function wrapper for Flask app
"""
import sys
import os

# Add parent directory to path to import the Flask app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the Flask app
from usdc_transfers_api import app

# Export the app for Vercel
# Vercel will automatically detect and use the Flask app
__all__ = ['app']
