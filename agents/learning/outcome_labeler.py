"""Daily Outcome Labeler (0328).

Run once per day after market close to label mature decision_episodes rows
with real market outcomes across 1w / 1m / 3m / 6m / 12m horizons.

Usage:
    python -m agents.learning.outcome_labeler          # label all mature episodes
    python -m agents.learning.outcome_labeler --dry-run # print what would be labeled

Designed to run from Optiplex via systemd timer (outcome-labeler.timer).
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone

import agent_db

# Horizons: (label, calendar_days_from_capture)
_HORIZONS: list[tuple[str, int]] = [
    ("1w",  7),
    ("1m",  30),
    ("3m",  91),
    ("6m",  182),
    ("12m", 365),
]

# Episodes must be at least this old before their 1w label is written.
_MIN_AGE_DAYS = 7


def _entry_date(captured_at: float) -> str:
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo("America/New_York")
    except Exception:
        from datetime import timedelta
        et_tz = timezone(timedelta(hours=-4))
    return datetime.fromtimestamp(captured_at, tz=et_tz).strftime("%Y-%m-%d")


def _horizon_date(entry: str, days: int) -> str:
    return (date.fromisoformat(entry) + timedelta(days=days)).isoformat()


def _already_labeled(conn, episode_id: str, horizon: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM episode_outcomes WHERE episode_id=? AND horizon=? LIMIT 1",
        (episode_id, horizon),
    ).fetchone()
    return row is not None


def _get_ticker_price(ticker: str, target_date: str) -> float | None:
    """Return the closing price for ticker on or before target_date.

    Tries holding_day first (fast, cached), then yfinance (network, fallback).
    """
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT price FROM holding_day WHERE ticker=? AND day<=? AND price>0 "
        "ORDER BY day DESC LIMIT 1",
        (ticker, target_date),
    ).fetchone()
    conn.close()
    if row:
        return float(row["price"])
    return _yf_price(ticker, target_date)


def _yf_price(ticker: str, target_date: str) -> float | None:
    try:
        import yfinance as yf
        start = (date.fromisoformat(target_date) - timedelta(days=5)).isoformat()
        end   = (date.fromisoformat(target_date) + timedelta(days=2)).isoformat()
        hist  = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if hist.empty:
            return None
        # Walk back up to 5 days to find a trading day
        for delta in range(6):
            candidate = (date.fromisoformat(target_date) - timedelta(days=delta)).isoformat()
            for idx, row in hist.iterrows():
                if idx.strftime("%Y-%m-%d") == candidate:
                    return float(row["Close"])
    except Exception as e:
        print(f"[outcome_labeler] yfinance fetch failed for {ticker} @ {target_date}: {e}")
    return None


def _spy_price_at(date_str: str) -> float | None:
    """Return cached SPY price, fetching from yfinance if missing."""
    from agents.outcome_evaluator import _ensure_spy_prices, _spy_price_at as _spy_get
    _ensure_spy_prices([date_str])
    return _spy_get(date_str)


def _fetch_price_series(ticker: str, start: str, end: str) -> dict[str, float]:
    """Return {date_str: close_price} for ticker in [start, end] window."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        return {idx.strftime("%Y-%m-%d"): float(r["Close"]) for idx, r in hist.iterrows()}
    except Exception as e:
        print(f"[outcome_labeler] price series fetch failed for {ticker}: {e}")
        return {}


def _compute_mfe_mae(
    ticker: str,
    entry_date: str,
    horizon_date: str,
    entry_price: float,
) -> tuple[float | None, float | None]:
    """Compute max favorable excursion and max adverse excursion over the window.

    MFE = max((price - entry) / entry) across all days in window
    MAE = min((price - entry) / entry) across all days in window
    """
    series = _fetch_price_series(ticker, entry_date, horizon_date)
    if not series:
        return None, None
    returns = [(p / entry_price) - 1.0 for p in series.values() if entry_price > 0]
    if not returns:
        return None, None
    return max(returns), min(returns)


