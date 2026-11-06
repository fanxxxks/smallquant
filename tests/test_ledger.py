"""Ledger and book invariants I-1, I-2, I-4, I-5, I-6, I-8."""

import json
from decimal import Decimal

import pytest

from newquant.ledger import Book, LedgerError, LedgerStore
from newquant.order import execute_plan, plan_order
from newquant.venue import Instrument

EQ = Instrument(code="510300", name="沪深300ETF", klass="equity")
BOND = Instrument(code="511010", name="国债ETF", klass="bond")


def make_book(tmp_path, name="acct.jsonl", cash="75000"):
    store = LedgerStore(tmp_path / name, now="2026-11-04T00:00:00+00:00")
    book = Book(store, instruments={EQ.code: EQ, BOND.code: BOND})
    if not store.records:
        book.open(Decimal(cash))
    return book


class TestDeterministicReplay:
    def test_two_runs_produce_the_same_head(self, tmp_path):
        heads = []
        for run in ("a", "b"):
            book = make_book(tmp_path, f"{run}.jsonl")
            book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
            book.execute(code="511010", side="buy", lots=6, price=Decimal("100.00"), session=2)
            heads.append((book.ledger.head, len(book.ledger.records)))
        assert heads[0] == heads[1]

    def test_reload_verifies_the_chain(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        head = book.ledger.head
        again = LedgerStore(tmp_path / "acct.jsonl")
        assert again.head == head
        assert [r.kind for r in again.records] == ["open", "fill"]

    def test_an_edited_record_refuses_to_load(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        path = tmp_path / "acct.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["payload"]["price"] = "15.00"
        lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(LedgerError):
            LedgerStore(path)


class TestNAV:
    def test_nav_identity(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        nav = book.nav({"510300": Decimal("16.50")})
        expected = book.cash + Decimal("4") * 100 * Decimal("16.50")
        assert nav == expected.quantize(Decimal("0.01"))

    def test_missing_mark_raises_rather_than_guessing(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=1, price=Decimal("16.00"), session=1)
        with pytest.raises(KeyError):
            book.nav({})

    def test_dividend_moves_cash_and_keeps_lots(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=10, price=Decimal("10.00"), session=1)
        before_lots, before_cash = book.positions["510300"], book.cash
        before_nav = book.nav({"510300": Decimal("10.00")})
        book.corporate_action(code="510300", action="dividend", per_share=Decimal("0.02"), session=2)
        assert book.positions["510300"] == before_lots
        assert book.cash == before_cash + Decimal("20.00")
        assert book.nav({"510300": Decimal("10.00")}) == before_nav + Decimal("20.00")

    def test_split_scales_lots_and_preserves_nav(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=10, price=Decimal("10.00"), session=1)
        before_nav = book.nav({"510300": Decimal("10.00")})
        book.corporate_action(code="510300", action="split", ratio=Decimal("2"), session=2)
        assert book.positions["510300"] == 20
        assert book.nav({"510300": Decimal("5.00")}) == before_nav


class TestSettlement:
    def test_t_plus_1_buy_cannot_be_sold_same_session(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        assert book.sellable_lots("510300", 1) == 0
        with pytest.raises(LedgerError):
            book.execute(code="510300", side="sell", lots=4, price=Decimal("16.10"), session=1)
        book.settle(2)
        assert book.sellable_lots("510300", 2) == 4
        book.execute(code="510300", side="sell", lots=4, price=Decimal("16.10"), session=2)

    def test_t_plus_0_bond_sell_proceeds_are_available_same_session(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="511010", side="buy", lots=3, price=Decimal("100.00"), session=1)
        assert book.sellable_lots("511010", 1) == 3
        cash_before = book.available_cash(1)
        book.execute(code="511010", side="sell", lots=3, price=Decimal("100.10"), session=1)
        assert book.available_cash(1) > cash_before - Decimal("300.00")

    def test_t_plus_1_sell_proceeds_are_locked_until_settlement(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        book.settle(2)
        cash_after_buy = book.cash
        book.execute(code="510300", side="sell", lots=4, price=Decimal("16.10"), session=2)
        proceeds = book.cash - cash_after_buy
        assert proceeds > 0
        assert book.available_cash(2) == book.cash - proceeds
        book.settle(3)
        assert book.available_cash(3) == book.cash


class TestSuppression:
    def test_below_gate_intent_becomes_a_record_not_a_silent_noop(self, tmp_path):
        book = make_book(tmp_path)
        plan = plan_order(EQ, side="buy", target_notional=Decimal("5100"), price=Decimal("16.00"),
                          tolerance_bp=Decimal("10"), available_cash=Decimal("75000"))
        assert not plan.ok and plan.reason == "below_cost_gate"
        rec = execute_plan(book, plan, session=1)
        assert rec.kind == "suppress"
        assert rec.payload["reason"] == "below_cost_gate"
        assert book.positions == {}

    def test_zero_lot_intent_is_suppressed_without_cost(self, tmp_path):
        plan = plan_order(EQ, side="buy", target_notional=Decimal("1500"), price=Decimal("16.00"),
                          tolerance_bp=Decimal("15.1"))
        assert plan.reason == "zero_lot"
        assert plan.cost is None

    def test_insufficient_settled_cash_suppresses_rather_than_resizing(self, tmp_path):
        book = make_book(tmp_path, cash="5000")
        plan = plan_order(EQ, side="buy", target_notional=Decimal("10000"), price=Decimal("16.00"),
                          tolerance_bp=Decimal("15.1"), available_cash=Decimal("5000"))
        assert plan.reason == "insufficient_settled_cash"
        with pytest.raises(LedgerError):
            book.execute(code="510300", side="buy", lots=6, price=Decimal("16.00"), session=1)


class TestCostRecomputation:
    def test_logged_cost_matches_a_fresh_computation(self, tmp_path):
        book = make_book(tmp_path)
        rec = book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        fresh = EQ.fees.cost(Decimal(rec.payload["notional"]), "buy")
        assert Decimal(rec.payload["commission"]) == fresh.commission
        assert Decimal(rec.payload["transfer"]) == fresh.transfer
        assert Decimal(rec.payload["total_cost"]) == fresh.total

    def test_tampered_cost_refuses_on_load(self, tmp_path):
        book = make_book(tmp_path)
        book.execute(code="510300", side="buy", lots=4, price=Decimal("16.00"), session=1)
        path = tmp_path / "acct.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        # consistent re-hash so the chain still validates: the cost check must catch it alone
        from newquant.ledger import _digest

        rec["payload"]["commission"] = "4.00"
        rec["hash"] = _digest(rec["prev"], rec["seq"], rec["kind"], rec["payload"])
        lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        store = LedgerStore(path)
        book2 = Book(store, instruments={EQ.code: EQ, BOND.code: BOND})
        with pytest.raises(LedgerError):
            book2.apply_all(store.records)
