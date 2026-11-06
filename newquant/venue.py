"""Venue facts: fee schedule, instrument table, one-way cost, and the cost gate.

Money is Decimal quantised to the cent; lots are ints. Nothing here reads a file or a
state object, so every number this module returns is reproducible from its arguments.

Rate sources (P1 `data/fee_matrix.json`, corrected for ETFs):
  commission 0.00025, floored at 5.00 CNY per non-zero order
  stamp duty 0      -- ETF only; the 0.0005 rate is a *stock* sell rate and must never be
                       applied to an ETF
  transfer   1e-05
  slippage   0.0005 -- assumed, not measured (open item 1 in the architecture doc)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Literal

CENT = Decimal("0.01")
BPS = Decimal(10000)
Side = Literal["buy", "sell"]


def q(value: Decimal | str | int | float) -> Decimal:
    """Quantise a money amount to the cent, half-up (broker convention)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeSchedule:
    """Per-order charge schedule. `slippage_rate` is an execution effect, not cash."""

    commission_rate: Decimal = Decimal("0.00025")
    commission_min: Decimal = Decimal("5.00")
    stamp_rate: Decimal = Decimal("0")  # ETF: zero
    transfer_rate: Decimal = Decimal("0.00001")
    slippage_rate: Decimal = Decimal("0.0005")
    name: str = "etf_std"

    def cost(self, notional: Decimal, side: Side) -> "Cost":
        """Full cost of one order of `notional` CNY, charged on the post-rounding size."""
        if notional <= 0:
            raise ValueError(f"notional must be positive, got {notional}")
        commission = q(max(self.commission_min, notional * self.commission_rate))
        stamp = q(notional * self.stamp_rate) if side == "sell" else q(0)
        transfer = q(notional * self.transfer_rate)
        slippage = q(notional * self.slippage_rate)
        return Cost(
            notional=q(notional),
            commission=commission,
            stamp=stamp,
            transfer=transfer,
            slippage=slippage,
        )


@dataclass(frozen=True)
class Cost:
    notional: Decimal
    commission: Decimal
    stamp: Decimal
    transfer: Decimal
    slippage: Decimal

    @property
    def cash_cost(self) -> Decimal:
        """What actually leaves or reduces the account balance."""
        return self.commission + self.stamp + self.transfer

    @property
    def total(self) -> Decimal:
        """Cash cost plus the modelled execution effect."""
        return self.cash_cost + self.slippage

    @property
    def bp(self) -> Decimal:
        return self.total / self.notional * BPS

    @property
    def cash_bp(self) -> Decimal:
        return self.cash_cost / self.notional * BPS

    def as_dict(self) -> dict[str, str]:
        return {
            "notional": str(self.notional),
            "commission": str(self.commission),
            "stamp": str(self.stamp),
            "transfer": str(self.transfer),
            "slippage": str(self.slippage),
            "total": str(self.total),
            "bp": str(self.bp.quantize(Decimal("0.0001"))),
        }


ETF_STD = FeeSchedule()

# Settlement is per class and is *not* uniformly T+1.
SETTLE_DAYS = {"equity": 1, "overseas": 1, "bond": 0, "commodity": 0, "cash": 0}


@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    klass: str  # equity | bond | commodity | overseas | cash
    lot: int = 100
    fees: FeeSchedule = ETF_STD
    listed_from: str = ""
    listed_to: str | None = None

    @property
    def settle_days(self) -> int:
        return SETTLE_DAYS[self.klass]


def lot_notional(price: Decimal, lot: int) -> Decimal:
    return q(Decimal(price) * lot)


def round_to_lots(target_notional: Decimal, price: Decimal, lot: int) -> int:
    """Floor a desired notional to whole board lots. Never rounds up: cash is binding."""
    if price <= 0:
        raise ValueError("price must be positive")
    if target_notional <= 0:
        return 0
    return int((Decimal(target_notional) / (Decimal(price) * lot)).to_integral_value(rounding="ROUND_FLOOR"))


FLOOR_CROSSING = ETF_STD.commission_min / ETF_STD.commission_rate  # 20000 CNY


def min_notional(tolerance_bp: Decimal | float | int, side: Side, fees: FeeSchedule = ETF_STD) -> Decimal | None:
    """Smallest order whose one-way TOTAL cost fits inside `tolerance_bp`.

    The 5 CNY commission floor makes the cost curve non-linear, so there are two regimes:

        N <  floor/rate   cost = 5 + var*N              rate = 5/N + var      (falling in N)
        N >= floor/rate   cost = (commission_rate+var)*N  rate = commission_rate+var  (flat)
        var = transfer + stamp(side) + slippage

    The rate therefore has an infimum of `commission_rate + var` and never goes below it.
    So:

      * tol <  commission_rate + var -> no size passes, at any capital   -> None
      * tol >= commission_rate + var -> N_min = 5 / (tol - var)

    The result is cent-CEILED, so the returned bound passes its own gate; a cent-floored
    value (10204.08 at 10 bp) is a hair under the bound. Because the engine rounds each cost
    component to the cent, the analytic bound can sit a few cents low (at 50 bp: 1,113.59
    computes to 50.018 bp), so it is then walked up a cent at a time until `gate_ok` — the
    same test the account uses — agrees. The bound is therefore never optimistic, and it is
    still only a bound: whole-lot rounding applies on top, and the binding test is `gate_ok`
    on the FINAL notional. 5,000 desired at a 16.00 price floors to 4,800 and fails 15.1 bp.
    """
    tol = Decimal(tolerance_bp) / BPS
    var = fees.transfer_rate + fees.slippage_rate + (fees.stamp_rate if side == "sell" else Decimal(0))
    denom = tol - var
    if denom <= 0:
        return None  # even an infinite order cannot amortise the variable rates
    if denom < fees.commission_rate:
        return None  # inside the flat regime the rate is commission_rate+var > tol
    bound = (fees.commission_min / denom).quantize(CENT, rounding=ROUND_CEILING)
    for _ in range(1000):
        if gate_ok(bound, side, tolerance_bp, fees)[0]:
            return bound
        bound += CENT
    raise RuntimeError(f"no cent within 10 CNY of the analytic bound clears {tolerance_bp} bp")


def gate_ok(notional: Decimal, side: Side, tolerance_bp: Decimal | float | int, fees: FeeSchedule = ETF_STD) -> tuple[bool, Decimal]:
    """The gate, evaluated on the FINAL post-rounding notional. Returns (passes, bp)."""
    if notional <= 0:
        return False, Decimal(0)
    bp = fees.cost(notional, side).bp
    return bp <= Decimal(tolerance_bp), bp
