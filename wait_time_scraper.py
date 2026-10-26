import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import os
import pytz

from build_dashboard import build_live, prepare
from health import csv_is_usable, describe, note_problem, salvage_csv

LIVE_DAYS = 10

def load_existing_csv(path):
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

    df = salvage_csv(path)
    if df is not None:
        with open(path, encoding='utf-8', errors='replace') as f:
            total = sum(1 for _ in f) - 1
        note_problem(f'{path} was partly unreadable ({problem}). Kept {len(df)} rows, '
                     f'skipped {max(total - len(df), 0)} broken lines.')
        return df

    os.makedirs('quarantine', exist_ok=True)
    dest = f"quarantine/wait_times_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
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

    if all_rows:
        new_data_df = pd.DataFrame(all_rows)
        master_csv_file = 'wait_times.csv'
        
        # Load existing data
        existing_df = None
        if os.path.exists(master_csv_file) and os.path.getsize(master_csv_file) > 0:
            existing_df = load_existing_csv(master_csv_file)
        if existing_df is not None:
            combined_df = pd.concat([existing_df, new_data_df], ignore_index=True)
        else:
            combined_df = new_data_df

        # 'coerce' turns any corrupted or broken timestamp strings into NaT (Not a Time) values safely
        combined_df['fetch_timestamp'] = pd.to_datetime(combined_df['fetch_timestamp'], errors='coerce')
        
        # Drop any rows that couldn't be parsed so they don't break the rest of the script
        combined_df.dropna(subset=['fetch_timestamp'], inplace=True)

        combined_df.drop_duplicates(subset=['fetch_timestamp', 'ride_name'], keep='last', inplace=True)

        # Keep a rolling window in the CSV. The daily archive job (archive.py) moves
        # rows into history/*.parquet, so this only needs to outlast a few missed runs
        # while still covering the 7 days the dashboard's uptime figures use.
        cutoff_date = now_tz.replace(tzinfo=None) - timedelta(days=LIVE_DAYS)
        live_dash_df = combined_df[combined_df['fetch_timestamp'] >= cutoff_date].copy()
        live_dash_df.to_csv(master_csv_file, index=False)

        build_live(prepare(live_dash_df))
        print(f"Logged {len(all_rows)} rides. Live CSV and dashboard data updated.")

if __name__ == "__main__":
    pull_wait_times()
