"""The two E1 arms: `Ridge` closed form, `MLP` small panel net.

Both arms see the *same* matrix: fourteen cross-sectionally standardised features plus an
explicit coverage ratio, with missing features set to the cross-sectional median (which,
after standardisation, is exactly 0 — so zero means "at the section's median", a stated
convention rather than AlphaGPT's accidental one). Both are fitted on the same rows, with
the same target, the same dates and the same early-stopping slice. The experiment's claim
is about the difference, so anything that is not shared would be a confound.

Parameter counts are deliberately small. At 2016 the training window is twelve months of a
~2 700-name cross-section, i.e. tens of thousands of rows against 15 free parameters: the
ridge arm is not starved. The MLP is the treatment, and it is capped (two hidden layers,
≤ 64 units) because the question is whether *mild* nonlinearity helps, not whether a large
net can memorise the panel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .features import FEATURES

COVERAGE_COLUMN = "coverage"
INPUT_COLUMNS: tuple[str, ...] = (*FEATURES, COVERAGE_COLUMN)

# A 21-session forward return on A-shares has a tail a squared loss cannot survive: the
# 2016 section alone reaches +577 % on resumption bars. Clipping the *training* target at
# ±100 % is applied identically to both arms, keeps the ranking almost untouched, and stops
# one resumed name from dominating a fold's fit. The IC is measured on the unclipped label.
TRAIN_LABEL_CLIP = 1.0

LAMBDA_GRID = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
MLP_HIDDEN = (48, 24)
MLP_DROPOUT = 0.10
MLP_EPOCHS = 30
MLP_PATIENCE = 3
MLP_BATCH = 4096
MLP_LR = 1e-3
MLP_SEEDS = (0, 1)


def design_matrix(frame: pd.DataFrame) -> np.ndarray:
    """Feature block → float64 matrix, missing standardised features set to 0 (median)."""
    block = frame.loc[:, list(FEATURES)].to_numpy(dtype="float64")
    finite = np.isfinite(block)
    coverage = finite.sum(axis=1) / len(FEATURES)
    block = np.where(finite, block, 0.0)
    return np.column_stack([block, coverage])


def rank_ic(prediction: np.ndarray, target: np.ndarray) -> float:
    """Spearman correlation of one cross-section; NaN when the section is degenerate."""
    ok = np.isfinite(prediction) & np.isfinite(target)
    if ok.sum() < 30:
        return float("nan")
    p = pd.Series(prediction[ok]).rank().to_numpy()
    t = pd.Series(target[ok]).rank().to_numpy()
    if p.std() == 0 or t.std() == 0:
        return float("nan")
    return float(np.corrcoef(p, t)[0, 1])


def monthly_ic(frame: pd.DataFrame, column: str) -> pd.Series:
    """Rank IC per signal date, restricted to rows that are trainable *and* entered.

    A name that could not be filled at ``t+1`` is excluded here as well as in training: its
    realised return is not one the account could have held, so including it measures the
    model against a portfolio nobody can own.
    """
    usable = frame[frame["entry_ok"] & frame["label"].notna()]
    out = {}
    for date, section in usable.groupby("trade_date", observed=True, sort=True):
        out[date] = rank_ic(section[column].to_numpy(), section["label"].to_numpy())
    return pd.Series(out, dtype="float64").dropna()


@dataclass
class RidgeArm:
    """Closed-form ridge on the pooled panel.

    Pooling across dates after per-date standardisation makes the fit equivalent to the
    average cross-sectional regression, which is the classical panel-predictor benchmark —
    the same object Leippold et al. (2022, JFE §4.4) use as the proportional-cost reference.
    """

    name: str = "ridge"
    lam: float = 1.0
    coef: np.ndarray | None = None
    fit_seconds: float = 0.0
    chosen_lambda: float | None = None
    lambda_trace: dict[float, float] = field(default_factory=dict)

    def _solve(self, X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
        design = np.column_stack([np.ones(len(X)), X])
        gram = design.T @ design
        penalty = np.eye(gram.shape[0]) * lam
        penalty[0, 0] = 0.0  # intercept is not shrunk
        return np.linalg.solve(gram + penalty, design.T @ y)

    def fit(self, train: pd.DataFrame, *, validate: pd.DataFrame | None = None) -> "RidgeArm":
        started = time.perf_counter()
        rows = train[train["entry_ok"] & train["label"].notna()]
        X = design_matrix(rows)
        y = np.clip(rows["label"].to_numpy(dtype="float64"), -TRAIN_LABEL_CLIP, TRAIN_LABEL_CLIP)
        if validate is not None and len(validate):
            best = None
            for lam in LAMBDA_GRID:
                coef = self._solve(X, y, lam)
                ics = []
                for _, section in validate[validate["entry_ok"] & validate["label"].notna()].groupby(
                    "trade_date", observed=True, sort=True
                ):
                    p = np.column_stack(
                        [np.ones(len(section)), design_matrix(section)]
                    ) @ coef
                    ics.append(rank_ic(p, section["label"].to_numpy()))
                score = float(np.nanmean(ics)) if ics else float("-inf")
                self.lambda_trace[lam] = score
                if best is None or score > best[1]:
                    best = (lam, score)
            lam = best[0] if best is not None and np.isfinite(best[1]) else 1.0
        else:
            lam = self.lam
        self.chosen_lambda = lam
        self.coef = self._solve(X, y, lam)
        self.fit_seconds = time.perf_counter() - started
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.coef is None:
            raise RuntimeError("RidgeArm.predict before fit")
        return np.column_stack([np.ones(len(frame)), design_matrix(frame)]) @ self.coef


@dataclass
class MlpArm:
    """Two-hidden-layer panel net, early-stopped on the time-ordered validation slice.

    The stopping criterion is the validation rank IC, not the loss: the loss is dominated by
    the cross-sectional variance of forward returns, which no arm can forecast. Averaging
    over two seeds is part of the definition of the arm (a single-seed number would be a
    lottery ticket, and the fold-by-fold comparison needs the arm's own variance reduced).
    """

    name: str = "mlp"
    states: list = field(default_factory=list)
    fit_seconds: float = 0.0
    epochs_run: list[int] = field(default_factory=list)
    val_ic: list[float] = field(default_factory=list)

    def fit(self, train: pd.DataFrame, *, validate: pd.DataFrame | None = None) -> "MlpArm":
        import torch
        import torch.nn as nn

        started = time.perf_counter()
        rows = train[train["entry_ok"] & train["label"].notna()]
        X = torch.tensor(design_matrix(rows), dtype=torch.float32)
        y = torch.tensor(
            np.clip(rows["label"].to_numpy(dtype="float64"), -TRAIN_LABEL_CLIP, TRAIN_LABEL_CLIP),
            dtype=torch.float32,
        )
        val_rows = (
            validate[validate["entry_ok"] & validate["label"].notna()]
            if validate is not None
            else pd.DataFrame()
        )

        for seed in MLP_SEEDS:
            torch.manual_seed(seed)
            net = nn.Sequential(
                nn.Linear(X.shape[1], MLP_HIDDEN[0]), nn.ReLU(), nn.Dropout(MLP_DROPOUT),
                nn.Linear(MLP_HIDDEN[0], MLP_HIDDEN[1]), nn.ReLU(), nn.Dropout(MLP_DROPOUT),
                nn.Linear(MLP_HIDDEN[1], 1),
            )
            optimizer = torch.optim.Adam(net.parameters(), lr=MLP_LR, weight_decay=1e-5)
            loss_fn = nn.MSELoss()
            generator = torch.Generator().manual_seed(seed)
            best_ic, best_state, stale, ran = -np.inf, None, 0, 0
            for epoch in range(MLP_EPOCHS):
                net.train()
                order = torch.randperm(len(X), generator=generator)
                for start in range(0, len(X), MLP_BATCH):
                    idx = order[start : start + MLP_BATCH]
                    optimizer.zero_grad()
                    loss = loss_fn(net(X[idx]).squeeze(-1), y[idx])
                    loss.backward()
                    optimizer.step()
                ran = epoch + 1
                if len(val_rows) == 0:
                    best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
                    continue
                net.eval()
                with torch.no_grad():
                    pred = net(
                        torch.tensor(design_matrix(val_rows), dtype=torch.float32)
                    ).squeeze(-1).numpy()
                scored = val_rows.copy()
                scored["_pred"] = pred
                ic = float(np.nanmean(list(monthly_ic(scored, "_pred").to_numpy())))
                if np.isfinite(ic) and ic > best_ic:
                    best_ic, stale = ic, 0
                    best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
                else:
                    stale += 1
                    if stale >= MLP_PATIENCE:
                        break
            self.states.append(best_state)
            self.epochs_run.append(ran)
            self.val_ic.append(best_ic)
        self.fit_seconds = time.perf_counter() - started
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        import torch
        import torch.nn as nn

        if not self.states:
            raise RuntimeError("MlpArm.predict before fit")
        X = torch.tensor(design_matrix(frame), dtype=torch.float32)
        preds = []
        for state in self.states:
            net = nn.Sequential(
                nn.Linear(X.shape[1], MLP_HIDDEN[0]), nn.ReLU(), nn.Dropout(MLP_DROPOUT),
                nn.Linear(MLP_HIDDEN[0], MLP_HIDDEN[1]), nn.ReLU(), nn.Dropout(MLP_DROPOUT),
                nn.Linear(MLP_HIDDEN[1], 1),
            )
            net.load_state_dict(state)
            net.eval()
            with torch.no_grad():
                preds.append(net(X).squeeze(-1).numpy())
        return np.mean(preds, axis=0)
