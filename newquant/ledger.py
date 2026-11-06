"""Append-only, hash-chained account ledger and the book state it projects.

Invariants enforced here (docs/direction-architecture.md §5):
  I-1  NAV = cash + sum(lots * lot * mark), written only by `Book.nav`
  I-2  every fill's cost is recomputed from the fee schedule at load time and must match
  I-4  proceeds of a sell are unavailable to buys until settlement; a T+1 buy is unsellable
  I-5  corporate actions move cash (dividend) or lots (split) with NAV preserved
  I-6  replaying the same records yields the same chain head; an edited record refuses to load
  I-8  a suppressed order is a record, never a silent no-op
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .venue import Cost, FeeSchedule, Instrument, Side, q

GENESIS = "0" * 64


def _canonical(seq: int, kind: str, payload: dict[str, Any]) -> bytes:
    return json.dumps(
        {"seq": seq, "kind": kind, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(prev: str, seq: int, kind: str, payload: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev.encode("ascii"))
    h.update(b"|")
    h.update(_canonical(seq, kind, payload))
    return h.hexdigest()


@dataclass(frozen=True)
class Record:
    seq: int
    prev: str
    kind: str
    payload: dict[str, Any]
    at: str
    hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "prev": self.prev,
            "kind": self.kind,
            "payload": self.payload,
            "at": self.at,
            "hash": self.hash,
        }


class LedgerError(RuntimeError):
    pass


class LedgerStore:
    """One file per account. Append-only; editing any byte makes it refuse to load."""

    def __init__(self, path: str | Path, *, now: str | None = None):
        self.path = Path(path)
        self._now = now
        self.records: list[Record] = []
        if self.path.exists() and self.path.stat().st_size > 0:
            self.records = self._load()

    # ---- io -----------------------------------------------------------------
    def _load(self) -> list[Record]:
        out: list[Record] = []
        prev = GENESIS
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise LedgerError(f"{self.path}:{lineno} is not JSON: {exc}") from exc
            rec = Record(**raw)
            if rec.seq != len(out):
                raise LedgerError(f"{self.path}:{lineno} seq {rec.seq} != expected {len(out)}")
            if rec.prev != prev:
                raise LedgerError(f"{self.path}:{lineno} prev hash does not chain")
            expect = _digest(rec.prev, rec.seq, rec.kind, rec.payload)
            if expect != rec.hash:
                raise LedgerError(f"{self.path}:{lineno} hash mismatch (record edited)")
            out.append(rec)
            prev = rec.hash
        return out

    def _timestamp(self) -> str:
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc).isoformat()

    def append(self, kind: str, payload: dict[str, Any]) -> Record:
        prev = self.records[-1].hash if self.records else GENESIS
        seq = len(self.records)
        payload = _jsonable(payload)
        rec = Record(
            seq=seq,
            prev=prev,
            kind=kind,
            payload=payload,
            at=self._timestamp(),
            hash=_digest(prev, seq, kind, payload),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        self.records.append(rec)
        return rec

    @property
    def head(self) -> str:
        return self.records[-1].hash if self.records else GENESIS

    def replay_into(self, book: "Book") -> "Book":
        book.apply_all(self.records)
        return book


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class Book:
    """Account state, projected from records. The only writer of NAV."""

    def __init__(self, ledger: LedgerStore | None = None, *, instruments: dict[str, Instrument] | None = None):
        self.ledger = ledger
        self.instruments = dict(instruments or {})
        self.cash = Decimal("0.00")
        self.positions: dict[str, int] = {}  # code -> lots held
        self.unsettled_lots: dict[str, list[tuple[int, int]]] = {}  # code -> [(lots, settle_seq_session)]
        self.unsettled_cash: list[tuple[Decimal, int]] = []  # [(amount, available_session)]
        self.session = 0

    # ---- instrument registry ------------------------------------------------
    def register(self, inst: Instrument) -> None:
        self.instruments[inst.code] = inst

    def instrument(self, code: str) -> Instrument:
        if code not in self.instruments:
            raise KeyError(f"unknown instrument {code}: register it before trading")
        return self.instruments[code]

    # ---- state projection ---------------------------------------------------
    def apply_all(self, records: Iterable[Record]) -> None:
        for rec in records:
            self.apply(rec)

    def apply(self, rec: Record) -> None:
        p = rec.payload
        kind = rec.kind
        if kind == "open":
            self.cash = Decimal(p["cash"])
        elif kind == "fill":
            inst = self.instrument(p["code"])
            lots = int(p["lots"])
            lot = inst.lot
            notional = Decimal(p["notional"])
            cost = Cost(
                notional=notional,
                commission=Decimal(p["commission"]),
                stamp=Decimal(p["stamp"]),
                transfer=Decimal(p["transfer"]),
                slippage=Decimal(p["slippage"]),
            )
            recomputed = inst.fees.cost(notional, p["side"])
            if recomputed.cash_cost != cost.cash_cost or recomputed.slippage != cost.slippage:
                raise LedgerError(
                    f"seq {rec.seq}: logged cost {cost.as_dict()} != recomputed {recomputed.as_dict()} (I-2)"
                )
            if p["side"] == "buy":
                self.cash -= notional + cost.cash_cost
                self.positions[p["code"]] = self.positions.get(p["code"], 0) + lots
                settle = int(p["settle_session"])
                if settle > int(p["session"]):
                    self.unsettled_lots.setdefault(p["code"], []).append((lots, settle))
            else:
                held = self.positions.get(p["code"], 0)
                if lots > held:
                    raise LedgerError(f"seq {rec.seq}: sell {lots} > held {held}")
                self.positions[p["code"]] = held - lots
                self.cash += notional - cost.cash_cost
                settle = int(p["settle_session"])
                if settle > int(p["session"]):
                    self.unsettled_cash.append((notional - cost.cash_cost, settle))
            self.session = max(self.session, int(p["session"]))
        elif kind == "suppress":
            self.session = max(self.session, int(p["session"]))
        elif kind == "corp":
            lots = self.positions.get(p["code"], 0)
            if p["action"] == "dividend":
                self.cash += q(Decimal(p["per_share"]) * lots * self.instrument(p["code"]).lot)
            elif p["action"] == "split":
                # A unit change scales the lot count. When the ratio is not an integer the
                # truncation drops a fraction of a board lot, so the record carries the cash
                # value of that fraction (`residual_cash`) and NAV is preserved to the cent.
                # Truncating silently would make I-5 false at small positions, where one lot
                # is a large share of the holding.
                ratio = Decimal(p["ratio"])
                self.positions[p["code"]] = int(Decimal(lots) * ratio)
                residual = Decimal(p.get("residual_cash", "0"))
                if residual:
                    self.cash += q(residual)
            else:  # pragma: no cover - schema guard
                raise LedgerError(f"seq {rec.seq}: unknown corp action {p['action']}")
            self.session = max(self.session, int(p["session"]))
        elif kind in ("mark", "decision"):
            self.session = max(self.session, int(p.get("session", self.session)))
        else:  # pragma: no cover - schema guard
            raise LedgerError(f"seq {rec.seq}: unknown record kind {kind}")

    # ---- session and availability ------------------------------------------
    def settle(self, session: int) -> None:
        """Make lots and cash available at the start of `session`."""
        self.session = max(self.session, session)
        for code, queue in list(self.unsettled_lots.items()):
            keep = [(lots, s) for (lots, s) in queue if s > session]
            if keep:
                self.unsettled_lots[code] = keep
            else:
                self.unsettled_lots.pop(code, None)
        self.unsettled_cash = [(amt, s) for (amt, s) in self.unsettled_cash if s > session]

    def available_cash(self, session: int | None = None) -> Decimal:
        session = self.session if session is None else session
        locked = sum((amt for amt, s in self.unsettled_cash if s > session), Decimal("0.00"))
        return self.cash - locked

    def sellable_lots(self, code: str, session: int | None = None) -> int:
        session = self.session if session is None else session
        held = self.positions.get(code, 0)
        locked = sum(lots for lots, s in self.unsettled_lots.get(code, []) if s > session)
        return held - locked

    # ---- writes -------------------------------------------------------------
    def _require_ledger(self) -> LedgerStore:
        if self.ledger is None:
            raise RuntimeError("book has no ledger attached; state would be unrecorded")
        return self.ledger

    def open(self, cash: Decimal, *, note: str = "") -> None:
        self._require_ledger().append("open", {"cash": q(cash), "note": note})
        self.cash = q(cash)

    def execute(self, *, code: str, side: Side, lots: int, price: Decimal, session: int) -> Record:
        """Record one fill. Raises rather than silently adjusting: the plan is upstream."""
        store = self._require_ledger()
        inst = self.instrument(code)
        if lots <= 0:
            raise ValueError("execute needs lots > 0; a zero-lot intent is a suppression")
        notional = q(Decimal(price) * lots * inst.lot)
        cost = inst.fees.cost(notional, side)
        if side == "buy":
            if notional + cost.cash_cost > self.available_cash(session):
                raise LedgerError(f"insufficient settled cash: need {notional + cost.cash_cost}")
        elif lots > self.sellable_lots(code, session):
            raise LedgerError(f"unsellable lots: {lots} > {self.sellable_lots(code, session)} (I-4)")
        payload = {
            "code": code,
            "side": side,
            "lots": lots,
            "lot": inst.lot,
            "price": q(price),
            "session": session,
            "settle_session": session + inst.settle_days,
            "notional": notional,
            "commission": cost.commission,
            "stamp": cost.stamp,
            "transfer": cost.transfer,
            "slippage": cost.slippage,
            "total_cost": cost.total,
            "cost_bp": cost.bp.quantize(Decimal("0.0001")),
        }
        rec = store.append("fill", payload)
        self.apply(rec)
        return rec

    def suppress(self, *, code: str, side: Side, intended_lots: int, reason: str, session: int, **extra: Any) -> Record:
        store = self._require_ledger()
        payload = {
            "code": code,
            "side": side,
            "intended_lots": int(intended_lots),
            "reason": reason,
            "session": session,
            **extra,
        }
        rec = store.append("suppress", payload)
        self.apply(rec)
        return rec

    def corporate_action(self, *, code: str, action: str, session: int, per_share: Decimal | None = None,
                         ratio: Decimal | None = None, residual_cash: Decimal | None = None) -> Record:
        store = self._require_ledger()
        payload: dict[str, Any] = {"code": code, "action": action, "session": session}
        if action == "dividend":
            if per_share is None:
                raise ValueError("dividend needs per_share")
            payload["per_share"] = q(per_share)
        elif action == "split":
            if ratio is None:
                raise ValueError("split needs ratio")
            payload["ratio"] = Decimal(ratio)
            if residual_cash is not None:
                payload["residual_cash"] = q(residual_cash)
        rec = store.append("corp", payload)
        self.apply(rec)
        return rec

    # ---- valuation ----------------------------------------------------------
    def nav(self, marks: dict[str, Decimal]) -> Decimal:
        """I-1: the only place NAV is written."""
        total = self.cash
        for code, lots in self.positions.items():
            if lots == 0:
                continue
            inst = self.instrument(code)
            if code not in marks:
                raise KeyError(f"no mark for held instrument {code}")
            total += q(Decimal(marks[code]) * lots * inst.lot)
        return q(total)

    def replay_hashes(self) -> list[str]:
        return [r.hash for r in (self.ledger.records if self.ledger else [])]
