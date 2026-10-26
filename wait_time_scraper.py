import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import os
import pytz

from build_dashboard import build_live, prepare
from health import csv_is_usable, describe, note_problem, salvage_csv
from themeparks import TP_COLUMNS, TP_CSV, fetch_themeparks, prepare_tp

LIVE_DAYS = 10
QT_CSV = 'wait_times.csv'

def load_existing_csv(path, column_sets=None):
    """Reads the live CSV, recovering from corruption instead of failing the poll.

    The CSV holds rows the daily archive hasn't copied to Parquet yet, so it is never
    simply overwritten: unreadable lines are skipped, and if the file can't be read at
    all it is moved to quarantine/ (and committed) before starting a fresh one.
    """
    problem = None
    try:
        df = pd.read_csv(path)
        if csv_is_usable(df):
            return df
        problem = 'missing or unparseable fetch_timestamp column'
    except Exception as e:
        problem = describe(e)

    df = salvage_csv(path, column_sets)
    if df is not None:
        with open(path, encoding='utf-8', errors='replace') as f:
            total = sum(1 for _ in f) - 1
        note_problem(f'{path} was partly unreadable ({problem}). Kept {len(df)} rows, '
                     f'skipped {max(total - len(df), 0)} broken lines.')
        return df

    os.makedirs('quarantine', exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    dest = f"quarantine/{stem}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
    os.replace(path, dest)
    note_problem(f'{path} could not be read ({problem}). Moved it to {dest} and started a '
                 f'fresh file; the daily archive will try to recover its rows.')
    return None


def pull_wait_times():
    # Disneyland (16), DCA (17), and Universal Studios Hollywood (66)
    parks = {
        16: "Disneyland",
        17: "Disney California Adventure",
        66: "Universal Studios Hollywood"
    }
    
    all_rows = []
    tz = pytz.timezone('America/Los_Angeles')
    now_tz = datetime.now(tz)
    fetch_time = now_tz.strftime("%Y-%m-%d %H:%M:%S")
    
    for park_id, park_name in parks.items():
        url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status() 
            data = response.json()
            
            for land in data.get('lands', []):
                land_name = land.get('name')
                for ride in land.get('rides', []):
                    all_rows.append({
                        'fetch_timestamp': fetch_time,
                        'park_name': park_name,
                        'land': land_name,
                        'ride_name': ride.get('name'),
                        'wait_time': ride.get('wait_time'),
                        'is_open': ride.get('is_open'),
                        'last_updated': ride.get('last_updated')
                    })
        except Exception as e:
            print(f"Error fetching park {park_name} ({park_id}): {e}")

    cutoff = now_tz.replace(tzinfo=None) - timedelta(days=LIVE_DAYS)
    live_df = append_rolling_csv(QT_CSV, all_rows, cutoff) if all_rows else None

    # ThemeParks.wiki (ride status + Lightning Lane). A failure here never blocks the
    # Queue-Times data above.
    tp_rows, tp_errors = fetch_themeparks(fetch_time)
    if tp_errors and not tp_rows:
        note_problem('ThemeParks.wiki fetch failed for every park: ' + '; '.join(tp_errors))
    tp_df = append_rolling_csv(TP_CSV, tp_rows, cutoff, [TP_COLUMNS]) if tp_rows else None

    if live_df is not None:
        if tp_df is None and os.path.exists(TP_CSV):
            tp_df = load_existing_csv(TP_CSV, [TP_COLUMNS])
        build_live(prepare(live_df), prepare_tp(tp_df) if tp_df is not None else None)
        print(f"Logged {len(all_rows)} Queue-Times rides and {len(tp_rows)} ThemeParks.wiki rides.")


def append_rolling_csv(path, rows, cutoff, column_sets=None):
    """Appends rows to a rolling CSV, keeps rows newer than cutoff, returns the result.

    The daily archive job (archive.py) copies rows into history/*.parquet, so the CSV
    only needs to outlast a few missed archive runs and cover the 7 days the
    dashboard's uptime figures use.
    """
    combined = pd.DataFrame(rows)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        existing = load_existing_csv(path, column_sets)
        if existing is not None:
            combined = pd.concat([existing, combined], ignore_index=True)

    # 'coerce' turns broken timestamps into NaT, which are then dropped
    combined['fetch_timestamp'] = pd.to_datetime(combined['fetch_timestamp'], errors='coerce')
    combined.dropna(subset=['fetch_timestamp'], inplace=True)
    combined.drop_duplicates(subset=['fetch_timestamp', 'park_name', 'ride_name'], keep='last', inplace=True)

    live = combined[combined['fetch_timestamp'] >= cutoff].copy()
    live.to_csv(path, index=False)
    return live


if __name__ == "__main__":
    pull_wait_times()
