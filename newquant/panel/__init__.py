"""L1: panel estimation.

`newquant.panel` is the only place a *learned* object exists. It reads the frozen L0
panel through a read-only connection, emits cross-sectional scores, and hands the
aggregation to `aggregate.py` so that the stock→sleeve step is one reviewable file
rather than something buried in a training loop.

Nothing here may write to the panel, and nothing here may read a column dated after
the signal date `t` (see `features.SIGNAL_LAG`).
"""
