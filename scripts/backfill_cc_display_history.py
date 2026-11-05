"""Backfill display-only historical option closes. Default is read-only dry run."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cc_history_backfill import collect, apply


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    import yfinance as yf
    with sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        result=collect(conn,yf.Ticker)
    inserted=0
    if args.apply:
        with sqlite3.connect(args.db,timeout=30) as conn:
            inserted=apply(conn,result['observations'])
    print(json.dumps(dict(mode='APPLIED' if args.apply else 'DRY_RUN',completed_session=result['completed_session'],
                         available_marks=len(result['observations']),inserted=inserted,failures=result['failures'])))


if __name__=='__main__':main()
