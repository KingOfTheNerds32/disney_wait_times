"""Daily archive job: merges wait_times.csv into history/wait_times_YYYY_MM.parquet,
then rebuilds data/history.json for the dashboard.

Runs once a day from .github/workflows/archive.yml so each monthly Parquet file is
rewritten at most once a day instead of on every 5-minute poll. The CSV keeps
LIVE_DAYS of rows, so a missed day is picked up by the next run.
"""
import glob
import os

import pandas as pd

from build_dashboard import build_history, prepare

LIVE_CSV = 'wait_times.csv'


def archive():
    live = pd.read_csv(LIVE_CSV)
    live['fetch_timestamp'] = pd.to_datetime(live['fetch_timestamp'], errors='coerce')
    live.dropna(subset=['fetch_timestamp'], inplace=True)
    live['year_month'] = live['fetch_timestamp'].dt.strftime('%Y_%m')

    os.makedirs('history', exist_ok=True)
    for year_month, group in live.groupby('year_month'):
        path = f'history/wait_times_{year_month}.parquet'
        group = group.drop(columns=['year_month'])
        if os.path.exists(path):
            existing = pd.read_parquet(path)
            existing['fetch_timestamp'] = pd.to_datetime(existing['fetch_timestamp'])
            merged = pd.concat([existing, group], ignore_index=True)
        else:
            merged = group
        merged.drop_duplicates(subset=['fetch_timestamp', 'ride_name'], keep='last', inplace=True)
        merged.sort_values('fetch_timestamp', inplace=True)
        merged.to_parquet(path, index=False, compression='snappy')
        print(f'{path}: {len(merged)} rows')

    frames = [pd.read_parquet(f) for f in sorted(glob.glob('history/*.parquet'))]
    # live.json is left to the next poll so the two workflows never edit the same file.
    build_history(prepare(pd.concat(frames, ignore_index=True)))


if __name__ == '__main__':
    archive()
