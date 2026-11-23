"""Small, auditable calculations for a fictional EUR repo portfolio.

No market feeds or internal desk systems. All amounts in EUR; rates as annual %.
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

import pandas as pd

REQUIRED_PORTFOLIO = [
    "trade_id", "trade_date", "maturity_date", "trader", "country",
    "collateral", "side", "cash_amount_eur", "repo_rate_pct", "pnl_eur",
]
REQUIRED_LEDGER = ["trade_id", "signed_cash_eur", "pnl_eur"]
VALID_SIDES = {"Repo", "Reverse Repo"}


def validate_portfolio(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize user-supplied, EUR-denominated position data."""
    missing = sorted(set(REQUIRED_PORTFOLIO) - set(raw.columns))
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    df = raw[REQUIRED_PORTFOLIO].copy()
    # Optional illustrative collateral bucket label, separate from trade_id.
    if "ticker" in raw.columns:
        df["ticker"] = raw["ticker"].astype("string").str.strip()
    else:
        df["ticker"] = df["collateral"].str.upper() + "-GEN"
    if df["ticker"].isna().any() or df["ticker"].eq("").any():
        raise ValueError("ticker cannot contain empty values.")
    df["trade_id"] = df["trade_id"].astype("string").str.strip()
    for col in ("trader", "country", "collateral", "side"):
        df[col] = df[col].astype("string").str.strip()
    if df.empty:
        raise ValueError("The portfolio file has no transactions.")
    if df["trade_id"].isna().any() or df["trade_id"].eq("").any():
        raise ValueError("Every transaction must have a trade_id.")
    if df["trade_id"].duplicated().any():
        raise ValueError("trade_id must be unique (one row per trade).")
    if df["side"].isna().any() or not df["side"].isin(VALID_SIDES).all():
        raise ValueError("side must be 'Repo' or 'Reverse Repo'.")
    for col in ("trader", "country", "collateral"):
        if df[col].isna().any() or df[col].eq("").any():
            raise ValueError(f"{col} cannot contain empty values.")
    for col in ("trade_date", "maturity_date"):
        df[col] = pd.to_datetime(df[col], errors="raise").dt.normalize()
    if df[["trade_date", "maturity_date"]].isna().any().any():
        raise ValueError("trade_date and maturity_date cannot be empty.")
    if (df["maturity_date"] <= df["trade_date"]).any():
        raise ValueError("Every maturity_date must be after trade_date.")
    for col in ("cash_amount_eur", "repo_rate_pct", "pnl_eur"):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if df[col].isna().any() or not df[col].map(lambda x: pd.notna(x) and abs(x) != float("inf")).all():
            raise ValueError(f"{col} must have finite numeric values.")
    if (df["cash_amount_eur"] <= 0).any():
        raise ValueError("cash_amount_eur must be strictly positive; use side for direction.")
    return df


def enrich_portfolio(raw: pd.DataFrame, as_of: date | str | pd.Timestamp) -> pd.DataFrame:
    """Add funding direction, exposure, tenor and *estimated* single-day carry.

    pnl_eur is an independent illustrative P&L input, NOT calculated by this model.
    Carry is a one-day gross interest run rate, not mark-to-market trading P&L.
    """
    df = validate_portfolio(raw)
    as_of_ts = pd.Timestamp(as_of).normalize()
    df = df.loc[(df["trade_date"] <= as_of_ts) & (df["maturity_date"] > as_of_ts)].copy()
    if df.empty:
        return df.assign(
            signed_cash_eur=pd.Series(dtype=float), tenor_days=pd.Series(dtype=int),
            daily_carry_eur=pd.Series(dtype=float), gross_weight_pct=pd.Series(dtype=float)
        )
    # Positive = funding received (repo); negative = cash deployed (reverse repo).
    df["signed_cash_eur"] = df["cash_amount_eur"].where(
        df["side"].eq("Repo"), -df["cash_amount_eur"]
    )
    df["tenor_days"] = (df["maturity_date"] - df["trade_date"]).dt.days
    # Repo interest is an expense; reverse-repo interest is income.
    df["daily_carry_eur"] = (
        -df["signed_cash_eur"] * (df["repo_rate_pct"] / 100) / 360
    )
    df["gross_weight_pct"] = df["cash_amount_eur"] / df["cash_amount_eur"].sum() * 100
    return df