def _insert_outcome(
    conn,
    episode_id: str,
    horizon: str,
    ticker_return: float | None,
    spy_return: float | None,
    alpha: float | None,
    mfe: float | None,
    mae: float | None,
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO episode_outcomes
           (episode_id, horizon, ticker_return, spy_return, alpha, mfe, mae, labeled_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (episode_id, horizon, ticker_return, spy_return, alpha, mfe, mae, time.time()),
    )


def _label_one_episode(
    conn,
    episode_id: str,
    ticker: str,
    captured_at: float,
    today: str,
    dry_run: bool,
) -> int:
    """Label all mature horizons for one episode. Returns count of horizons written."""
    entry = _entry_date(captured_at)
    written = 0
    for horizon_label, days in _HORIZONS:
        h_date = _horizon_date(entry, days)
        if h_date > today:
            continue
        if _already_labeled(conn, episode_id, horizon_label):
            continue

        entry_price = _get_ticker_price(ticker, entry)
        h_price     = _get_ticker_price(ticker, h_date)
        if entry_price is None or h_price is None or entry_price == 0:
            print(f"[outcome_labeler] missing price for {ticker} "
                  f"entry={entry} horizon={h_date} — skipping")
            continue

        ticker_return = (h_price / entry_price) - 1.0

        spy_entry = _spy_price_at(entry)
        spy_h     = _spy_price_at(h_date)
        spy_return = ((spy_h / spy_entry) - 1.0) if spy_entry and spy_h else None
        alpha      = (ticker_return - spy_return) if spy_return is not None else None

        mfe, mae = _compute_mfe_mae(ticker, entry, h_date, entry_price)

        if dry_run:
            print(
                f"  DRY-RUN {ticker} {horizon_label}: "
                f"return={ticker_return:+.2%} spy={spy_return and f'{spy_return:+.2%}' or '?'} "
                f"alpha={alpha and f'{alpha:+.2%}' or '?'} "
                f"mfe={mfe and f'{mfe:+.2%}' or '?'} mae={mae and f'{mae:+.2%}' or '?'}"
            )
        else:
            _insert_outcome(conn, episode_id, horizon_label, ticker_return,
                            spy_return, alpha, mfe, mae)
            # 0360: propagate 3m alpha to model_observations shadow predictions
            if horizon_label == "3m" and alpha is not None:
                try:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """UPDATE model_observations
                           SET outcome_alpha_90d=?, outcome_labeled_at=?
                           WHERE episode_id=? AND outcome_alpha_90d IS NULL""",
                        (alpha, now_iso, episode_id),
                    )
                except Exception:
                    pass
        written += 1

    if not dry_run and written:
        conn.commit()
    return written


