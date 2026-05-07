"""Project-wide pytest configuration.

Ensures the project root is on sys.path so `from backend.physics import ...`
resolves regardless of where pytest is invoked from.

This file is auto-loaded by pytest before any test module imports.
"""
import os
import sys

# Project root = parent dir of this conftest.py
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
