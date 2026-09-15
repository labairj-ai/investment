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
    return datetime.fromtimestamp(captured_at, tz=timezone.utc).strftime("%Y-%m-%d")


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


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    label_mature_episodes(dry_run=dry)
