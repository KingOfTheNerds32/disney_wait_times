"""Daily archive job: merges wait_times.csv into history/wait_times_YYYY_MM.parquet,
then rebuilds data/history.json for the dashboard.

Runs once a day from .github/workflows/archive.yml so each monthly Parquet file is
rewritten at most once a day instead of on every 5-minute poll. The CSV keeps
LIVE_DAYS of rows, so a missed day is picked up by the next run.
"""
import glob
import json
import os
from datetime import datetime

import pandas as pd

from build_dashboard import LIVE_JSON, TZ, build_history, prepare
from health import describe, note_problem, salvage_csv

LIVE_CSV = 'wait_times.csv'
STALE_HOURS = 6  # polls normally pause for a few hours overnight


def check_freshness():
    """Flags polling that has silently stopped (cron-job.org down, API outage...)."""
    try:
        with open(LIVE_JSON, encoding='utf-8') as f:
            generated = datetime.fromisoformat(json.load(f)['generated'])
    except Exception as e:
        note_problem(f'Could not read {LIVE_JSON} to check data freshness ({describe(e)}).')
        return
    age = datetime.now(TZ) - generated
    if age.total_seconds() > STALE_HOURS * 3600:
        note_problem(f'The newest wait times are {age.total_seconds() / 3600:.0f} hours old '
                     f'(from {generated:%Y-%m-%d %H:%M} PT). Polling seems to have stopped: check '
                     f'the cron-job.org job and recent "Disney Poller" runs.')


def read_quarantined():
    """Salvages rows from CSVs the scraper set aside; returns (frames, files read)."""
    frames, done = [], []
    for path in sorted(glob.glob('quarantine/*.csv')):
        df = salvage_csv(path)
        if df is not None:
            frames.append(df)
            done.append(path)
        else:
            note_problem(f'Could not salvage {path}; left it in quarantine/ for a manual look.')
    return frames, done


def archive():
    check_freshness()
    quarantined, quarantine_files = read_quarantined()
    live = pd.concat([pd.read_csv(LIVE_CSV)] + quarantined, ignore_index=True)
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

    # Quarantined rows are in Parquet now, so their files can go.
    for path in quarantine_files:
        os.remove(path)
        print(f'Archived and removed {path}')

    frames = [pd.read_parquet(f) for f in sorted(glob.glob('history/*.parquet'))]
    # live.json is left to the next poll so the two workflows never edit the same file.
    build_history(prepare(pd.concat(frames, ignore_index=True)))


if __name__ == '__main__':
    archive()
