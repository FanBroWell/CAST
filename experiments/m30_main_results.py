from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest import (
    backtest_panel_raw,
    backtest_cokf_raw,
    metric_row,
)
from src.mpc import PaperMPC
from src.filter.single_ckf import (
    CollaborativeKF,
    calibrate_sigma_raw,
)
from src.filter.cokf import (
    CrossAssetCollaborativeKF,
    estimate_rho_raw,
)

DATA_DIR = ROOT / "data" / "raw"

DATASETS = [
    "NASDAQ",
    "CSI300",
    "TPX100",
    "Global30",
]

NORMALISE_DATASETS = {
    "Global30",
}

CAL_END = "2010-01-01"
HORIZON_L = 7
ORDERS = (1, 2, 3)
V_0 = 1000.0
LAMBDAS = (0.05, 0.1, 0.3, 0.6)
B = 0.5

SIGMA_L_FLOOR_MULT = 1.5


class PaperMPCFloored(PaperMPC):
    def __init__(self, *args, sigma_l_mult: float = SIGMA_L_FLOOR_MULT, **kwargs):
        super().__init__(*args, **kwargs)
        self.sigma_l_mult = sigma_l_mult

    def solve(self, u_current, price_pred, sigma_l_paper, capital):
        return super().solve(u_current, price_pred,
                             sigma_l_paper * self.sigma_l_mult, capital)


def make_multi(sigma_v: float, sigma_w: float, horizon: int):
    return CollaborativeKF(
        orders=ORDERS,
        sigma_v_list=tuple(sigma_v for _ in ORDERS),
        sigma_w=sigma_w,
        horizon=horizon,
    )


def load_panel(dataset: str) -> pd.DataFrame:
    panel = pd.read_parquet(DATA_DIR / f"{dataset}.parquet")
    panel = panel.ffill().bfill().dropna(how="any")
    if dataset in NORMALISE_DATASETS:
        panel = panel / panel.iloc[0]
    return panel


