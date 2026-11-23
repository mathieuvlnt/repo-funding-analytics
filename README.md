# Repo & Funding Analytics

**Independent personal project** · Python / Pandas / Streamlit / Plotly · **100% synthetic examples**

A small four-part desk analytics app demonstrating how an EUR sovereign repo portfolio can be monitored, how short-term funding cashflows can be calculated, how a theoretical EUR/USD FX swap is quoted, and how daily Front Office / Product Control snapshots can be reconciled.

> All sample trades, trade IDs, names, collateral buckets, P&L, money market rates, spot FX and price inputs are fictional. The **off-white / red visual palette** is a personal design choice, not a corporate identity. **This is not an HSBC product, endorsed bank tool, live data feed or executable pricing system.** No logo or non-public data is used.

## Changes in this edition

- Compact, non-branded **off-white/red** interface; a red top accent and subtly rose-tinted sidebar throughout the application.
- New **Funding Maturity Ladder** on the portfolio page: four remaining-tenor buckets, Repo vs Reverse Repo split and net cash by bucket.
- More realistic deterministic source: 100 illustrative contracts (71 active, 20 expired and 9 forward-starting as of 23 Nov 2026).
- FO / PC reconciliation input files now represent the same **71 active trades at the fixed snapshot date**, while preserving five intentional breaks.
- Existing repo, deposit and FX-swap calculators remain deliberately simple and auditable.

## What is in the application?

| Tab | Functionality | Key concepts |
|---|---|---|
| **01 · Portfolio & P&L** | Load a 100-trade synthetic source history (some expired, some active, some forward-starting); choose a position date; filter by country / side; see gross cash, net cash borrowing, indicative sample P&L and estimated 1-day carry; group by country, collateral, ticker, trader or side; inspect a **funding maturity ladder** split between repo and reverse repo, Top 5 P&L contributors and download filtered trades. | `read_csv`, date filtering, ACT maturity buckets, calculated columns, `groupby`, `agg`, `nlargest`, weights |
| **02 · Cash Funding Pricers** | Two sub-tabs: **Repo / Reverse Repo** with ACT/360 interest, collateral haircut and rate sensitivity; **unsecured money market deposit / borrowing** with signed opening and maturity cashflows and rate sensitivity. | Dates, simple interest, conventions, signed cashflows, scenario tables |
| **03 · FX Swap Pricer** | **EUR/USD** theoretical outright forward based on money-market rates and covered interest parity; forward points, near / far currency exchanges, EUR or USD interest-rate sensitivity. | Covered interest parity, FX quote conventions, scenario repricing |
| **04 · Daily Reconciliation** | Compare fictional Front Office and Product Control CSVs, detect P&L or cash breaks and missing trade IDs, change tolerances, view match rate and export exceptions. | `merge(how="outer", indicator=True, validate="one_to_one")`, column arithmetic, exception filtering |

## Run it on your computer

Python **3.10 or newer** is recommended. Extract the ZIP and open a terminal in the project directory:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On **Windows**, double-click `run_windows.bat` (requires Python on PATH). On **macOS / Linux**, run `bash run_mac_linux.sh`.

The dashboard should open at **http://localhost:8501**.

## Project structure

```text
repo-funding-analytics/
├── app.py                         # Streamlit UI, 4 main tabs
├── analytics.py                   # Isolated pricing, aggregation, reconciliation
├── .streamlit/config.toml         # Off-white and red theme
├── data/
│   ├── portfolio.csv              # 100 synthetic repo/reverse repo positions
│   ├── front_office.csv           # 71-row active FO snapshot
│   └── product_control.csv        # 71-row PC snapshot, deliberate breaks
├── scripts/
│   ├── generate_demo_data.py      # Deterministic generator
│   └── base_portfolio_16.csv      # Preserved fictitious seed rows
├── docs/
│   ├── METHODOLOGY.md             # Financial conventions & limitations
│   ├── GUIDE_ENTRETIEN_FR.md     # How to explain the app and calculations
│   └── VALIDATION.md              # Checks performed & honest runtime limitations
├── tests/test_analytics.py        # 25 automated tests
├── requirements.txt
├── requirements-dev.txt
├── run_windows.bat
└── run_mac_linux.sh
```

## Data schema

