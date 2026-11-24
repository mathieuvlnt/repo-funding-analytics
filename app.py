from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    cash_deposit_pricing,
    deposit_scenarios,
    enrich_portfolio,
    funding_scenarios,
    funding_maturity_ladder,
    #fx_forward_quote,
    #fx_rate_scenarios,
    #fx_swap_cashflows,
    grouped_portfolio,
    portfolio_summary,
    reconcile,
    repo_interest)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SNAPSHOT = date(2026, 11, 23)
RED = "#DB0011"
INK = "#2A2A2A"
MUTED = "#77716E"
PAPER = "#F7F5F2"
GOOD = "#31745D"
BAD = "#B94A47"
CHART_COLORS = ["#DB0011", "#B4525A", "#E3B2B7", "#62585B", "#A89A97", "#E5CBCB", "#8A7770", "#D58C8C"]

st.set_page_config(
    page_title="Repo Funding & P&L Analytics | REPO / LAB",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded")


st.markdown("""
<style>
header[data-testid="stHeader"] {
    border-top: 10px solid #DB0011 !important;}

.hero {
    background: white;
    padding: 22px 24px;
    border-radius: 10px;
    border: 1px solid #E7D6D8;
    border-top: 4px solid #DB0011;}

.hero h1 {
    font-size: 30px;
    color: #2A2A2A;}

.brand {
    font-size: 18px;
    font-weight: bold;}

.brand span {
    color: #DB0011;}

.note, .sidebar-note {
    padding: 12px;
    background: white;
    border-left: 3px solid #DB0011;}


[data-testid="stMetric"] {
    background: white;
    padding: 18px;
    border: 1px solid #E7D6D8;
    border-top: 3px solid #DB0011;
    border-radius: 10px;}

</style>
""", unsafe_allow_html=True)


def eur(value: float, compact: bool = False, signed: bool = False, decimals: int = 2) -> str:
    sign = "−" if value < 0 else ("+" if signed and value > 0 else "")
    abs_v = abs(float(value))
    div, suffix = 1, ""
    if compact and abs_v >= 1e9:
        div, suffix = 1e9, "bn"
    elif compact and abs_v >= 1e6:
        div, suffix = 1e6, "m"
    elif compact and abs_v >= 1e3:
        div, suffix = 1e3, "k"
    return f"{sign}€{abs_v / div:,.{decimals}f}{suffix}"


def number(value: float, decimals: int = 2, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:,.{decimals}f}"


def chart_style(fig: go.Figure, height: int = 275) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=12),
        margin=dict(l=10, r=54, t=22, b=18),
        showlegend=False,
        xaxis=dict(showgrid=False, linecolor="#DED8CF", zeroline=False),
        yaxis=dict(gridcolor="#EBE5DE", zeroline=False),)
    return fig


def note(content: str) -> None:
    st.markdown(f'<div class="note">{content}</div>', unsafe_allow_html=True)


