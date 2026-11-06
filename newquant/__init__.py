"""newquant — account-level net-CNY research line for small CN A-share ETF books.

Layer map (see docs/direction-architecture.md):
  L0 data/freeze    frozen, hashed inputs
  L1 panel/         panel estimation (ridge | mlp) -> sleeve scores
  L2 sleeve/        combiner, <= 4 fitted parameters
  L3 book/ + ledger/ order arithmetic, cost gate, append-only ledger
  L4 eval/          net curve, block bootstrap, decision rules
"""

__version__ = "0.1.0"
