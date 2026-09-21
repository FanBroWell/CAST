# CAST

### A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets

Official implementation of CAST.

Accepted at **[IEEE International Conference on Data Mining (ICDM 2026)](https://icdm2026.neu.edu.cn/)**.

----

## Paper

Our paper is available on arXiv:

**CAST: A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets**  
Yu Peng, Matloob Khushi, Josiah Poon  
Accepted at IEEE International Conference on Data Mining (ICDM 2026)  
arXiv:2609.14205, 2026  
[Paper](https://arxiv.org/abs/2609.14205) | [PDF](https://arxiv.org/pdf/2609.14205)

----

CAST is a modular and interpretable trading system designed for drawdown control in stock markets. It consists of two components:

* **CoKF**: a Cross-Asset Collaborative Kalman Filter that estimates each asset's latent state online, couples assets through cross-asset correlations, and adaptively fuses multiple integrated-random-walk orders.
* **MPC**: a Model Predictive Control module that converts forecasts into trading decisions using forecast uncertainty as an explicit risk penalty.

---

## Repository Layout

```
CAST/
├── data/raw/
│   ├── NASDAQ.{parquet,json}
│   ├── CSI300.{parquet,json}
│   ├── TPX100.{parquet,json}
│   └── Global30.{parquet,json}
├── src/
│   ├── metrics.py
│   ├── mpc.py
│   ├── backtest.py
│   └── filter/
│       ├── single_ckf.py
│       └── cokf.py
└── experiments/
    └── m30_main_results.py
```

## Overall Comparison

<p align="center">
  <img src="./figures/Overall_Comparison.png" alt="CAST Overall Comparison" width="900">
</p>

---
## Datasets

Four panels of 30 daily-close stocks, January 2005 to April 2025:

| Dataset  | Description                |
|----------|----------------------------|
| NASDAQ   | U.S. large-cap             |
| CSI300   | Chinese A-share large-cap  |
| TPX100   | Japanese blue-chips        |
| Global30 | Cross-currency basket      |

Each panel is one `.parquet` (prices) + one `.json` (tickers). 

Global30 prices (different currencies) are normalized to the first-day value before backtesting, while the other three datasets use raw prices.

---

## Setup

```bash
pip install -r requirements.txt
```

Requires Python ≥ 3.10. CPU only — no GPU/CUDA needed. A full run takes ~40 minutes.

---

## Reproducing the Main Results

```bash
python3 -u experiments/m30_main_results.py
```

Settings:

| Parameter             | Value                              |
|-----------------------|------------------------------------|
| Calibration window    | data before 2010-01-01 (~5 years)  |
| Test window           | data from 2010-01-01 (~15 years)   |
| MPC horizon $L$       | 7                                  |
| Per-trade cap $\beta$ | 0.5                                |
| Initial capital       | \$1000                             |
| $\lambda$ grid        | {0.05, 0.1, 0.3, 0.6}              |
| IRW orders            | (1, 2, 3)                          |

Backtest timing and calibration:

- Decisions are made after observing the current close and are executed at the next close.
- $\rho$ and the Kalman noise parameters ($\sigma_v$, $\sigma_w$) are calibrated only from pre-2010 data and kept fixed during the 2010-2025 test window.
- During testing, Kalman states and model-order weights are updated online using only information available up to the current day.

Running `experiments/m30_main_results.py` generates the following CSV files under `data/`:

- `m30_main_results.csv`: full sweep over the reported MPC risk weights, one row per `(dataset, lambda, method)`.
- `m30_main_results_best_lambda.csv`: post-hoc summary of the best-Sharpe operating point within the reported lambda grid. This file is provided only for inspecting lambda sensitivity, not as a validation-selected evaluation protocol.


---

## Citation

If you find this repository or paper useful, please cite our work.

### BibTeX

    @misc{peng2026cast,
      title = {{CAST}: A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets},
      author = {Peng, Yu and Khushi, Matloob and Poon, Josiah},
      year = {2026},
      eprint = {2609.14205},
      archivePrefix = {arXiv},
      primaryClass = {cs.CE},
      doi = {10.48550/arXiv.2609.14205},
      url = {https://arxiv.org/abs/2609.14205},
      note = {Accepted at IEEE International Conference on Data Mining (ICDM 2026)}
    }

### APA

    `Peng, Y., Khushi, M., & Poon, J. (2026). CAST: A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets. arXiv. https://doi.org/10.48550/arXiv.2609.14205
    `

### IEEE

    `Y. Peng, M. Khushi, and J. Poon, "CAST: A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets," arXiv:2609.14205, 2026. doi: 10.48550/arXiv.2609.14205.
    `

### Plain Text

    `Yu Peng, Matloob Khushi, and Josiah Poon. CAST: A Cross-Asset State-Space Trading System for Drawdown Control in Stock Markets. arXiv:2609.14205, 2026. https://arxiv.org/abs/2609.14205
    `
