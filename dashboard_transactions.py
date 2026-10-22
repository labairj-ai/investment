"""Recover original purchases from open lots and immutable FIFO sale allocations."""
import json


def purchase_markers(conn, minimum_value=500):
    lots = {}

    def add(lot_id, ticker, day, price, shares):
        key = (lot_id, ticker, day, float(price))
        lots[key] = lots.get(key, 0.0) + float(shares)

    for row in conn.execute(
        "SELECT id, ticker, purchase_date, cost_per_share, shares FROM cost_lots"
    ):
        add(*row)
    for ticker, detail in conn.execute("SELECT ticker, fifo_detail FROM sell_transactions"):
        try:
            allocations = json.loads(detail or "[]")
        except (ValueError, TypeError):
            continue
        if not isinstance(allocations, list):
            continue
        for allocation in allocations:
            try:
                add(allocation["lot_id"], ticker, allocation["purchase_date"],
                    allocation["cost_per_share"], allocation["shares"])
            except (KeyError, TypeError, ValueError):
                continue
    return [
        dict(date=day, type="buy", ticker=ticker, shares=round(shares, 6), price=price)
        for (_, ticker, day, price), shares in sorted(lots.items(), key=lambda item: item[0][2])
        if shares * price >= minimum_value
    ]
