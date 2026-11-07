"""Cut window panes from sheet glass.

Read a YAML job of stock and rough opening sizes, subtract the adjustment
from each pane, and write a PDF cutting plan. Panes from one window stay on
the same sheet when they fit. The plan buys as few extra sheets as possible.
"""

__version__ = "0.1.0"