def portfolio_summary(df: pd.DataFrame) -> dict[str, float | int]:
    """Summarize the active, already-enriched portfolio."""
    if df.empty:
        return dict(trades=0, gross_eur=0., net_borrowing_eur=0., pnl_eur=0., daily_carry_eur=0.)
    return dict(
        trades=len(df),
        gross_eur=float(df["cash_amount_eur"].sum()),
        net_borrowing_eur=float(df["signed_cash_eur"].sum()),
        pnl_eur=float(df["pnl_eur"].sum()),
        daily_carry_eur=float(df["daily_carry_eur"].sum()),
    )


def grouped_portfolio(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Group exposures and illustrative P&L without netting absolute weights."""
    if by not in {"country", "collateral", "ticker", "trader", "side"}:
        raise ValueError("Unsupported grouping dimension")
    columns = [by, "trades", "gross_eur", "net_eur", "pnl_eur", "daily_carry_eur", "gross_weight_pct"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    grouped = df.groupby(by, as_index=False).agg(
        trades=("trade_id", "count"),
        gross_eur=("cash_amount_eur", "sum"),
        net_eur=("signed_cash_eur", "sum"),
        pnl_eur=("pnl_eur", "sum"),
        daily_carry_eur=("daily_carry_eur", "sum"),
    )
    grouped["gross_weight_pct"] = grouped["gross_eur"] / df["cash_amount_eur"].sum() * 100
    return grouped.sort_values("gross_eur", ascending=False).reset_index(drop=True)



def funding_maturity_ladder(df: pd.DataFrame, as_of: date | str | pd.Timestamp) -> pd.DataFrame:
    """Outstanding secured cash by *remaining calendar days* to maturity.

    Feed an enriched, active portfolio (optionally filtered by country/side).
    Buckets do not claim a trade was contracted as overnight or tomorrow-next.
    Both lending and borrowing principal amounts are shown as non-negative
    amounts in the ladder; their signed difference is net cash borrowing.
    """
    labels = ["1 day", "2–7 days", "8–30 days", ">30 days"]
    columns = ["maturity_bucket", "trades", "repo_eur", "reverse_eur", "gross_eur", "net_eur"]
    if df.empty:
        return pd.DataFrame({
            "maturity_bucket": labels,
            "trades": [0] * 4, "repo_eur": [0.] * 4,
            "reverse_eur": [0.] * 4, "gross_eur": [0.] * 4, "net_eur": [0.] * 4,
        })[columns]
    remaining = (df["maturity_date"] - pd.Timestamp(as_of).normalize()).dt.days
    if remaining.le(0).any():
        raise ValueError("Maturity ladder requires only active, unexpired trades")
    if not df["side"].isin(VALID_SIDES).all():
        raise ValueError("Invalid funding side in the maturity ladder")
    temp = df[["side", "cash_amount_eur"]].copy()
    temp["maturity_bucket"] = pd.cut(
        remaining, bins=[0, 1, 7, 30, float("inf")], labels=labels,
        include_lowest=True,
    )
    temp["repo_eur"] = temp["cash_amount_eur"].where(temp["side"].eq("Repo"), 0.)
    temp["reverse_eur"] = temp["cash_amount_eur"].where(temp["side"].eq("Reverse Repo"), 0.)
    grouped = temp.groupby("maturity_bucket", observed=True).agg(
        trades=("cash_amount_eur", "size"),
        repo_eur=("repo_eur", "sum"),
        reverse_eur=("reverse_eur", "sum"),
    ).reindex(labels, fill_value=0).reset_index()
    grouped["gross_eur"] = grouped["repo_eur"] + grouped["reverse_eur"]
    grouped["net_eur"] = grouped["repo_eur"] - grouped["reverse_eur"]
    return grouped[columns]

def repo_interest(cash_eur: float, annual_rate_pct: float, days: int) -> float:
    """Simple ACT/360 repo interest; negative repo rates are allowed."""
    if cash_eur <= 0:
        raise ValueError("Cash must be strictly positive")
    if days <= 0:
        raise ValueError("End date must be later than start date")
    return cash_eur * (annual_rate_pct / 100) * days / 360


def funding_scenarios(
    cash_eur: float, rate_pct: float, days: int, side: str,
    shocks_bp: Sequence[int] = (-50, -25, 0, 25, 50),
) -> pd.DataFrame:
    """Model interest sensitivity, not an MTM or hedged trading P&L."""
    if side not in VALID_SIDES:
        raise ValueError("Invalid repo side")
    base = repo_interest(cash_eur, rate_pct, days)
    sign = -1 if side == "Repo" else 1
    rows = []
    for bp in shocks_bp:
        rate = rate_pct + bp / 100  # 100 bp = 1 percentage point
        interest = repo_interest(cash_eur, rate, days)
        rows.append({
            "shock_bp": int(bp), "rate_pct": rate,
            "interest_eur": interest,
            "signed_interest_eur": sign * interest,
            "delta_signed_eur": sign * (interest - base),
        })
    return pd.DataFrame(rows)


def validate_ledger(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    missing = sorted(set(REQUIRED_LEDGER) - set(raw.columns))
    if missing:
        raise ValueError(f"{label}: missing columns: {', '.join(missing)}")
    df = raw[REQUIRED_LEDGER].copy()
    df["trade_id"] = df["trade_id"].astype("string").str.strip()
    if df["trade_id"].isna().any() or df["trade_id"].eq("").any():
        raise ValueError(f"{label}: empty trade_id")
    if df["trade_id"].duplicated().any():
        raise ValueError(f"{label}: duplicate trade_id (one row per trade expected)")
    for col in ("signed_cash_eur", "pnl_eur"):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if df[col].isna().any() or not df[col].map(lambda x: pd.notna(x) and abs(x) != float("inf")).all():
            raise ValueError(f"{label}: invalid numeric values in {col}")
    return df


def reconcile(
    front_office: pd.DataFrame,
    product_control: pd.DataFrame,
    pnl_tolerance_eur: float = 1.,
    cash_tolerance_eur: float = 1.,
) -> pd.DataFrame:
    """One-to-one full outer reconciliation of illustrative trade-level snapshots."""
    if pnl_tolerance_eur < 0 or cash_tolerance_eur < 0:
        raise ValueError("Tolerances must be non-negative")
    fo = validate_ledger(front_office, "Front Office")
    pc = validate_ledger(product_control, "Product Control")
    result = fo.merge(
        pc, on="trade_id", how="outer", suffixes=("_fo", "_pc"),
        indicator=True, validate="one_to_one"
    )
    result["pnl_diff_eur"] = result["pnl_eur_fo"] - result["pnl_eur_pc"]
    result["cash_diff_eur"] = result["signed_cash_eur_fo"] - result["signed_cash_eur_pc"]

    def classify(row: pd.Series) -> str:
        if row["_merge"] == "left_only":
            return "Missing in PC"
        if row["_merge"] == "right_only":
            return "Missing in FO"
        pnl_break = abs(row["pnl_diff_eur"]) > pnl_tolerance_eur
        cash_break = abs(row["cash_diff_eur"]) > cash_tolerance_eur
        if pnl_break and cash_break:
            return "P&L + Cash break"
        if pnl_break:
            return "P&L break"
        if cash_break:
            return "Cash break"
        return "Matched"

    result["status"] = result.apply(classify, axis=1)
    return result.sort_values(["status", "trade_id"]).reset_index(drop=True)


# ---------- Cash funding / FX swap demo pricing ----------


def cash_deposit_pricing(
    principal_eur: float, annual_rate_pct: float, days: int, side: str
) -> dict[str, float | int]:
    """Unsecured fixed-rate deposit. Side is from the desk's perspective.

    Cash lending: pay principal today, receive principal + interest at maturity.
    Cash borrowing: receive principal today, pay principal + interest at maturity.
    Negative rates are permitted and reverse interest signs automatically.
    """
    if side not in {"Cash lending", "Cash borrowing"}:
        raise ValueError("Side must be Cash lending or Cash borrowing")
    interest = repo_interest(principal_eur, annual_rate_pct, days)
    sign = 1 if side == "Cash lending" else -1
    return {
        "tenor_days": days,
        "gross_interest_eur": interest,
        "signed_interest_eur": sign * interest,
        "opening_cashflow_eur": -sign * principal_eur,
        "maturity_cashflow_eur": sign * (principal_eur + interest),
    }


def deposit_scenarios(
    principal_eur: float, annual_rate_pct: float, days: int, side: str,
    shocks_bp: Sequence[int] = (-50, -25, 0, 25, 50),
) -> pd.DataFrame:
    """Signed interest change for rate repricing, not an existing-deposit MTM."""
    base = cash_deposit_pricing(principal_eur, annual_rate_pct, days, side)
    rows = []
    for bp in shocks_bp:
        rate = annual_rate_pct + bp / 100
        calc = cash_deposit_pricing(principal_eur, rate, days, side)
        rows.append({
            "shock_bp": bp,
            "rate_pct": rate,
            "interest_eur": calc["gross_interest_eur"],
            "signed_interest_eur": calc["signed_interest_eur"],
            "delta_signed_eur": calc["signed_interest_eur"] - base["signed_interest_eur"],
        })
    return pd.DataFrame(rows)


def fx_forward_quote(
    spot_usd_per_eur: float,
    eur_rate_pct: float,
    usd_rate_pct: float,
    days: int,
    basis_bp: float = 0.0,
) -> dict[str, float]:
    """Illustrative EUR/USD forward via single-period covered interest parity.

    Spot is quoted USD per 1 EUR. Both money market inputs use ACT/360.
    Optional basis is a *hypothetical adjustment to USD rate*, not a market quote.
    This is not a tradable FX-swap bid/ask pricing model.
    """
    import math
    if not math.isfinite(spot_usd_per_eur) or spot_usd_per_eur <= 0:
        raise ValueError("Spot EUR/USD must be strictly positive")
    if days <= 0:
        raise ValueError("End date must be later than start date")
    if not all(map(math.isfinite, (eur_rate_pct, usd_rate_pct, basis_bp))):
        raise ValueError("Rates and basis must be finite")
    t = days / 360
    usd_factor = 1 + (usd_rate_pct + basis_bp / 100) / 100 * t
    eur_factor = 1 + eur_rate_pct / 100 * t
    if usd_factor <= 0 or eur_factor <= 0:
        raise ValueError("Accumulation factors must be positive")
    fwd = spot_usd_per_eur * usd_factor / eur_factor
    points = (fwd - spot_usd_per_eur) * 10_000
    return {"forward": fwd, "swap_points_pips": points, "tenor_years": t}


def fx_swap_cashflows(
    notional_eur: float,
    spot_usd_per_eur: float,
    forward_usd_per_eur: float,
    near_side: str,
) -> pd.DataFrame:
    """Near and far FX legs from perspective of a desk buying/selling EUR near.

    'Buy EUR near': receive EUR / pay USD spot; reverse at far date.
    All rates are USD per EUR, no premiums or fees.
    """
    import math
    if not math.isfinite(notional_eur) or notional_eur <= 0:
        raise ValueError("EUR notional must be strictly positive")
    if near_side not in {"Buy EUR near", "Sell EUR near"}:
        raise ValueError("Invalid near-leg side")
    if not all(math.isfinite(x) and x > 0 for x in (spot_usd_per_eur, forward_usd_per_eur)):
        raise ValueError("FX rates must be strictly positive")
    sign = 1 if near_side == "Buy EUR near" else -1
    return pd.DataFrame([
        {"leg": "Near / Spot", "eur_cashflow": sign * notional_eur, "usd_cashflow": -sign * notional_eur * spot_usd_per_eur},
        {"leg": "Far / Forward", "eur_cashflow": -sign * notional_eur, "usd_cashflow": sign * notional_eur * forward_usd_per_eur},
    ])


def fx_rate_scenarios(
    spot: float, eur_rate_pct: float, usd_rate_pct: float, days: int,
    shock_currency: str, shocks_bp: Sequence[int] = (-50, -25, 0, 25, 50),
) -> pd.DataFrame:
    """Sensitivity of theoretical outright EUR/USD forward to one rate input."""
    if shock_currency not in {"EUR", "USD"}:
        raise ValueError("shock_currency must be EUR or USD")
    base = fx_forward_quote(spot, eur_rate_pct, usd_rate_pct, days)
    rows = []
    for bp in shocks_bp:
        eur = eur_rate_pct + (bp / 100 if shock_currency == "EUR" else 0)
        usd = usd_rate_pct + (bp / 100 if shock_currency == "USD" else 0)
        result = fx_forward_quote(spot, eur, usd, days)
        rows.append({
            "shock_bp": bp,
            "forward": result["forward"],
            "swap_points_pips": result["swap_points_pips"],
            "delta_points_pips": result["swap_points_pips"] - base["swap_points_pips"],
        })
    return pd.DataFrame(rows)
