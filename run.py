"""Entry point for East Lake Time Tracker."""

import sys
import os

# Add src to path so the eastlake package is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from eastlake.app import EastLakeApp

if __name__ == "__main__":
    EastLakeApp().run()
