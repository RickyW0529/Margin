#!/usr/bin/env python3
"""DB-only monthly backtest for CSI300, All-A, and CSI500 quant pools."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from margin.settings import MarginSettings
from margin.sql.backtest_queries import (
    company_pool_members as company_pool_members_sql,
)
from margin.sql.backtest_queries import (
    company_pool_snapshots as company_pool_snapshots_sql,
)
from margin.sql.backtest_queries import (
    coverage_by_endpoint,
    coverage_by_index_code,
    daily_basic_facts,
    index_weight_members,
    market_panel_facts,
    security_names_active,
)
from margin.valuation_discovery.quant.manual_all_a import (
    ManualAllAConfig,
    score_manual_all_a,
)
from margin.valuation_discovery.quant.pool_defaults import DEFAULT_QUANT_POOL_PRESETS
from margin.valuation_discovery.quant.theme_tilt import (
    ThemeSignalConfig,
    confirmation_states,
    score_theme_components,
)

MARKET_FEATURE_DAYS = 260
VALUATION_INDICATORS = (
    "pe_ttm",
    "pb",
    "ps",
    "dividend_yield",
    "market_cap",
    "turnover_rate",
)
MARKET_INDICATORS = ("close", "amount", "adj_factor")
INDEX_CODES = {"CSI300": "000300.SH", "CSI500": "000905.SH"}
MAX_ABS_DAILY_RETURN = 0.35
THEME_CODE = "optical_module_cpo"
THEME_NAME = "光模块/CPO"
THEME_SOURCE = "curated_seed_v20260624_akshare_unavailable"
THEME_SIGNAL_CONFIG = ThemeSignalConfig(
    entry_score=70.0,
    entry_confirmation_periods=2,
    exit_score=55.0,
    exit_confirmation_periods=2,
)
THEME_MEMBERS: dict[str, float] = {
    "300308.SZ": 1.00,
    "300502.SZ": 1.00,
    "300394.SZ": 1.00,
    "002281.SZ": 0.95,
    "300570.SZ": 0.90,
    "301205.SZ": 0.90,
    "603083.SH": 0.90,
    "300548.SZ": 0.90,
    "300620.SZ": 0.85,
    "688498.SH": 0.85,
    "688205.SH": 0.80,
    "000988.SZ": 0.75,
    "688195.SH": 0.75,
    "688048.SH": 0.75,
    "002902.SZ": 0.65,
    "000063.SZ": 0.60,
    "300913.SZ": 0.55,
    "603118.SH": 0.50,
    "600522.SH": 0.45,
    "600105.SH": 0.45,
    "300757.SZ": 0.40,
    "300710.SZ": 0.35,
    "300615.SZ": 0.30,
}


def main(argv: list[str] | None = None) -> int:
    """Run the DB-only monthly backtest for CSI300, All-A and CSI500 pools.

    Args:
        argv: Optional argument list. When ``None``, arguments are read from
            ``sys.argv``.

    Returns:
        int: 0 on success.

    Raises:
        SystemExit: When no rebalance dates are available from DB market data.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2024-06-24")
    parser.add_argument("--end-date", default="2026-06-23")
    parser.add_argument("--output-dir", default="backtest_output_three_pools_db")
    parser.add_argument("--cost-bps", default="20,50,100,150,200")
    parser.add_argument(
        "--theme-mode",
        choices=("enabled", "disabled"),
        default="enabled",
        help="Enable or disable the additive theme-hotness factor.",
    )
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    costs = tuple(int(item.strip()) for item in args.cost_bps.split(",") if item.strip())
    theme_enabled = args.theme_mode == "enabled"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(str(MarginSettings().database_url))
    try:
        coverage = inspect_coverage(engine, start=start, end=end)
        prices = load_market_panels(engine, start=start - timedelta(days=420), end=end)
        daily_basic = load_daily_basic(engine, start=start, end=end)
        company_pools = load_company_pool_snapshots(engine)
        index_members = load_index_members(engine, start=start - timedelta(days=45), end=end)
        security_names = load_security_names(engine)
    finally:
        engine.dispose()

    coverage["loaded"] = {
        "market_rows": int(len(prices["long"])),
        "daily_basic_rows": int(len(daily_basic)),
        "company_pool_snapshots": int(len(company_pools["snapshots"])),
        "index_member_dates": {
            code: int(len(values)) for code, values in index_members.items()
        },
    }
    (output_dir / "data_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    rebalance_dates = month_end_dates(prices["adj_close"].index, start=start, end=end)
    if not rebalance_dates:
        raise SystemExit("No rebalance dates available from DB market data.")
    theme_signals = build_theme_signals(prices, rebalance_dates) if theme_enabled else {}
    coverage["loaded"]["theme"] = {
        "enabled": theme_enabled,
        "code": THEME_CODE,
        "name": THEME_NAME,
        "source": THEME_SOURCE if theme_enabled else "disabled",
        "seed_members": len(THEME_MEMBERS),
        "matched_members": int(
            len(set(THEME_MEMBERS) & set(prices["adj_close"].columns.astype(str)))
        ),
        "signals": len(theme_signals),
    }
    pd.DataFrame(theme_signals.values()).to_csv(
        output_dir / "theme_signals_optical_module_cpo.csv",
        index=False,
    )
    (output_dir / "data_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    all_rows: list[dict[str, Any]] = []
    default_rows: list[dict[str, Any]] = []
    for pool_code in ("CSI300", "ALL_A", "CSI500"):
        for cost_bps in costs:
            result = run_pool_backtest(
                pool_code=pool_code,
                cost_bps=cost_bps,
                rebalance_dates=rebalance_dates,
                prices=prices,
                daily_basic=daily_basic,
                company_pools=company_pools,
                index_members=index_members,
                security_names=security_names,
                theme_signals=theme_signals,
                theme_enabled=theme_enabled,
            )
            all_rows.append(result["summary"])
            if cost_bps == 100:
                default_rows.append(result["summary"])
                prefix = pool_code.lower()
                result["nav"].to_csv(
                    output_dir / f"{prefix}_nav_100bps.csv",
                    index=False,
                )
                result["trades"].to_csv(
                    output_dir / f"{prefix}_trades_100bps.csv",
                    index=False,
                )
                result["latest_candidates"].to_csv(
                    output_dir / f"{prefix}_latest_candidates_100bps.csv",
                    index=False,
                )

    summary = pd.DataFrame(all_rows)
    defaults = pd.DataFrame(default_rows)
    summary.to_csv(output_dir / "three_pool_db_backtest_summary.csv", index=False)
    defaults.to_csv(
        output_dir / "three_pool_db_backtest_defaults_100bps.csv",
        index=False,
    )
    print(
        json.dumps(
            {"output_dir": str(output_dir), "defaults": default_rows},
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


def inspect_coverage(engine, *, start: date, end: date) -> dict[str, Any]:
    """Inspect DB data coverage for the requested backtest window.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.
        start: Backtest start date.
        end: Backtest end date.

    Returns:
        dict[str, Any]: Coverage report with per-endpoint and per-index stats
            plus data warnings.
    """
    with engine.connect() as conn:
        endpoint_rows = conn.execute(coverage_by_endpoint()).mappings().all()
        index_rows = conn.execute(coverage_by_index_code()).mappings().all()
    by_endpoint = [dict(row) for row in endpoint_rows]
    by_index = [dict(row) for row in index_rows]
    daily_basic_min = min(
        (row["min_date"] for row in by_endpoint if row["endpoint_code"] == "daily_basic"),
        default=None,
    )
    return {
        "requested_window": {"start": start.isoformat(), "end": end.isoformat()},
        "by_endpoint_indicator": by_endpoint,
        "index_weight_by_index_code": by_index,
        "db_only": True,
        "csv_fallback_used": False,
        "data_warnings": [
            warning
            for warning in (
                (
                    f"daily_basic starts at {daily_basic_min}; requested {start}"
                    if daily_basic_min is not None and daily_basic_min > start
                    else None
                ),
                (
                    "CSI500 index_weight with json index_code is missing"
                    if not any(row.get("index_code") == "000905.SH" for row in by_index)
                    else None
                ),
                (
                    "CSI300 index_weight with json index_code is missing"
                    if not any(row.get("index_code") == "000300.SH" for row in by_index)
                    else None
                ),
            )
            if warning
        ],
    }


def load_market_panels(engine, *, start: date, end: date) -> dict[str, Any]:
    """Load market panel facts and derive price, return and feature panels.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.
        start: Panel start date (lookback-extended before backtest start).
        end: Panel end date.

    Returns:
        dict[str, Any]: Dict with long frame, close, amount, adj_close,
            returns and computed feature panels.

    Raises:
        SystemExit: When the DB market facts frame is empty.
    """
    frame = pd.read_sql_query(
        market_panel_facts(),
        engine,
        params={
            "indicators": list(MARKET_INDICATORS),
            "start_date": start,
            "end_date": end,
        },
    )
    if frame.empty:
        raise SystemExit("DB market facts are empty for requested window.")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    close = pivot_indicator(frame, "close")
    amount = pivot_indicator(frame, "amount")
    adj_factor = (
        pivot_indicator(frame, "adj_factor")
        .reindex_like(close)
        .ffill()
        .fillna(1.0)
    )
    # Pandas DataFrame arithmetic can align unexpectedly when large sparse
    # panels carry the same axis names. Use explicit elementwise arrays.
    adj_close = pd.DataFrame(
        close.to_numpy(dtype=float) * adj_factor.to_numpy(dtype=float),
        index=close.index,
        columns=close.columns,
    )
    daily_returns = adj_close.pct_change(fill_method=None).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    daily_returns = daily_returns.where(
        daily_returns.abs() <= MAX_ABS_DAILY_RETURN,
    )
    avg_amount_20d = amount.rolling(20, min_periods=10).mean()
    rolling_amount = avg_amount_20d.replace(0, np.nan)
    volume_ratio = amount / rolling_amount
    features = {
        "return_20d": adj_close / adj_close.shift(20) - 1,
        "return_6m_ex_1m": adj_close.shift(21) / adj_close.shift(126) - 1,
        "volatility_120d": daily_returns.rolling(120, min_periods=40).std()
        * math.sqrt(252),
        "max_drawdown_250d": adj_close
        / adj_close.rolling(250, min_periods=60).max()
        - 1,
        "avg_amount_20d": avg_amount_20d,
        "volume_ratio": volume_ratio,
    }
    return {
        "long": frame,
        "close": close,
        "amount": amount,
        "adj_close": adj_close,
        "returns": daily_returns,
        "features": features,
    }


def pivot_indicator(frame: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Pivot a long indicator frame into a date-by-security wide table.

    Args:
        frame: Long-format DataFrame with indicator_id column.
        indicator: Indicator name to filter on.

    Returns:
        pd.DataFrame: Pivoted table indexed by trade_date, columns by
            security_id.
    """
    part = frame.loc[frame["indicator_id"] == indicator]
    return part.pivot_table(
        index="trade_date",
        columns="security_id",
        values="value",
        aggfunc="last",
    ).sort_index()


def load_daily_basic(engine, *, start: date, end: date) -> pd.DataFrame:
    """Load daily basic valuation facts and pivot into a wide frame.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.
        start: Query start date.
        end: Query end date.

    Returns:
        pd.DataFrame: Pivoted daily basic frame indexed by trade_date and
            security_id, or an empty frame when no rows exist.
    """
    frame = pd.read_sql_query(
        daily_basic_facts(),
        engine,
        params={"indicators": list(VALUATION_INDICATORS), "start_date": start, "end_date": end},
    )
    if frame.empty:
        return frame
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.pivot_table(
        index=["trade_date", "security_id"],
        columns="indicator_id",
        values="value",
        aggfunc="last",
    ).reset_index()


def load_index_members(
    engine,
    *,
    start: date,
    end: date,
) -> dict[str, dict[pd.Timestamp, set[str]]]:
    """Load index weight members grouped by index code and trade date.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.
        start: Query start date.
        end: Query end date.

    Returns:
        dict[str, dict[pd.Timestamp, set[str]]]: Mapping from index code to
            trade-date to set of member security IDs.
    """
    frame = pd.read_sql_query(
        index_weight_members(),
        engine,
        params={
            "start_date": start,
            "end_date": end,
            "index_codes": list(INDEX_CODES.values()),
        },
    )
    result = {code: {} for code in INDEX_CODES.values()}
    if frame.empty:
        return result
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    for (index_code, trade_date), group in frame.groupby(["index_code", "trade_date"]):
        result.setdefault(index_code, {})[trade_date] = set(group["security_id"].astype(str))
    return result


def load_company_pool_snapshots(engine) -> dict[str, Any]:
    """Load company pool snapshots and their member security ID sets.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.

    Returns:
        dict[str, Any]: Dict with snapshots DataFrame and members mapping
            from snapshot_id to security ID set.
    """
    snapshots = pd.read_sql_query(
        company_pool_snapshots_sql(),
        engine,
    )
    members = pd.read_sql_query(
        company_pool_members_sql(),
        engine,
    )
    if not snapshots.empty:
        snapshots["business_at"] = pd.to_datetime(snapshots["business_at"]).dt.tz_localize(None)
    member_map = {
        snapshot_id: set(group["security_id"].astype(str))
        for snapshot_id, group in members.groupby("snapshot_id")
    } if not members.empty else {}
    return {"snapshots": snapshots, "members": member_map}


def load_security_names(engine) -> dict[str, str]:
    """Load active security ID to name mapping.

    Args:
        engine: SQLAlchemy engine connected to the warehouse.

    Returns:
        dict[str, str]: Mapping from security ID to display name.
    """
    frame = pd.read_sql_query(
        security_names_active(),
        engine,
    )
    return dict(zip(frame["security_id"].astype(str), frame["name"].astype(str), strict=False))


def month_end_dates(index: pd.DatetimeIndex, *, start: date, end: date) -> list[pd.Timestamp]:
    """Extract month-end rebalance dates within the requested window.

    Args:
        index: DatetimeIndex of available trading dates.
        start: Window start date.
        end: Window end date.

    Returns:
        list[pd.Timestamp]: Sorted list of last trading day per month.
    """
    dates = pd.DatetimeIndex(index).sort_values().unique()
    dates = dates[(dates.date >= start) & (dates.date <= end)]
    if dates.empty:
        return []
    grouped = pd.Series(dates, index=dates).groupby(dates.to_period("M")).max()
    return list(pd.DatetimeIndex(grouped.values).sort_values())


def run_pool_backtest(
    *,
    pool_code: str,
    cost_bps: int,
    rebalance_dates: list[pd.Timestamp],
    prices: dict[str, Any],
    daily_basic: pd.DataFrame,
    company_pools: dict[str, Any],
    index_members: dict[str, dict[pd.Timestamp, set[str]]],
    security_names: dict[str, str],
    theme_signals: dict[pd.Timestamp, dict[str, Any]],
    theme_enabled: bool = True,
) -> dict[str, Any]:
    """Run a single pool backtest at a given cost level.

    Args:
        pool_code: Pool identifier (CSI300, ALL_A, CSI500).
        cost_bps: Round-trip transaction cost in basis points.
        rebalance_dates: Monthly rebalance timestamps.
        prices: Market panel dict from load_market_panels.
        daily_basic: Daily valuation frame from load_daily_basic.
        company_pools: Company pool snapshots from load_company_pool_snapshots.
        index_members: Index members from load_index_members.
        security_names: Security ID to name mapping.
        theme_signals: Theme hotness signals keyed by date.
        theme_enabled: Whether the theme factor is active.

    Returns:
        dict[str, Any]: Dict with summary, nav, trades and latest_candidates
            DataFrames.
    """
    preset = DEFAULT_QUANT_POOL_PRESETS[pool_code]
    config = ManualAllAConfig(
        score_threshold=preset.buy_threshold,
        min_avg_amount_20d=preset.min_avg_amount_20d,
        weights=theme_adjusted_weights(
            preset.factor_weights,
            theme_enabled=theme_enabled,
        ),
    )
    manual_policy = preset.candidate_policy.get("manual_rebalance", {})
    min_holding_months = int(manual_policy.get("min_holding_months", 0))
    selected_weights: dict[str, float] = {}
    holding_months: dict[str, int] = {}
    nav = 1.0
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    latest_candidates = pd.DataFrame()
    total_turnover = 0.0
    skipped_rebalances = 0
    data_notes: list[str] = []

    daily_basic_sorted = (
        daily_basic.sort_values(["trade_date", "security_id"])
        if not daily_basic.empty
        else daily_basic
    )
    for idx, rebalance_date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[idx + 1]
        period_index = prices["returns"].index[
            (prices["returns"].index > rebalance_date)
            & (prices["returns"].index <= next_date)
        ]
        universe = universe_for_date(
            pool_code,
            rebalance_date,
            prices=prices,
            company_pools=company_pools,
            index_members=index_members,
        )
        if not universe:
            skipped_rebalances += 1
            data_notes.append(f"{pool_code}:{rebalance_date.date()}:empty_universe")
        else:
            frame = feature_frame_for_date(
                rebalance_date,
                universe=universe,
                prices=prices,
                daily_basic=daily_basic_sorted,
                security_names=security_names,
                theme_signals=theme_signals if theme_enabled else {},
            )
            if frame.empty:
                skipped_rebalances += 1
                data_notes.append(f"{pool_code}:{rebalance_date.date()}:empty_features")
            else:
                scored = score_manual_all_a(frame, config=config)
                scored["keep_candidate"] = (
                    scored["manual_all_a_score"] >= preset.sell_threshold
                )
                keep_ids = set(
                    scored.loc[scored["keep_candidate"], "security_id"].astype(str)
                )
                scored_ids = set(scored["security_id"].astype(str))
                protected_ids = {
                    sid
                    for sid, months in holding_months.items()
                    if months < min_holding_months and sid in scored_ids
                }
                keep_ids |= protected_ids
                current_kept = {sid for sid in selected_weights if sid in keep_ids}
                buys = set(
                    scored.loc[scored["manual_all_a_candidate"], "security_id"].astype(
                        str
                    )
                )
                target_ids = sorted(current_kept | buys)
                target_weights = target_weight_map(
                    scored,
                    target_ids,
                    preset.weighting,
                    preset.sell_threshold,
                )
                turnover = sum(
                    abs(
                        target_weights.get(sid, 0.0)
                        - selected_weights.get(sid, 0.0)
                    )
                    for sid in set(target_weights) | set(selected_weights)
                )
                total_turnover += turnover
                nav *= max(0.0, 1.0 - turnover * cost_bps / 10_000.0)
                trade_rows.append(
                    {
                        "date": rebalance_date.date().isoformat(),
                        "pool": pool_code,
                        "cost_bps": cost_bps,
                        "turnover": turnover,
                        "holdings": len(target_weights),
                        "candidate_count": int(
                            scored["manual_all_a_candidate"].sum()
                        ),
                        "theme_hot_score": _theme_signal_value(
                            theme_signals,
                            rebalance_date,
                            "theme_hot_score",
                        ),
                        "theme_signal_confirmed": _theme_signal_value(
                            theme_signals,
                            rebalance_date,
                            "theme_signal_confirmed",
                        ),
                        "min_holding_months": min_holding_months,
                        "nav_after_cost": nav,
                    }
                )
                selected_weights = target_weights
                holding_months = {
                    sid: holding_months.get(sid, 0) + 1
                    for sid in selected_weights
                }
                latest_candidates = scored.assign(
                    date=rebalance_date.date().isoformat(),
                    name=scored["security_id"].map(security_names),
                )
        if selected_weights:
            period_returns = prices["returns"].reindex(
                index=period_index,
                columns=list(selected_weights.keys()),
            )
            weights = pd.Series(selected_weights)
            daily_period_returns = period_returns.fillna(0.0).mul(weights).sum(axis=1)
        else:
            daily_period_returns = pd.Series(0.0, index=period_index)
        for trade_date, day_ret_value in daily_period_returns.items():
            day_ret = float(day_ret_value)
            nav *= 1.0 + day_ret
            nav_rows.append(
                {
                    "date": trade_date.date().isoformat(),
                    "pool": pool_code,
                    "cost_bps": cost_bps,
                    "nav": nav,
                    "daily_return": day_ret,
                    "holdings": len(selected_weights),
                }
            )
    nav_frame = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    summary = summarize_backtest(
        pool_code=pool_code,
        preset=preset,
        cost_bps=cost_bps,
        nav_frame=nav_frame,
        trades=trades,
        total_turnover=total_turnover,
        skipped_rebalances=skipped_rebalances,
        data_notes=data_notes,
        theme_enabled=theme_enabled,
    )
    return {
        "summary": summary,
        "nav": nav_frame,
        "trades": trades,
        "latest_candidates": latest_candidates,
    }


def universe_for_date(
    pool_code: str,
    rebalance_date: pd.Timestamp,
    *,
    prices: dict[str, Any],
    company_pools: dict[str, Any],
    index_members: dict[str, dict[pd.Timestamp, set[str]]],
) -> set[str]:
    """Resolve the investable universe for a pool at a rebalance date.

    Args:
        pool_code: Pool identifier (CSI300, ALL_A, CSI500).
        rebalance_date: PIT rebalance timestamp.
        prices: Market panel dict from load_market_panels.
        company_pools: Company pool snapshots from load_company_pool_snapshots.
        index_members: Index members from load_index_members.

    Returns:
        set[str]: Set of security IDs in the universe, or an empty set when
            no index members are available before the date.
    """
    if pool_code == "ALL_A":
        snapshots = company_pools["snapshots"]
        if not snapshots.empty:
            eligible = snapshots.loc[snapshots["business_at"] <= rebalance_date]
            if not eligible.empty:
                snapshot_id = eligible.iloc[-1]["snapshot_id"]
                return set(company_pools["members"].get(snapshot_id, set()))
        return set(prices["adj_close"].columns.astype(str))
    index_code = INDEX_CODES[pool_code]
    by_date = index_members.get(index_code, {})
    eligible_dates = [value for value in by_date if value <= rebalance_date]
    if not eligible_dates:
        return set()
    return set(by_date[max(eligible_dates)])


def feature_frame_for_date(
    rebalance_date: pd.Timestamp,
    *,
    universe: set[str],
    prices: dict[str, Any],
    daily_basic: pd.DataFrame,
    security_names: dict[str, str],
    theme_signals: dict[pd.Timestamp, dict[str, Any]],
) -> pd.DataFrame:
    """Build the scoring feature frame for one rebalance date.

    Args:
        rebalance_date: PIT rebalance timestamp.
        universe: Set of security IDs in the universe.
        prices: Market panel dict from load_market_panels.
        daily_basic: Daily valuation frame from load_daily_basic.
        security_names: Security ID to name mapping.
        theme_signals: Theme hotness signals keyed by date.

    Returns:
        pd.DataFrame: Feature frame with market features, latest valuation
            fundamentals, names and theme columns.
    """
    securities = sorted(universe & set(prices["adj_close"].columns.astype(str)))
    if not securities:
        return pd.DataFrame()
    records = pd.DataFrame({"security_id": securities})
    for name, panel in prices["features"].items():
        if rebalance_date in panel.index:
            values = panel.loc[rebalance_date, securities]
        else:
            values = panel.loc[:rebalance_date, securities].tail(1).squeeze()
        records[name] = records["security_id"].map(values.to_dict())
    if not daily_basic.empty:
        latest_basic = daily_basic.loc[daily_basic["trade_date"] <= rebalance_date]
        if not latest_basic.empty:
            latest_basic = latest_basic.sort_values(
                ["security_id", "trade_date"]
            ).drop_duplicates("security_id", keep="last")
            records = records.merge(
                latest_basic.drop(columns=["trade_date"]),
                on="security_id",
                how="left",
            )
    records["name"] = records["security_id"].map(security_names)
    records = attach_theme_features(records, rebalance_date, theme_signals)
    return records


def build_theme_signals(
    prices: dict[str, Any],
    rebalance_dates: list[pd.Timestamp],
) -> dict[pd.Timestamp, dict[str, Any]]:
    """Build PIT theme hotness signals from seed members and market panels.

    Args:
        prices: Market panel dict with adj_close, amount and returns.
        rebalance_dates: Rebalance timestamps for which to compute signals.

    Returns:
        dict[pd.Timestamp, dict[str, Any]]: Per-rebalance theme signal
            metrics including hot score, relative strength and confirmation.
    """
    adj_close = prices["adj_close"]
    amount = prices["amount"].reindex_like(adj_close)
    members = sorted(set(THEME_MEMBERS) & set(adj_close.columns.astype(str)))
    rows: list[dict[str, Any]] = []
    if not members:
        return {}
    returns_20d = adj_close / adj_close.shift(20) - 1.0
    returns_60d = adj_close / adj_close.shift(60) - 1.0
    amount_20d = amount.rolling(20, min_periods=10).mean()
    amount_120d = amount.rolling(120, min_periods=40).mean()
    for rebalance_date in rebalance_dates:
        date_key = _latest_panel_date(adj_close.index, rebalance_date)
        if date_key is None:
            continue
        member_20d = returns_20d.reindex(columns=members).loc[date_key].dropna()
        member_60d = returns_60d.reindex(columns=members).loc[date_key].dropna()
        market_20d = returns_20d.loc[date_key].dropna()
        market_60d = returns_60d.loc[date_key].dropna()
        if member_20d.empty or member_60d.empty or market_20d.empty or market_60d.empty:
            score = 0.0
            relative_strength_20d = 0.0
            relative_strength_60d = 0.0
            amount_ratio_20d = 1.0
            breadth_20d = 0.0
            drawdown_60d = 0.0
        else:
            market_return_20d = float(market_20d.median())
            market_return_60d = float(market_60d.median())
            relative_strength_20d = float(member_20d.mean() - market_return_20d)
            relative_strength_60d = float(member_60d.mean() - market_return_60d)
            amount_now = float(
                amount_20d.reindex(columns=members).loc[date_key].sum(skipna=True)
            )
            amount_base = float(
                amount_120d.reindex(columns=members).loc[date_key].sum(skipna=True)
            )
            amount_ratio_20d = amount_now / amount_base if amount_base > 0 else 1.0
            breadth_20d = float((member_20d > market_return_20d).mean())
            drawdown_60d = _theme_drawdown_60d(adj_close, members, date_key)
            score = score_theme_components(
                relative_strength_20d=relative_strength_20d,
                relative_strength_60d=relative_strength_60d,
                amount_ratio_20d=amount_ratio_20d,
                breadth_20d=breadth_20d,
                drawdown_60d=drawdown_60d,
            )
        rows.append(
            {
                "date": rebalance_date,
                "theme_code": THEME_CODE,
                "theme_name": THEME_NAME,
                "theme_source": THEME_SOURCE,
                "theme_hot_score": score,
                "theme_relative_strength_20d": relative_strength_20d,
                "theme_relative_strength_60d": relative_strength_60d,
                "theme_amount_ratio_20d": amount_ratio_20d,
                "theme_breadth_20d": breadth_20d,
                "theme_drawdown_60d": drawdown_60d,
                "theme_member_count": len(members),
            }
        )
    states = confirmation_states(
        [(row["date"], row["theme_hot_score"]) for row in rows],
        config=THEME_SIGNAL_CONFIG,
    )
    result: dict[pd.Timestamp, dict[str, Any]] = {}
    for row in rows:
        date_key = row["date"]
        row["theme_signal_confirmed"] = states.get(date_key, False)
        row["date"] = date_key.date().isoformat()
        result[date_key] = row
    return result


def attach_theme_features(
    records: pd.DataFrame,
    rebalance_date: pd.Timestamp,
    theme_signals: dict[pd.Timestamp, dict[str, Any]],
) -> pd.DataFrame:
    """Attach current theme signal and per-security membership confidence.

    Args:
        records: Candidate feature frame for one rebalance date.
        rebalance_date: The rebalance timestamp to look up.
        theme_signals: Pre-computed theme signals keyed by date.

    Returns:
        pd.DataFrame: Enriched records with theme columns, or the original
            frame when no signal exists for the date.
    """
    signal = theme_signals.get(rebalance_date)
    if signal is None:
        return records
    enriched = records.copy()
    confidence = enriched["security_id"].map(THEME_MEMBERS).fillna(0.0).astype(float)
    member_mask = confidence > 0
    enriched["theme_member_confidence"] = confidence
    enriched["theme_hot_score"] = float(signal["theme_hot_score"])
    enriched["theme_signal_confirmed"] = bool(signal["theme_signal_confirmed"])
    enriched["theme_relative_strength_20d"] = float(
        signal["theme_relative_strength_20d"]
    )
    enriched["theme_relative_strength_60d"] = float(
        signal["theme_relative_strength_60d"]
    )
    enriched["theme_amount_ratio_20d"] = float(signal["theme_amount_ratio_20d"])
    enriched["theme_breadth_20d"] = float(signal["theme_breadth_20d"])
    enriched["theme_drawdown_60d"] = float(signal["theme_drawdown_60d"])
    enriched.loc[member_mask, "theme_code"] = THEME_CODE
    enriched.loc[member_mask, "theme_name"] = THEME_NAME
    enriched.loc[member_mask, "theme_source"] = THEME_SOURCE
    return enriched


def theme_adjusted_weights(
    weights: dict[str, float],
    *,
    theme_enabled: bool,
) -> dict[str, float]:
    """Return factor weights with theme-hotness isolated behind a switch.

    Args:
        weights: Original factor weight map.
        theme_enabled: When False, theme_hotness weight is zeroed out.

    Returns:
        dict[str, float]: Adjusted weight map.
    """
    adjusted = dict(weights)
    if not theme_enabled:
        adjusted["theme_hotness"] = 0.0
    return adjusted


def _latest_panel_date(
    index: pd.DatetimeIndex,
    target: pd.Timestamp,
) -> pd.Timestamp | None:
    """Return the latest panel date at or before the target timestamp."""
    eligible = pd.DatetimeIndex(index).sort_values()
    eligible = eligible[eligible <= target]
    return None if eligible.empty else eligible[-1]


def _theme_drawdown_60d(
    adj_close: pd.DataFrame,
    members: list[str],
    date_key: pd.Timestamp,
) -> float:
    """Compute the max drawdown of the theme member NAV over the trailing 60 days."""
    window = adj_close.reindex(columns=members).loc[:date_key].tail(60).ffill()
    window = window.dropna(axis=1, thresh=max(20, len(window) // 2))
    if len(window) < 20 or window.empty:
        return 0.0
    normalized = window / window.iloc[0]
    theme_nav = normalized.mean(axis=1, skipna=True).dropna()
    if theme_nav.empty:
        return 0.0
    drawdown = theme_nav / theme_nav.cummax() - 1.0
    return float(drawdown.min())


def _theme_signal_value(
    theme_signals: dict[pd.Timestamp, dict[str, Any]],
    rebalance_date: pd.Timestamp,
    key: str,
) -> Any:
    """Safely look up a single theme signal field for a rebalance date."""
    signal = theme_signals.get(rebalance_date)
    return None if signal is None else signal.get(key)


def target_weight_map(
    scored: pd.DataFrame,
    target_ids: list[str],
    weighting: str,
    sell_threshold: float,
) -> dict[str, float]:
    """Compute normalized target weights for selected securities.

    Args:
        scored: Scored candidate frame with manual_all_a_score and
            volatility_120d columns.
        target_ids: Security IDs to include in the target portfolio.
        weighting: Weighting scheme ("inv_vol_score", "score_excess" or
            equal weight).
        sell_threshold: Score threshold below which excess is clipped.

    Returns:
        dict[str, float]: Mapping from security ID to normalized weight.
    """
    if not target_ids:
        return {}
    target = scored.loc[scored["security_id"].astype(str).isin(target_ids)].copy()
    if target.empty:
        return {}
    if weighting == "inv_vol_score":
        default_vol = target.get("volatility_120d", pd.Series([0.25])).median()
        vol = (
            pd.to_numeric(target.get("volatility_120d"), errors="coerce")
            .replace(0, np.nan)
            .fillna(default_vol)
        )
        raw_score = pd.to_numeric(target["manual_all_a_score"], errors="coerce")
        raw = (raw_score - sell_threshold + 1.0).clip(lower=1.0) / vol.clip(
            lower=0.05
        )
    elif weighting == "score_excess":
        raw_score = pd.to_numeric(target["manual_all_a_score"], errors="coerce")
        raw = (raw_score - sell_threshold + 1.0).clip(lower=1.0)
    else:
        raw = pd.Series(1.0, index=target.index)
    raw = raw.replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(lower=0.0)
    if raw.sum() <= 0:
        raw = pd.Series(1.0, index=target.index)
    weights = raw / raw.sum()
    return dict(
        zip(target["security_id"].astype(str), weights.astype(float), strict=False)
    )


def summarize_backtest(
    *,
    pool_code: str,
    preset: Any,
    cost_bps: int,
    nav_frame: pd.DataFrame,
    trades: pd.DataFrame,
    total_turnover: float,
    skipped_rebalances: int,
    data_notes: list[str],
    theme_enabled: bool = True,
) -> dict[str, Any]:
    """Compute summary statistics for one pool backtest run.

    Args:
        pool_code: Pool identifier (CSI300, ALL_A, CSI500).
        preset: Quant pool preset with thresholds and weighting.
        cost_bps: Transaction cost in basis points.
        nav_frame: Daily NAV rows for the backtest.
        trades: Per-rebalance trade rows.
        total_turnover: Cumulative turnover across all rebalances.
        skipped_rebalances: Count of rebalances skipped due to empty data.
        data_notes: Human-readable data quality notes.
        theme_enabled: Whether the theme factor was active.

    Returns:
        dict[str, Any]: Summary dict with return, risk, turnover and holdings
            statistics, or an insufficient_data status when NAV is empty.
    """
    if nav_frame.empty:
        return {
            "pool": pool_code,
            "label": preset.label,
            "cost_bps": cost_bps,
            "status": "insufficient_data",
            "data_notes": ";".join(data_notes[:20]),
        }
    returns = pd.to_numeric(nav_frame["daily_return"], errors="coerce").fillna(0.0)
    nav = pd.to_numeric(nav_frame["nav"], errors="coerce")
    days = max(len(nav_frame), 1)
    cum_return = float(nav.iloc[-1] - 1.0)
    ann_return = float(nav.iloc[-1] ** (252.0 / days) - 1.0)
    ann_vol = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else 0.0
    ir = ann_return / ann_vol if ann_vol > 0 else None
    drawdown = nav / nav.cummax() - 1.0
    years = days / 252.0
    return {
        "pool": pool_code,
        "label": preset.label,
        "cost_bps": cost_bps,
        "status": "ok",
        "buy_threshold": preset.buy_threshold,
        "sell_threshold": preset.sell_threshold,
        "weighting": preset.weighting,
        "cum_return": cum_return,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "information_ratio": ir,
        "max_drawdown": float(drawdown.min()),
        "annual_turnover": total_turnover / years if years > 0 else None,
        "avg_holdings": float(trades["holdings"].mean()) if not trades.empty else 0.0,
        "median_holdings": float(trades["holdings"].median()) if not trades.empty else 0.0,
        "min_holdings": int(trades["holdings"].min()) if not trades.empty else 0,
        "max_holdings": int(trades["holdings"].max()) if not trades.empty else 0,
        "min_holding_months": int(
            trades["min_holding_months"].max()
        ) if not trades.empty and "min_holding_months" in trades else 0,
        "theme_source": THEME_SOURCE if theme_enabled else "disabled",
        "theme_confirmed_rebalances": int(
            pd.to_numeric(
                trades.get("theme_signal_confirmed", pd.Series(dtype=int)),
                errors="coerce",
            ).fillna(0).sum()
        ) if not trades.empty else 0,
        "avg_theme_hot_score": float(
            pd.to_numeric(
                trades.get("theme_hot_score", pd.Series(dtype=float)),
                errors="coerce",
            ).mean()
        ) if not trades.empty else None,
        "skipped_rebalances": skipped_rebalances,
        "data_notes": ";".join(dict.fromkeys(data_notes[:20])),
    }


if __name__ == "__main__":
    raise SystemExit(main())