def scenario_visual(scenarios: pd.DataFrame, axis_label: str, title: str) -> None:
    graph, table = st.columns([1.0, 1.05], gap="large")
    with graph:
        st.markdown(f"**{title}**")
        fig = go.Figure(go.Scatter(
            x=scenarios["shock_bp"], y=scenarios["delta_signed_eur"],
            mode="lines+markers", line=dict(color=RED, width=3),
            marker=dict(color=RED, size=8),
            hovertemplate="Shock %{x:+d} bp<br>Δ cashflow €%{y:+,.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color="#B6A8A4")
        fig.update_xaxes(title="Rate shock (bp)", dtick=25)
        fig.update_yaxes(title=axis_label, tickformat="~s")
        st.plotly_chart(chart_style(fig), use_container_width=True, config={"displayModeBar": False})
    with table:
        st.markdown("**Scenario table**")
        view = scenarios.rename(columns={
            "shock_bp": "Shock (bp)", "rate_pct": "Rate (%)",
            "interest_eur": "Gross interest (€)",
            "signed_interest_eur": "Net interest (€)",
            "delta_signed_eur": "Δ net interest (€)",
        }).copy()
        view["Shock (bp)"] = view["Shock (bp)"].map(lambda v: f"{v:+d}")
        view["Rate (%)"] = view["Rate (%)"].map(lambda v: number(v, 3))
        for key in ("Gross interest (€)", "Net interest (€)", "Δ net interest (€)"):
            view[key] = view[key].map(lambda v: eur(v, signed=True))
        st.dataframe(view, use_container_width=True, hide_index=True)


def render_portfolio() -> None:
    st.subheader("EUR sovereign repo book")
    # Upload is intentionally secondary: sample data are available immediately.
    with st.expander("Upload custom portfolio (CSV) · optional", expanded=False):
        upload = st.file_uploader("Upload file using the sample CSV schema", type=["csv"], key="portfolio_csv")
        st.caption("The supplied 1000 synthetic transactions load automatically if no file is uploaded.")
    try:
        raw = pd.read_csv(upload if upload is not None else DATA / "portfolio_1000_4_traders.csv")
        a, b, c = st.columns([1.0, 1.0, 1.0], gap="medium")
        with a:
            as_of = st.date_input("Position date", value=SNAPSHOT, key="position_date")
        active = enrich_portfolio(raw, as_of)
    except (ValueError, KeyError, TypeError, pd.errors.ParserError) as exc:
        st.error(f"Portfolio CSV could not be loaded: {exc}")
        return
    with b:
        country = st.selectbox("Collateral country", ["All countries"] + sorted(active["country"].dropna().unique().tolist()))
    with c:
        side = st.selectbox("Funding side", ["All transactions", "Repo", "Reverse Repo"])
    filtered = active.copy()
    if country != "All countries":
        filtered = filtered.loc[filtered["country"] == country].copy()
    if side != "All transactions":
        filtered = filtered.loc[filtered["side"] == side].copy()
    if filtered.empty:
        st.info(f"No active transactions match the selected date / filters. Source file contains {len(raw)} trades.")
        return
    filtered["gross_weight_pct"] = filtered["cash_amount_eur"] / filtered["cash_amount_eur"].sum() * 100
    summary = portfolio_summary(filtered)
    st.caption(f"**{len(filtered)} selected positions** · {len(active)} outstanding on {as_of:%d %b %Y} · {len(raw)} transactions in the source CSV (including past and future trades)")
    k1, k2, k3, k4 = st.columns(4, gap="small")
    for card, label, val, desc in [
        (k1, "Gross cash exposure", eur(summary["gross_eur"], compact=True), "Total active absolute cash"),
        (k2, "Net cash borrowing", eur(summary["net_borrowing_eur"], compact=True, signed=True), "Repo less reverse repo"),
        (k3, "Illustrative Daily P&L · sample", eur(summary["pnl_eur"], compact=True, signed=True), "Supplied fictitious P&L, not modelled"),
        (k4, "Daily funding carry", eur(summary["daily_carry_eur"], compact=True, signed=True), "ACT/360 estimated net interest"),
    ]:
        with card:
            st.metric(label, val)
            st.caption(desc)
    # Maturity ladder: remaining *calendar days* on active, selected trades.
    st.markdown("#### Funding maturity ladder")
    ladder = funding_maturity_ladder(filtered, as_of)
    ladder_plot, ladder_table = st.columns([1.1, .9], gap="large")
    with ladder_plot:
        fig = go.Figure()
        for col, name, color in [
            ("repo_eur", "Repo · cash borrowed", RED),
            ("reverse_eur", "Reverse repo · cash lent", "#B6A3A6"),
        ]:
            fig.add_trace(go.Bar(
                x=ladder["maturity_bucket"], y=ladder[col] / 1e6,
                name=name, marker_color=color,
                hovertemplate=f"%{{x}}<br>{name}: €%{{y:,.1f}}m<extra></extra>",
            ))
        fig = chart_style(fig, 278)
        fig.update_layout(
            barmode="stack", showlegend=True,
            legend=dict(orientation="h", y=-.28, x=0, font=dict(size=10)),
        )
        fig.update_yaxes(title="Gross cash (€m)", tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with ladder_table:
        ladder_view = ladder[["maturity_bucket", "trades", "gross_eur", "net_eur"]].copy()
        ladder_view.columns = ["Remaining tenor", "Trades", "Gross (€m)", "Net borrowing (€m)"]
        ladder_view["Gross (€m)"] = ladder_view["Gross (€m)"].map(lambda v: number(v / 1e6, 1))
        ladder_view["Net borrowing (€m)"] = ladder_view["Net borrowing (€m)"].map(lambda v: number(v / 1e6, 1, True))
        st.dataframe(ladder_view, use_container_width=True, hide_index=True)
        seven_day_gross = ladder.loc[ladder["maturity_bucket"].isin(["1 day", "2–7 days"]), "gross_eur"].sum()
        st.caption(f"**€{seven_day_gross / 1e6:,.1f}m** in gross repo/reverse-repo cash matures within 7 calendar days")

    st.markdown("#### Exposure & P&L breakdown")
    group_name = st.selectbox("Group by", ["Country", "Collateral", "Ticker", "Trader", "Side"], key="group_by")
    group_key = group_name.lower()
    grouped = grouped_portfolio(filtered, group_key)
    left, right = st.columns([1.15, 0.85], gap="large")
    with left:
        st.markdown("**Indicative P&L by group**")
        values = grouped.sort_values("pnl_eur")
        fig = go.Figure(go.Bar(
            x=values["pnl_eur"], y=values[group_key], orientation="h",
            marker_color=[RED if x >= 0 else "#837778" for x in values["pnl_eur"]],
            text=[eur(x, compact=True, signed=True) for x in values["pnl_eur"]],
            textposition="outside", cliponaxis=False,
            hovertemplate="%{y}<br>Sample P&L €%{x:,.0f}<extra></extra>",
        ))
        fig.update_xaxes(title="EUR", zeroline=True, zerolinecolor="#A7A19A")
        st.plotly_chart(chart_style(fig, 300), use_container_width=True, config={"displayModeBar": False})
    with right:
        st.markdown("**Gross cash allocation**")
        fig = go.Figure(go.Pie(
            labels=grouped[group_key], values=grouped["gross_eur"], hole=.66,
            marker=dict(colors=CHART_COLORS), textinfo="percent", textposition="outside",
            hovertemplate="%{label}: €%{value:,.0f}<extra></extra>",
        ))
        chart_style(fig, 300)
        fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-.2, x=0, font=dict(size=11)))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown("**Exposure breakdown**")
    exposure_view = grouped[[group_key, "trades", "gross_eur", "net_eur", "pnl_eur", "daily_carry_eur", "gross_weight_pct"]].copy()
    exposure_view.columns = [group_name, "Trades", "Gross (€m)", "Net (€m)", "P&L (€)", "Daily carry (€)", "Gross weight (%)"]
    exposure_view["Gross (€m)"] = exposure_view["Gross (€m)"].map(lambda v: number(v / 1e6, 2))
    exposure_view["Net (€m)"] = exposure_view["Net (€m)"].map(lambda v: number(v / 1e6, 2, True))
    exposure_view["P&L (€)"] = exposure_view["P&L (€)"].map(lambda v: number(v, 0, True))
    exposure_view["Daily carry (€)"] = exposure_view["Daily carry (€)"].map(lambda v: number(v, 2, True))
    exposure_view["Gross weight (%)"] = exposure_view["Gross weight (%)"].map(lambda v: f"{v:.1f}%")
    st.dataframe(exposure_view, hide_index=True, use_container_width=True)

    st.markdown("**Top 5 P&L contributors (selected active trades)**")
    top5 = filtered.nlargest(5, "pnl_eur")[["trade_id", "ticker", "country", "side", "cash_amount_eur", "pnl_eur", "gross_weight_pct"]].copy()
    top5.columns = ["Trade ID", "Ticker", "Country", "Side", "Gross (€m)", "P&L (€)", "Weight (%)"]
    top5["Gross (€m)"] = top5["Gross (€m)"].map(lambda v: number(v / 1e6, 2))
    top5["P&L (€)"] = top5["P&L (€)"].map(lambda v: number(v, 0, True))
    top5["Weight (%)"] = top5["Weight (%)"].map(lambda v: f"{v:.2f}%")
    st.dataframe(top5, hide_index=True, use_container_width=True)

    with st.expander("All trade-level positions and CSV export", expanded=False):
        view = filtered.sort_values("cash_amount_eur", ascending=False)[[
            "trade_id", "ticker", "trader", "country", "collateral", "side", "cash_amount_eur",
            "signed_cash_eur", "repo_rate_pct", "maturity_date", "gross_weight_pct", "pnl_eur", "daily_carry_eur"
        ]].copy()
        show = view.copy()
        show.columns = ["Trade ID", "Ticker", "Trader", "Country", "Collateral", "Side", "Cash (€m)",
                        "Signed (€m)", "Rate (%)", "Maturity", "Weight (%)", "Sample P&L (€)", "Daily carry (€)"]
        show["Cash (€m)"] = show["Cash (€m)"].map(lambda v: number(v / 1e6, 2))
        show["Signed (€m)"] = show["Signed (€m)"].map(lambda v: number(v / 1e6, 2, True))
        show["Rate (%)"] = show["Rate (%)"].map(lambda v: number(v, 3))
        show["Maturity"] = show["Maturity"].dt.strftime("%d %b %Y")
        show["Weight (%)"] = show["Weight (%)"].map(lambda v: f"{v:.2f}%")
        for key in ("Sample P&L (€)", "Daily carry (€)"):
            show[key] = show[key].map(lambda v: number(v, 2, True))
        st.dataframe(show, hide_index=True, use_container_width=True)
        st.download_button("Download selected trades (CSV)", view.to_csv(index=False).encode("utf-8"),
                           "repo_selected_trades.csv", "text/csv")
    note("<b>Method:</b> gross weights use absolute cash principals and sum to 100% within the selected positions. Repo = cash borrowed (+); reverse repo = cash lent (−)")


def render_repo_pricer() -> None:
    st.markdown("#### Secured funding · Repo pricer")
    st.caption("Simple-interest ACT/360 financing (no live curve, margin calls or pricing adjustments)")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        side = st.radio("Transaction side", ["Repo", "Reverse Repo"], horizontal=True, key="repo_side")
        cash_m = st.number_input("Cash principal (€ millions)", min_value=.001, max_value=10000., value=100., step=5., format="%.2f", key="repo_cash_m")
        rate = st.number_input("Annual repo rate (%)", min_value=-10., max_value=30., value=2.50, step=.05, format="%.3f", key="repo_rate")
    with c2:
        haircut = st.number_input("Illustrative collateral haircut (%)", min_value=0., max_value=50., value=2., step=.5, format="%.2f", key="haircut")
        start = st.date_input("Start date", value=SNAPSHOT, key="repo_start")
        end = st.date_input("Repurchase date", value=date(2026, 12, 7), key="repo_end")
    days = (end - start).days
    if days <= 0:
        st.warning("Repurchase date must be after the start date.")
        return
    cash = cash_m * 1e6
    interest = repo_interest(cash, rate, days)
    sign = -1 if side == "Repo" else 1
    opening = -sign * cash
    final = sign * (cash + interest)
    c1, c2, c3, c4 = st.columns(4, gap="small")
    c1.metric("ACT tenor", f"{days} days")
    c2.metric("Net interest cashflow", eur(sign * interest, signed=True))
    c3.metric("Maturity cashflow", eur(final, compact=True, signed=True))
    c4.metric("Indicative collateral", eur(cash / (1 - haircut / 100), compact=True))
    st.caption(f"Opening cashflow: {eur(opening, signed=True)} · Maturity cashflow: {eur(final, signed=True)} · Positive = cash received by the desk.")
    st.markdown("#### Funding rate sensitivity")
    scenario_visual(funding_scenarios(cash, rate, days, side), "Δ net interest (€)", "Interest sensitivity · ±50 bp")
    note("<b>Repo method:</b> interest = principal × annual rate × actual days / 360. A repo is cash borrowing against collateral; a reverse repo is cash lending. Collateral value = cash / (1 − haircut)")


def render_deposit_pricer() -> None:
    st.markdown("#### Unsecured funding · Money market deposit")
    a, b = st.columns(2, gap="large")
    with a:
        side = st.radio("Cash direction", ["Cash lending", "Cash borrowing"], horizontal=True, key="deposit_side")
        principal_m = st.number_input("Principal (€ millions)", min_value=.001, max_value=10000., value=50., step=5., format="%.2f", key="deposit_principal")
        rate = st.number_input("Annual deposit rate (%)", min_value=-10., max_value=30., value=2.60, step=.05, format="%.3f", key="deposit_rate")
    with b:
        st.caption("ACT/360 · EUR · illustrative fixed-rate unsecured deposit")
        start = st.date_input("Value date", value=SNAPSHOT, key="deposit_start")
        end = st.date_input("Maturity date", value=date(2026, 12, 23), key="deposit_end")
    days = (end - start).days
    if days <= 0:
        st.warning("Maturity date must be after value date.")
        return
    principal = principal_m * 1e6
    result = cash_deposit_pricing(principal, rate, days, side)
    c1, c2, c3, c4 = st.columns(4, gap="small")
    c1.metric("ACT tenor", f"{days} days")
    c2.metric("Gross interest", eur(result["gross_interest_eur"]))
    c3.metric("Net interest cashflow", eur(result["signed_interest_eur"], signed=True))
    c4.metric("Maturity cashflow", eur(result["maturity_cashflow_eur"], compact=True, signed=True))
    st.caption(f"Initial cashflow: {eur(result['opening_cashflow_eur'], signed=True)} · Maturity cashflow: {eur(result['maturity_cashflow_eur'], signed=True)} · Positive = cash received.")
    st.markdown("#### Deposit rate sensitivity")
    scenario_visual(deposit_scenarios(principal, rate, days, side), "Δ net interest (€)", "Deposit interest sensitivity · ±50 bp")
    note("<b>Deposit method:</b> interest = principal × annual rate × actual days / 360. Cash lending pays the principal today and receives principal plus interest at maturity; cash borrowing reverses these flows")


def render_funding_tab() -> None:
    st.subheader("Cash funding pricers")
    secured, unsecured = st.tabs(["Secured · Repo", "Unsecured · Money market deposit"])
    with secured:
        render_repo_pricer()
    with unsecured:
        render_deposit_pricer()


@st.cache_data(ttl=21600)
def get_ecb_rates():
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    with urlopen(url, timeout=8) as response:
        root = ET.fromstring(response.read())

    rates = {}
    fixing_date = None

    for element in root.iter():
        if "time" in element.attrib:
            fixing_date = element.attrib["time"]

        if "currency" in element.attrib:
            rates[element.attrib["currency"]] = float(
                element.attrib["rate"])

    if not fixing_date or not all(
        ccy in rates for ccy in ["USD", "GBP", "CHF", "JPY"]
    ):
        raise ValueError("Missing ECB exchange rates")

    return fixing_date, rates



def render_fx_swap() -> None:

    st.subheader("FX Swap Pricer")
    st.caption("FX spot references and theoretical forward pricing")

    # Four currencies, each available in both directions
    currencies = ["USD", "GBP", "CHF", "JPY"]
    pairs = (
        [f"EUR/{ccy}" for ccy in currencies]
        + [f"{ccy}/EUR" for ccy in currencies])

    # Get ECB reference rates
    try:
        fixing_date, ecb_rates = get_ecb_rates()
        source = "ECB"
    except Exception:
        fixing_date = None
        source = "Sample"
        ecb_rates = {
            "USD": 1.08,
            "GBP": 0.85,
            "CHF": 0.93,
            "JPY": 170.00}

    pair = st.selectbox("Currency pair", pairs, key="fx_pair")
    base, quote_ccy = pair.split("/")

    # ECB provides one unit of EUR in foreign currency
    foreign = quote_ccy if base == "EUR" else base
    eur_spot = ecb_rates[foreign]

    spot_reference = (
        eur_spot if base == "EUR"
        else 1 / eur_spot)

    # Illustrative funding rates
    rate_defaults = {
        "EUR": 2.50,
        "USD": 4.00,
        "GBP": 3.75,
        "CHF": 1.00,
        "JPY": 0.75}

    # Simplified currency day-count conventions
    day_count = {
        "EUR": 360,
        "USD": 360,
        "GBP": 365,
        "CHF": 360,
        "JPY": 360}

    # Reset inputs when the currency pair or ECB fixing changes
    selection = (pair, fixing_date)

    if st.session_state.get("fx_last_selection") != selection:
        st.session_state["fx_spot"] = spot_reference
        st.session_state["fx_base_rate"] = rate_defaults[base]
        st.session_state["fx_quote_rate"] = rate_defaults[quote_ccy]
        st.session_state["fx_last_selection"] = selection

    if source == "ECB":
        st.caption(
            f"ECB reference spot: {fixing_date} · ")
    else:
        st.warning(
            "ECB data unavailable: sample spot values are used. "
            "They can be changed manually")


     # Default settlement dates based on ECB fixing
    reference_day = (
        date.fromisoformat(fixing_date)
        if fixing_date else date.today())
    
    near_default = (
        pd.Timestamp(reference_day) + pd.offsets.BDay(2)).date()

    far_default = (
        pd.Timestamp(near_default) + pd.DateOffset(months=3)
    ).date()
    
    left, right = st.columns(2, gap="large")

    with left:
        direction = st.radio(
            "Near leg direction",
            ["Buy base near", "Sell base near"],
            format_func=lambda x: x.replace("base", base),
            horizontal=True,
            key="fx_side")

        notional_m = st.number_input(
            f"{base} notional ({base} millions)",
            min_value=0.001,
            max_value=10000.0,
            value=10.0,
            step=1.0,
            key="fx_notional")

        spot_decimals = 7 if base == "JPY" else (
            3 if quote_ccy == "JPY" else 5)

        spot = st.number_input(
            f"Spot {pair} ({quote_ccy} per {base})",
            min_value=0.0000001,
            max_value=1000000.0,
            step=0.000001 if base == "JPY" else (
                0.01 if quote_ccy == "JPY" else 0.0001
            ),
            format=f"%.{spot_decimals}f",
            key="fx_spot")

        base_rate = st.number_input(
            f"{base} money market rate (%)",
            min_value=-20.0,
            max_value=30.0,
            step=0.05,
            format="%.3f",
            key="fx_base_rate")

    with right:
        quote_rate = st.number_input(
            f"{quote_ccy} money market rate (%)",
            min_value=-20.0,
            max_value=30.0,
            step=0.05,
            format="%.3f",
            key="fx_quote_rate")

        near = st.date_input(
            "Near settlement date",
            value=near_default,
            key="fx_near_date")

        far = st.date_input(
            "Far settlement date",
            value=far_default,
            key="fx_far_date")

    days = (far - near).days

    if days <= 0:
        st.warning("Far date must be after near date.")
        return

    # Theoretical forward from covered-interest parity
    def forward_price(r_base, r_quote):
        factor_base = (
            1 + r_base / 100 * days / day_count[base])
        factor_quote = (
            1 + r_quote / 100 * days / day_count[quote_ccy])

        if factor_base <= 0 or factor_quote <= 0:
            raise ValueError("Invalid interest-rate factors")

        return spot * factor_quote / factor_base

    try:
        forward = forward_price(base_rate, quote_rate)
    except ValueError as exc:
        st.error(str(exc))
        return

    # Display convention: JPY-quoted pairs use 0.01,
    # other pairs use 0.0001 per pip.
    pip_size = 0.01 if quote_ccy == "JPY" else 0.0001
    swap_points = (forward - spot) / pip_size

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("ACT tenor", f"{days} days")
    c2.metric(
        f"Forward {pair}",
        f"{forward:.{spot_decimals}f}")
    c3.metric("Swap points", f"{swap_points:+.2f} pips")
    c4.metric(
        f"{quote_ccy} − {base} rates",
        f"{quote_rate - base_rate:+.2f} pp")

    notional = notional_m * 1e6
    direction_sign = 1 if direction == "Buy base near" else -1

    cashflows = pd.DataFrame({
        "Leg": ["Near / Spot", "Far / Forward"],
        f"{base} cashflow": [
            direction_sign * notional,
            -direction_sign * notional
        ],
        f"{quote_ccy} cashflow": [
            -direction_sign * notional * spot,
            direction_sign * notional * forward
        ]
    })

    st.markdown("#### Near and far contractual cashflows")

    display_flows = cashflows.copy()

    for ccy in [base, quote_ccy]:
        col = f"{ccy} cashflow"
        display_flows[col] = display_flows[col].map(
            lambda x: f"{x:+,.2f}")

    st.dataframe(
        display_flows,
        hide_index=True,
        use_container_width=True)

    # Funding rate sensitivity
    st.markdown("#### What moves the forward points?")

    if st.session_state.get("fx_shock_ccy") not in [base, quote_ccy]:
        st.session_state["fx_shock_ccy"] = quote_ccy

    shocked_ccy = st.selectbox(
        "Shock the money market rate",
        [quote_ccy, base],
        key="fx_shock_ccy")

    scenarios = []

    for shock in [-50, -25, 0, 25, 50]:
        rb = base_rate
        rq = quote_rate

        if shocked_ccy == base:
            rb += shock / 100
        else:
            rq += shock / 100

        new_forward = forward_price(rb, rq)
        new_points = (new_forward - spot) / pip_size

        scenarios.append({
            "Shock (bp)": shock,
            "Forward": new_forward,
            "Points (pips)": new_points,
            "Delta points": new_points - swap_points
        })

    scenarios = pd.DataFrame(scenarios)

    chart_col, table_col = st.columns([1, 1.05])

    with chart_col:
        st.markdown(f"**{shocked_ccy} rate shocks · ±50 bp**")

        fig = go.Figure(go.Scatter(
            x=scenarios["Shock (bp)"],
            y=scenarios["Points (pips)"],
            mode="lines+markers",
            line=dict(color=RED, width=3),
            marker=dict(color=RED, size=8)))

        fig.update_xaxes(
            title=f"{shocked_ccy} rate shock (bp)")
        fig.update_yaxes(title="Swap points (pips)")

        st.plotly_chart(
            chart_style(fig),
            use_container_width=True,
            config={"displayModeBar": False})

    with table_col:
        st.markdown("**Forward sensitivity table**")

        view = scenarios.copy()
        view["Forward"] = view["Forward"].map(
            lambda v: f"{v:.{spot_decimals}f}")
        view["Points (pips)"] = view["Points (pips)"].map(
            lambda v: f"{v:+.2f}")
        view["Delta points"] = view["Delta points"].map(
            lambda v: f"{v:+.2f}")

        st.dataframe(
            view,
            hide_index=True,
            use_container_width=True)


    note(
        "<b>FX method:</b> Theoretical forward based on simple interest-rate parity. "
        "Funding curves, bid-ask spreads and cross-currency basis are excluded")



def readable_recon(df: pd.DataFrame) -> pd.DataFrame:
    """Readable on-screen values; preserve original numeric CSV for download."""
    cols = ["trade_id", "status", "pnl_eur_fo", "pnl_eur_pc", "pnl_diff_eur", "signed_cash_eur_fo", "signed_cash_eur_pc", "cash_diff_eur"]
    view = df[cols].copy().rename(columns={
        "trade_id": "Trade ID", "status": "Status",
        "pnl_eur_fo": "FO P&L (€)", "pnl_eur_pc": "PC P&L (€)",
        "pnl_diff_eur": "P&L diff (€)",
        "signed_cash_eur_fo": "FO cash (€m)", "signed_cash_eur_pc": "PC cash (€m)",
        "cash_diff_eur": "Cash diff (€)",
    })
    for c in ("FO P&L (€)", "PC P&L (€)", "P&L diff (€)", "Cash diff (€)"):
        view[c] = view[c].map(lambda v: number(v, 2, True) if pd.notna(v) else "—")
    for c in ("FO cash (€m)", "PC cash (€m)"):
        view[c] = view[c].map(lambda v: number(v / 1e6, 3, True) if pd.notna(v) else "—")
    return view


def render_reconciliation() -> None:
    st.subheader("Daily FO / Product Control reconciliation")
    st.caption("Trade-level comparison of synthetic FO and Product Control files — fixed snapshot: 23 Nov 2026.")
    with st.expander("Import custom Front Office / Product Control CSVs · optional", expanded=False):
        l, r = st.columns(2)
        with l:
            fo_upload = st.file_uploader("Front Office ledger", type=["csv"], key="recon_fo")
        with r:
            pc_upload = st.file_uploader("Product Control ledger", type=["csv"], key="recon_pc")
        st.caption("Without uploads, both synthetic CSV examples are loaded automatically.")
    l, r = st.columns(2)
    with l:
        pnl_tol = st.number_input("P&L break tolerance (€)", min_value=0., value=1., step=1., key="pnl_tol")
    with r:
        cash_tol = st.number_input("Cash break tolerance (€)", min_value=0., value=1., step=1., key="cash_tol")
    try:
        fo = pd.read_csv(fo_upload if fo_upload is not None else DATA / "front_office_v2.csv")
        pc = pd.read_csv(pc_upload if pc_upload is not None else DATA / "product_control_v2.csv")
        result = reconcile(fo, pc, pnl_tol, cash_tol)
    except (ValueError, KeyError, TypeError, pd.errors.ParserError) as exc:
        st.error(f"Ledger reconciliation failed: {exc}")
        return
    total = len(result)
    n_match = int(result["status"].eq("Matched").sum())
    n_break = int(result["status"].str.contains("break").sum())
    n_missing = int(result["status"].str.startswith("Missing").sum())
    k1, k2, k3, k4, k5 = st.columns(5, gap="small")
    k1.metric("Unique trade IDs", total)
    k2.metric("Matched", n_match)
    k3.metric("Match rate", f"{n_match / total * 100:.1f}%" if total else "—")
    k4.metric("Value breaks", n_break)
    k5.metric("Missing trades", n_missing)
    exceptions = result.loc[result["status"] != "Matched"]
    st.markdown(
        f"#### Exceptions requiring investigation ({len(exceptions)})")
    
    if exceptions.empty:
        st.success("All trades match within the selected tolerances.")
    else:
        st.dataframe(readable_recon(exceptions), hide_index=True, use_container_width=True)
    with st.expander(f"Full reconciliation · {total} trade IDs", expanded=False):
        st.dataframe(readable_recon(result), hide_index=True, use_container_width=True)
    l, r = st.columns(2)
    with l:
        st.download_button("Download full reconciliation (CSV)",
                           result.drop(columns=["_merge"]).to_csv(index=False).encode("utf-8"),
                           "reconciliation_full.csv", "text/csv", use_container_width=True)
    with r:
        st.download_button("Download exceptions only (CSV)",
                           exceptions.drop(columns=["_merge"]).to_csv(index=False).encode("utf-8"),
                           "reconciliation_exceptions.csv", "text/csv", use_container_width=True)
    note("<b>Scope:</b> this is a simplified trade-level reconciliation via a full outer merge on unique trade ID. It identifies missing records and compares supplied P&L/signed cash balances with EUR tolerances")


st.sidebar.markdown('<div class="brand"> Desk <span>/</span> Cash Financing Solution Repo</div>', unsafe_allow_html=True)
st.sidebar.caption("Personal Python project")
st.sidebar.divider()
st.sidebar.markdown("**Inside the tool**")
st.sidebar.caption("Portfolio · Cash funding · FX swaps · Controls")
st.sidebar.markdown(
    """
    <div class="sidebar-note">
        • Synthetic trading data & illustrative pricing<br>
        • Official ECB FX reference rates
    </div>
    """,
    unsafe_allow_html=True)
st.sidebar.divider()
st.sidebar.markdown(
    """
    <div style="
        margin-top: 35vh;
        font-size: 26px;
        font-weight: 700;
        color: #77716E;
    ">
        Mathieu Voluntario
    </div>
    """,
    unsafe_allow_html=True)

st.markdown("""
<div class="hero">
 <h1>Repo &amp; Funding Analytics</h1>
 <p>Portfolio monitoring · Funding pricers · Daily reconciliation</p>
 <div class="disclaimer">Simulated transactions</div>
</div>
""", unsafe_allow_html=True)

portfolio_tab, funding_tab, fx_tab, reconciliation_tab = st.tabs([
    "01   Portfolio & P&L", "02   Cash Funding Pricers", "03   FX Swap Pricer", "04   Daily Reconciliation"
])
with portfolio_tab:
    render_portfolio()
with funding_tab:
    render_funding_tab()
with fx_tab:
    render_fx_swap()
with reconciliation_tab:
    render_reconciliation()