def label_mature_episodes(
    min_age_days: int = _MIN_AGE_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Label all unlabeled episode_outcomes rows for episodes older than min_age_days.

    Returns {"episodes_checked": n, "horizons_written": m}.
    """
    cutoff = time.time() - (min_age_days * 86400)
    today  = date.today().isoformat()

    conn = agent_db._connect()
    episodes = conn.execute(
        "SELECT episode_id, ticker, captured_at FROM decision_episodes WHERE captured_at < ?",
        (cutoff,),
    ).fetchall()

    total_written = 0
    for ep in episodes:
        ep_id     = ep["episode_id"]
        ticker    = ep["ticker"]
        captured  = ep["captured_at"]
        if dry_run:
            print(f"[outcome_labeler] {ticker} (captured {_entry_date(captured)}):")
        written = _label_one_episode(conn, ep_id, ticker, captured, today, dry_run)
        total_written += written

    conn.close()
    result = {"episodes_checked": len(episodes), "horizons_written": total_written}
    if not dry_run:
        print(f"[outcome_labeler] Done: {result}")
    return result


_CF_HORIZONS: list[tuple[str, int]] = [
    ("1w",  7),
    ("1m",  30),
    ("3m",  91),
]


def _already_cf_labeled(conn, intent_id: str, horizon: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM risk_counterfactual_outcomes WHERE intent_id=? AND horizon=? LIMIT 1",
        (intent_id, horizon),
    ).fetchone()
    return row is not None


def label_risk_counterfactuals(
    min_age_days: int = _MIN_AGE_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Label mature risk counterfactual rows with market outcomes (0332).

    Finds base rejection rows (horizon IS NULL) that are old enough, then for
    each mature horizon inserts a labeled row with ticker/SPY returns and alpha.

    Returns {"rejections_checked": n, "horizons_written": m}.
    """
    cutoff = time.time() - (min_age_days * 86400)
    today  = date.today().isoformat()

    conn = agent_db._connect()
    base_rows = conn.execute(
        """SELECT id, intent_id, episode_id, ticker, side, decision_date, rejected_at
           FROM risk_counterfactual_outcomes
           WHERE horizon IS NULL AND rejected_at < ?""",
        (cutoff,),
    ).fetchall()

    total_written = 0
    for base in base_rows:
        intent_id = base["intent_id"]
        ticker    = base["ticker"]
        side      = (base["side"] or "BUY").upper()
        entry     = base["decision_date"] or _entry_date(base["rejected_at"] or time.time())

        for horizon_label, days in _CF_HORIZONS:
            h_date = _horizon_date(entry, days)
            if h_date > today:
                continue
            if _already_cf_labeled(conn, intent_id, horizon_label):
                continue

            entry_price = _get_ticker_price(ticker, entry)
            h_price     = _get_ticker_price(ticker, h_date)
            if entry_price is None or h_price is None or entry_price == 0:
                print(f"[outcome_labeler] counterfactual missing price for {ticker} "
                      f"entry={entry} horizon={h_date} — skipping")
                continue

            ticker_return = (h_price / entry_price) - 1.0

            # 0338: directional_return flips sign for SELL/EXIT — a blocked exit before
            # a price decline is a good blocked trade (decision was right, gate was wrong).
            directional_return = ticker_return if side == "BUY" else -ticker_return

            spy_entry = _spy_price_at(entry)
            spy_h     = _spy_price_at(h_date)
            spy_return = ((spy_h / spy_entry) - 1.0) if spy_entry and spy_h else None
            alpha      = (ticker_return - spy_return) if spy_return is not None else None
            decision_alpha = (directional_return - spy_return) if spy_return is not None else None

            mfe, mae = _compute_mfe_mae(ticker, entry, h_date, entry_price)

            if dry_run:
                print(
                    f"  DRY-RUN counterfactual {ticker} {horizon_label}: "
                    f"return={ticker_return:+.2%} directional={directional_return:+.2%} "
                    f"alpha={alpha and f'{alpha:+.2%}' or '?'}"
                )
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO risk_counterfactual_outcomes
                       (intent_id, episode_id, ticker, decision_date, horizon,
                        ticker_return, spy_return, alpha,
                        directional_return, decision_alpha,
                        mfe, mae, labeled_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        intent_id, base["episode_id"], ticker, entry,
                        horizon_label, ticker_return, spy_return, alpha,
                        directional_return, decision_alpha,
                        mfe, mae, time.time(),
                    ),
                )
            total_written += 1

    if not dry_run and total_written:
        conn.commit()
    conn.close()
    result = {"rejections_checked": len(base_rows), "horizons_written": total_written}
    if not dry_run:
        print(f"[outcome_labeler] counterfactuals: {result}")
    return result


_TO_HORIZONS: list[tuple[str, int, str]] = [
    ("1w",  7,  "labeled_1w_at"),
    ("1m",  30, "labeled_1m_at"),
    ("3m",  91, "labeled_3m_at"),
]


