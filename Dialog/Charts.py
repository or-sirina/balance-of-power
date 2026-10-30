"""
Backwards-compatible re-export of the chart widgets.

The chart implementations live in the top-level :mod:`Charts` module.  This
module is kept so that existing imports (``from Dialog.Charts import *``) keep
working, and so that any code that still asks for the old QtChart names gets the
substitute widgets instead of an ImportError.

The previous implementation imported ``PyQt5.QtChart``, which is not part of a
standard PyQt5 installation and is ABI-incompatible with the PyQt5 wheels for
recent CPython builds; that import was what prevented the game from starting.
"""

from Charts import BarChart, ChartBase, LineChart, Sparkline

# Historical alias: the old module exposed a QChart subclass named HistoryChart.
HistoryChart = ChartBase

__all__ = ["BarChart", "ChartBase", "LineChart", "Sparkline", "HistoryChart"]
