"""Action-specific validation for POST /api/agents/recommendations/{id}/execute (0092)."""
from datetime import datetime as _dt


def validate_execution_body(
    action: str,
    body: dict,
    rec: dict,
    today,  # datetime.date
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

    quantity           = body.get("quantity")
    execution_price    = body.get("execution_price")
    execution_fraction = body.get("execution_fraction")
    contracts          = body.get("contracts")
    strike             = body.get("strike")
    premium            = body.get("premium")
    expiration         = body.get("expiration")
    pos_before         = body.get("position_shares_before")

    if action in ("EXIT", "TRIM", "ALLOCATE"):
        if quantity is not None and float(quantity) <= 0:
            return (400, "quantity must be > 0")
        if execution_price is not None and float(execution_price) <= 0:
            return (400, "execution_price must be > 0")
        if pos_before is not None and quantity is not None and float(quantity) > float(pos_before):
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
            covered_shares = float(pos_before)
            if int(contracts) * 100 > covered_shares:
                return (
                    400,
                    f"contracts*100 ({int(contracts)*100}) exceeds covered shares ({covered_shares:.0f})",
                )

    elif action in ("ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT"):
        # 0101: multi-leg roll — validate both legs are present
        btc_price  = body.get("btc_price")   # debit paid to close existing
        sto_premium = body.get("sto_premium") # premium received for new leg
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
        # Net credit check: STO premium should exceed BTC debit (warn, don't block)
        _btc = float(btc_price or execution_price or 0)
        _sto = float(sto_premium or premium or 0)
        if _sto < _btc:
            # Allow with warning — user may accept a net debit roll
            pass

    return None