def label_trade_outcomes(
    min_age_days: int = _MIN_AGE_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Label trade_outcomes rows with fill-price-entry returns at 1w/1m/3m (0333).

    Scans rows where the labeled_Xw_at column is NULL and the fill is old enough.
    Computes return from fill_price (not market close), so the entry reflects actual
    execution quality — the EXECUTED_TRADE_RETURN label type.

    Returns {"fills_checked": n, "horizons_written": m}.
    """
    today = date.today().isoformat()
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT to2.id, to2.fill_id, to2.ticker, to2.fill_date, to2.fill_price,
                  to2.fill_fees, to2.fill_qty, to2.intent_id, to2.arrival_price,
                  COALESCE(to2.action, ti.side, 'BUY') AS resolved_action
           FROM trade_outcomes to2
           LEFT JOIN trade_intents ti ON to2.intent_id = ti.intent_id
           WHERE to2.fill_date IS NOT NULL AND to2.fill_price IS NOT NULL AND to2.fill_price > 0
             AND julianday('now') - julianday(to2.fill_date) >= ?""",
        (min_age_days,),
    ).fetchall()

    total_written = 0
    for row in rows:
        to_id = row["id"]
        ticker = row["ticker"]
        fill_date = row["fill_date"]
        gross_fill_price = float(row["fill_price"])
        fill_qty  = float(row["fill_qty"] or 1)
        fill_fees = float(row["fill_fees"] or 0)
        arrival_price = row["arrival_price"]

        # 0338: direction sign — SELL/EXIT/TRIM decisions are good when price falls after
        resolved_action = (row["resolved_action"] or "BUY").upper()
        is_sell = resolved_action in ("SELL", "EXIT", "TRIM")

        # 0339: fee-adjusted effective entry price
        fees_per_share = fill_fees / fill_qty if fill_qty > 0 else 0.0
        if is_sell:
            effective_entry = gross_fill_price - fees_per_share
        else:
            effective_entry = gross_fill_price + fees_per_share
        if effective_entry <= 0:
            effective_entry = gross_fill_price  # fallback if fees exceed price

        # 0339: implementation shortfall — filled price vs arrival (limit) price
        impl_shortfall = None
        if arrival_price and arrival_price > 0:
            if is_sell:
                impl_shortfall = (arrival_price - gross_fill_price) / arrival_price
            else:
                impl_shortfall = (gross_fill_price - arrival_price) / arrival_price

        for horizon_label, days, labeled_col in _TO_HORIZONS:
            h_date = _horizon_date(fill_date, days)
            if h_date > today:
                continue
            # Skip if already labeled
            existing = conn.execute(
                f"SELECT {labeled_col} FROM trade_outcomes WHERE id=?", (to_id,)
            ).fetchone()
            if existing and existing[labeled_col] is not None:
                continue

            h_price = _get_ticker_price(ticker, h_date)
            if h_price is None or effective_entry == 0:
                continue

            # 0339: fee-adjusted return uses effective_entry (fees baked in)
            to_return = (h_price / effective_entry) - 1.0
            # 0338: decision_return sign-flipped for SELL/EXIT/TRIM
            decision_return = -to_return if is_sell else to_return

            spy_entry = _spy_price_at(fill_date)
            spy_h     = _spy_price_at(h_date)
            spy_return = ((spy_h / spy_entry) - 1.0) if spy_entry and spy_h else None
            alpha      = (to_return - spy_return) if spy_return is not None else None
            decision_alpha = (decision_return - spy_return) if spy_return is not None else None

            mark_col          = f"mark_{horizon_label}"
            return_col        = f"return_{horizon_label}"
            spy_col           = f"spy_return_{horizon_label}"
            alpha_col         = f"alpha_{horizon_label}"
            dec_return_col    = f"decision_return_{horizon_label}"
            dec_alpha_col     = f"decision_alpha_{horizon_label}"

            if dry_run:
                print(
                    f"  DRY-RUN trade_outcome {ticker} {horizon_label}: "
                    f"return={to_return:+.2%} decision_return={decision_return:+.2%} "
                    f"alpha={alpha and f'{alpha:+.2%}' or '?'} IS={impl_shortfall}"
                )
            else:
                conn.execute(
                    f"""UPDATE trade_outcomes
                        SET {mark_col}=?, {return_col}=?, {spy_col}=?, {alpha_col}=?,
                            {dec_return_col}=?, {dec_alpha_col}=?,
                            implementation_shortfall=?, {labeled_col}=?
                        WHERE id=?""",
                    (h_price, to_return, spy_return, alpha,
                     decision_return, decision_alpha,
                     impl_shortfall, time.time(), to_id),
                )
            total_written += 1

    if not dry_run and total_written:
        conn.commit()
    conn.close()
    result = {"fills_checked": len(rows), "horizons_written": total_written}
    if not dry_run:
        print(f"[outcome_labeler] trade_outcomes: {result}")
    return result


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    label_mature_episodes(dry_run=dry)
    label_risk_counterfactuals(dry_run=dry)
    label_trade_outcomes(dry_run=dry)
