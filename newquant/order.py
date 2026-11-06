"""Order arithmetic: lot rounding, the post-rounding cost gate, and suppression semantics.

The rule that the reviews settled (ledger decision `cross-fixes-v4`): the gate is evaluated
on the FINAL post-rounding executable notional and on TOTAL one-way cost, and a failing
order is SUPPRESSED rather than resized. There is no path in this module that returns a
smaller order than the caller asked for — except the sell-side cap at the holding, which is
a constraint of the ledger, not a policy choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .venue import Cost, Instrument, Side, gate_ok, min_notional, q, round_to_lots

Reason = Literal[
    "ok",
    "zero_lot",
    "below_cost_gate",
    "insufficient_settled_cash",
    "capped_to_holding",
    "no_admissible_size",
]


@dataclass(frozen=True)
class Plan:
    code: str
    side: Side
    lots: int
    price: Decimal
    notional: Decimal
    cost: Cost | None
    ok: bool
    reason: Reason
    tolerance_bp: Decimal
    detail: str = ""

    @property
    def bp(self) -> Decimal:
        return self.cost.bp if self.cost is not None else Decimal(0)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "side": self.side,
            "lots": self.lots,
            "price": str(self.price),
            "notional": str(self.notional),
            "bp": str(self.bp.quantize(Decimal("0.0001"))),
            "ok": self.ok,
            "reason": self.reason,
            "tolerance_bp": str(self.tolerance_bp),
            "detail": self.detail,
        }


def plan_order(
    inst: Instrument,
    *,
    side: Side,
    target_notional: Decimal,
    price: Decimal,
    tolerance_bp: Decimal | float | int,
    available_cash: Decimal | None = None,
    sellable_lots: int | None = None,
    session: int = 0,
) -> Plan:
    """Decide whether an intent becomes an order. Deterministic: same inputs, same Plan."""
    tol = Decimal(tolerance_bp)
    price = Decimal(price)
    lots = round_to_lots(Decimal(target_notional), price, inst.lot)

    if side == "sell" and sellable_lots is not None:
        lots = min(lots, int(sellable_lots))

    if lots <= 0:
        return Plan(inst.code, side, 0, price, Decimal("0.00"), None, False, "zero_lot", tol,
                    "intent floored to zero board lots")

    notional = q(price * lots * inst.lot)
    passes, bp = gate_ok(notional, side, tol, inst.fees)
    cost = inst.fees.cost(notional, side)
    bound = min_notional(tol, side, inst.fees)
    detail = f"bp={bp.quantize(Decimal('0.0001'))}"
    if bound is None:
        return Plan(inst.code, side, lots, price, notional, cost, False, "no_admissible_size", tol,
                    f"tolerance {tol}bp below the all-variable rate for this schedule")
    if not passes:
        detail = f"bp={bp.quantize(Decimal('0.0001'))} > tol={tol}; unrounded min {bound}"
        return Plan(inst.code, side, lots, price, notional, cost, False, "below_cost_gate", tol, detail)

    if side == "buy" and available_cash is not None and notional + cost.cash_cost > Decimal(available_cash):
        detail = f"need {notional + cost.cash_cost}, settled {Decimal(available_cash)}"
        return Plan(inst.code, side, lots, price, notional, cost, False, "insufficient_settled_cash", tol, detail)

    return Plan(inst.code, side, lots, price, notional, cost, True, "ok", tol, detail)


def execute_plan(book, plan: Plan, *, session: int):
    """Route a Plan into the ledger: a fill when ok, a suppress record otherwise (I-8)."""
    if plan.ok:
        return book.execute(code=plan.code, side=plan.side, lots=plan.lots, price=plan.price, session=session)
    return book.suppress(
        code=plan.code,
        side=plan.side,
        intended_lots=plan.lots,
        reason=plan.reason,
        session=session,
        notional=str(plan.notional),
        bp=str(plan.bp.quantize(Decimal("0.0001"))),
        tolerance_bp=str(plan.tolerance_bp),
        detail=plan.detail,
    )