def run_dataset(dataset: str, lam: float) -> dict:
    panel = load_panel(dataset)
    raw = panel.values
    cal_end_ts = pd.Timestamp(CAL_END)
    test_start_idx = int(np.searchsorted(panel.index.values, cal_end_ts.to_datetime64()))

    cal = panel.loc[panel.index < CAL_END]
    sigma_v = np.zeros(panel.shape[1])
    sigma_w = np.zeros(panel.shape[1])
    for j, col in enumerate(panel.columns):
        sigma_v[j], sigma_w[j] = calibrate_sigma_raw(cal[col].values, order=1)

    out = {
        "dataset": dataset,
        "lambda": lam,
        "test_start_idx": test_start_idx,
    }

    t0 = time.time()
    res_multi = backtest_panel_raw(
        predictor_factory=lambda i: make_multi(
            float(sigma_v[i]), float(sigma_w[i]), HORIZON_L,
        ),
        mpc_factory=lambda: PaperMPCFloored(horizon=HORIZON_L, lam=lam, b=B),
        raw_panel=raw,
        test_start_idx=test_start_idx,
        V_0_per_asset=V_0,
    )
    out["CKF"] = metric_row(res_multi["V_portfolio"][test_start_idx:])
    print(f"    CKF   λ={lam}  done in {time.time()-t0:.1f}s")

    t0 = time.time()
    rho = estimate_rho_raw(raw, cal_end_idx=test_start_idx)
    sigma_v_per_order = tuple(sigma_v.copy() for _ in ORDERS)
    cokf = CrossAssetCollaborativeKF(
        M=panel.shape[1],
        orders=ORDERS,
        sigma_v_per_order=sigma_v_per_order,
        sigma_w=sigma_w,
        rho=rho,
        horizon=HORIZON_L,
    )
    res_x = backtest_cokf_raw(
        cokf=cokf,
        mpc_factory=lambda: PaperMPCFloored(horizon=HORIZON_L, lam=lam, b=B),
        raw_panel=raw,
        test_start_idx=test_start_idx,
        V_0_per_asset=V_0,
    )
    out["CAST"] = metric_row(res_x["V_portfolio"][test_start_idx:])
    print(f"    CAST   λ={lam}  done in {time.time()-t0:.1f}s")

    out["rho_mean"] = float(rho[~np.eye(len(rho), dtype=bool)].mean())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Main trading results: CKF + CAST across λ on 4 datasets")
    parser.add_argument("--resume", action="store_true",
                        help="Skip (dataset, lambda) pairs already present in the output CSV")
    args = parser.parse_args()

    csv_path = ROOT / "data" / "m30_main_results.csv"

    rows = []
    completed = set()
    if args.resume and csv_path.exists():
        existing = pd.read_csv(csv_path)
        rows = existing.to_dict(orient="records")
        completed = {(d, round(float(l), 4))
                     for d, l in zip(existing["dataset"], existing["lambda"])}
        print(f"[resume] {len(completed)} (dataset, lambda) trading pairs already done.",
              flush=True)

    for dataset in DATASETS:
        print(f"\n=== {dataset} (trading) ===", flush=True)
        for lam in LAMBDAS:
            if (dataset, round(float(lam), 4)) in completed:
                print(f"    SKIP {dataset} λ={lam} (already in CSV)", flush=True)
                continue
            r = run_dataset(dataset, lam)
            for method in ("CKF", "CAST"):
                rows.append({
                    "dataset":  dataset,
                    "lambda":   lam,
                    "method":   method,
                    "rho_mean": r["rho_mean"],
                    **r[method],
                })
            tmp_path = csv_path.with_suffix(".csv.tmp")
            pd.DataFrame(rows).to_csv(tmp_path, index=False)
            tmp_path.replace(csv_path)
            print(f"    [checkpoint] {len(rows)} rows saved -> "
                  f"{csv_path.relative_to(ROOT)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    print(f"\nTrading results -> {csv_path.relative_to(ROOT)}")

    print(f"\n{'='*100}\n  TRADING METRIC TABLE — 4 datasets × 4 lambdas × (CKF, CAST)\n{'='*100}")
    cols = ["dataset", "lambda", "method",
            "sharpe", "sortino", "max_dd",
            "ann_return", "calmar", "win_rate",
            "final_value", "busted"]
    avail = [c for c in cols if c in df.columns]
    print(df[avail].to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    pivots = {}
    for method in ("CKF", "CAST"):
        print(f"\n{'='*100}\n  SHARPE PIVOT — {method}\n{'='*100}")
        p = df[df["method"] == method].pivot(index="dataset", columns="lambda", values="sharpe")
        print(p.to_string(float_format=lambda x: f"{x:+.3f}"))
        pivots[method] = p

    print(f"\n{'='*100}\n  CAST MINUS CKF  (Sharpe Δ; positive ⇒ CAST wins)\n{'='*100}")
    print((pivots["CAST"] - pivots["CKF"]).to_string(float_format=lambda x: f"{x:+.3f}"))

    print(f"\n{'='*100}\n  BEST-LAMBDA SUMMARY (per dataset × method, ranked by Sharpe)\n{'='*100}")
    best = (df.sort_values("sharpe", ascending=False)
              .groupby(["dataset", "method"], as_index=False)
              .head(1)
              .sort_values(["dataset", "method"]))
    summary_cols = ["dataset", "method", "lambda", "rho_mean",
                    "sharpe", "sortino", "calmar",
                    "max_dd", "ann_return",
                    "final_value", "busted"]
    av = [c for c in summary_cols if c in best.columns]
    print(best[av].to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    best_csv = ROOT / "data" / "m30_main_results_best_lambda.csv"
    best.to_csv(best_csv, index=False)
    print(f"\nBest-lambda summary -> {best_csv.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
