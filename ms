#!/usr/bin/env python3
"""Mediastack CLI entry point."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cli.ms import main
sys.exit(main())
