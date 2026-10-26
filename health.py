"""Records problems the pipeline recovered from (or noticed) during a run.

Scripts call note_problem(); the workflow's final step opens a GitHub issue from
PROBLEMS_FILE when it exists (see .github/scripts/report_problems.sh). The file is
never committed.
"""
from datetime import datetime, timezone

import pandas as pd

PROBLEMS_FILE = 'pipeline_problems.md'
# Column order written by the scraper (older files also have ride_id after land).
CSV_COLUMNS = ['fetch_timestamp', 'park_name', 'land', 'ride_id', 'ride_name', 'wait_time',
               'is_open', 'last_updated']


def note_problem(message):
    print(f'::warning::{message}')
    with open(PROBLEMS_FILE, 'a', encoding='utf-8') as f:
        f.write(f'- {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {message}\n')


def csv_is_usable(df):
    """True if most rows have a parseable fetch_timestamp (i.e. the file isn't garbage)."""
    if df is None or 'fetch_timestamp' not in df.columns or df.empty:
        return False
    valid = pd.to_datetime(df['fetch_timestamp'], errors='coerce').notna().sum()
    return valid >= 0.5 * len(df)


def salvage_csv(path):
    """Best-effort read of a damaged wait-times CSV; returns a DataFrame or None.

    Skips malformed lines, and if the header itself is damaged, re-reads the file
    assuming the scraper's standard column order.
    """
    attempts = [
        dict(on_bad_lines='skip', engine='python'),
        dict(on_bad_lines='skip', engine='python', header=None, skiprows=1, names=CSV_COLUMNS),
        dict(on_bad_lines='skip', engine='python', header=None, skiprows=1, names=CSV_COLUMNS[:3] + CSV_COLUMNS[4:]),
    ]
    for kwargs in attempts:
        try:
            df = pd.read_csv(path, encoding_errors='replace', **kwargs)
        except Exception:
            continue
        if csv_is_usable(df):
            return df
    return None


def describe(error):
    return ' '.join(str(error).split())
