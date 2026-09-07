"""Action-specific validation for POST /api/agents/recommendations/{id}/execute (0092/0107)."""
from __future__ import annotations
from datetime import datetime as _dt
from typing import Optional

# Required fields by action type (0107 / 0132)
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "EXIT":             ["execution_date", "quantity", "execution_price"],
    "TRIM":             ["execution_date", "quantity", "execution_price"],
    "ALLOCATE":         ["execution_date", "quantity", "execution_price"],
    "BUY":              ["execution_date", "quantity", "execution_price"],
    "HARVEST":          ["execution_date", "quantity", "execution_price"],
    "SELL_CC":          ["execution_date", "contracts", "strike", "premium", "expiration"],
    "BUY_TO_CLOSE":     ["execution_date", "execution_price"],
    "ALLOW_ASSIGNMENT": ["execution_date"],
    "ROLL_OUT":         ["execution_date"],   # btc_price/sto_premium checked separately
    "ROLL_UP":          ["execution_date"],
    "ROLL_UP_AND_OUT":  ["execution_date"],
}


def validate_execution_body(
    action: str,
    body: dict,
    rec: dict,
    today,  # datetime.date
    server_pos_before: Optional[float] = None,  # 0107: loaded from holdings.csv server-side
) -> "tuple[int, str] | None":
    """Return (http_code, message) on validation failure, or None on success."""

    execution_date = (body.get("execution_date") or "").strip()
    if not execution_date:
        return (400, "execution_date is required")

    try:
        exec_dt = _dt.strptime(execution_date, "%Y-%m-%d").date()
    except ValueError:
        return (400, "execution_date must be YYYY-MM-DD")

    if exec_dt > today:
        return (400, "execution_date cannot be in the future")

    rec_date = _dt.utcfromtimestamp(rec["created_at"]).date()
    if exec_dt < rec_date:
        return (
            400,
            f"execution_date {execution_date} cannot be before recommendation date {rec_date.isoformat()}",
        )

    # 0107: enforce required fields per action type
    required = _REQUIRED_FIELDS.get(action, [])
    for field in required:
        if field == "execution_date":
            continue  # already checked above
        if not body.get(field) and body.get(field) != 0:
            return (400, f"{field} is required for {action}")

    quantity           = body.get("quantity")
    execution_price    = body.get("execution_price")
    execution_fraction = body.get("execution_fraction")
    contracts          = body.get("contracts")
    strike             = body.get("strike")
    premium            = body.get("premium")
    expiration         = body.get("expiration")

    # 0107: use server-side position size; ignore client-supplied position_shares_before
    pos_before = server_pos_before

    if action in ("EXIT", "TRIM", "ALLOCATE"):
        if quantity is not None and float(quantity) <= 0:
            return (400, "quantity must be > 0")
        if execution_price is not None and float(execution_price) <= 0:
            return (400, "execution_price must be > 0")
        if pos_before is not None and quantity is not None and float(quantity) > pos_before:
            return (400, "quantity cannot exceed position_shares_before")
        if execution_fraction is not None:
            ef = float(execution_fraction)
            if not (0 < ef <= 1.0):
                return (400, "execution_fraction must be in (0, 1]")

    elif action == "SELL_CC":
        if contracts is not None and int(contracts) < 1:
            return (400, "contracts must be >= 1")
        if strike is not None and float(strike) <= 0:
            return (400, "strike must be > 0")
        if premium is not None and float(premium) <= 0:
            return (400, "premium must be > 0")
        if expiration:
            try:
                exp_dt = _dt.strptime(str(expiration), "%Y-%m-%d").date()
                if exp_dt < exec_dt:
                    return (400, "expiration cannot be before execution_date")
            except ValueError:
                return (400, "expiration must be YYYY-MM-DD")
        if contracts is not None and pos_before is not None:
            if int(contracts) * 100 > pos_before:
                return (
                    400,
                    f"contracts*100 ({int(contracts)*100}) exceeds covered shares ({pos_before:.0f})",
                )

    elif action in ("ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT"):
        btc_price  = body.get("btc_price")
        sto_premium = body.get("sto_premium")
        new_strike  = body.get("new_strike")
        new_expiry  = body.get("new_expiration")
        if btc_price is None and execution_price is None:
            return (400, "btc_price (or execution_price) required for roll BTC leg")
        if sto_premium is None and premium is None:
            return (400, "sto_premium (or premium) required for roll STO leg")
        if new_strike is None and strike is None:
            return (400, "new_strike (or strike) required for roll STO leg")
        if new_expiry is None and expiration is None:
            return (400, "new_expiration (or expiration) required for roll STO leg")

    return None