`data/portfolio.csv` contains **100 synthetic contracts**: **71 active**, **20 expired** and **9 not yet started**, as of the default snapshot **23 November 2026**. These counts change with the date filter. All rates and amounts are fictional.

It includes:

- `trade_id` — unique transaction ID (e.g., `R001`). **Required for reconciliation**.
- `ticker` — fictional collateral **bucket** label (e.g., `BUND-10Y`). **Not a trade ID, real security ticker, ISIN or live instrument quote**. Optional for uploaded CSVs; synthesized from collateral if absent.
- `trade_date`, `maturity_date` — contractual dates (`YYYY-MM-DD`). A trade is active when `trade_date ≤ position_date < maturity_date`.
- `trader`, `country`, `collateral`, `side` — fictional desk labels and `Repo` / `Reverse Repo`.
- `cash_amount_eur` — positive cash principal; `side` determines cash direction.
- `repo_rate_pct` — annual rate **in percent** (`2.5` means 2.5%).
- `pnl_eur` — **illustrative P&L input**; it is not calculated from a market valuation model.

The reconciliation files each have `trade_id`, `signed_cash_eur`, `pnl_eur` and represent a **fixed desk snapshot for 23 November 2026**, not all 100 historical contracts. Each file contains **71 rows**, drawn from the 71 outstanding positions (with deliberately introduced discrepancies); **72 unique IDs** appear after a full outer join. Five exceptions are built in: R005 and R011 P&L breaks, R008 cash break, R014 missing from Product Control, and an additional fictional R017 present only in Product Control. The remaining **67 trades** match. The reconciling ledgers do not automatically change when the user modifies the portfolio position-date filter.

The source portfolio is generated reproducibly with a fixed random seed; none of its rate, size or P&L values represent observed executable trades.

### Key interpretations

- **Gross cash**: sum of absolute cash principals of active / selected trades.
- **Net cash borrowing**: repo cash borrowed *minus* reverse-repo cash lent.
- **Weight**: each trade cash principal divided by total gross cash of the **selected set**.
- **Funding maturity ladder**: active trades grouped by remaining **calendar days** to maturity: 1 day, 2–7, 8–30, and over 30; both funding directions shown as positive gross amounts; net borrowing retains signs. These are **remaining-tenor buckets**, not literal contractual ON/TN trade labels.
- **Illustrative P&L**: sum of **given sample P&L** (not interest carry, not computed MTM).
- **1-day carry**: net estimated interest run-rate at each repo rate, on ACT/360, before fees.
- **Repo / deposit rate sensitivities**: hypothetical re-pricing of the **entire contract tenor** at different interest rates, **not an MTM value of an existing fixed-rate trade**.
- **FX swap**: theoretical EUR/USD forward via simple covered-interest parity; actual tradable swaps also reflect bid/ask, basis, curves, settlement conventions and other factors.
- **Reconciliation**: illustrative trade-level snapshot comparison; not a full independent position, collateral and settlement reconciliation.

See `docs/METHODOLOGY.md` for equations, worked examples and limitations.

## Regenerate the data

```bash
python scripts/generate_demo_data.py
```

This overwrites the three **synthetic CSVs** in `data/` with the reproducible 100-transaction sample. The portfolio preserves the 16 initial illustrative records and adds 84 mixed-lifecycle rows. Generated start and maturity dates are adjusted for weekends only (not full TARGET or settlement holiday calendars). The two ledgers are regenerated from the outstanding positions at 23 November 2026.

## Tests

Install test dependencies and run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The code is deliberately modular so that the calculations can be audited in `analytics.py`, independently of the dashboard presentation.

## Methodology sources (general conventions, not market data)

- ICMA: [What is a haircut?](https://www.icmagroup.org/market-practice-and-regulatory-policy/repo-and-collateral-markets/icma-ercc-publications/frequently-asked-questions-on-repo/21-what-is-a-haircut/) — repo collateral haircuts.
- BIS: [Covered interest parity lost: understanding the cross-currency basis](https://www.bis.org/publications/qr-201609/covered-interest-parity-lost-understanding-cross-currency-basis) — theoretical FX forward relationship and real-world basis.

## Scope

This is a learning and demonstration project, not investment advice and not a substitute for a trading or control platform. The project avoids artificial complexity: no external API, trading credentials, market feed, real bank data, or hidden model.
