"""Fetches ride status, standby and Lightning Lane return times from ThemeParks.wiki.

Runs alongside the Queue-Times scrape in each poll (same fetch_timestamp, so the two
sources line up row for row) and keeps its own rolling CSV, archived daily to
history/themeparks_YYYY_MM.parquet by archive.py.

Lightning Lane types:
  MP  = Lightning Lane Multi Pass (the queue ThemeParks.wiki calls RETURN_TIME)
  ILL = Lightning Lane Single Pass / Individual (PAID_RETURN_TIME)
"""
from datetime import datetime

import pandas as pd
import requests

TP_CSV = 'themeparks.csv'
# ThemeParks.wiki park ids -> the park names used in wait_times.csv
PARKS = {
    '7340550b-c14d-4def-80bb-acdb51d49a66': 'Disneyland',
    '832fcd51-ea19-4e77-85c7-75d5843b127c': 'Disney California Adventure',
    'bc4005c5-8c7e-41d7-b349-cdddf1796427': 'Universal Studios Hollywood',
}
TP_COLUMNS = ['fetch_timestamp', 'park_name', 'ride_name', 'status', 'standby_wait',
              'single_rider_wait', 'll_type', 'll_state', 'll_return_start', 'll_return_end']


def _local(ts):
    """'2026-10-26T12:35:00-07:00' -> '2026-10-26 12:35' (park-local, like fetch_timestamp)."""
    if not ts:
        return None
    return datetime.fromisoformat(ts).strftime('%Y-%m-%d %H:%M')


def fetch_themeparks(fetch_time):
    """Returns (rows, errors) for every attraction in PARKS."""
    rows, errors = [], []
    for park_id, park_name in PARKS.items():
        try:
            response = requests.get(f'https://api.themeparks.wiki/v1/entity/{park_id}/live', timeout=30)
            response.raise_for_status()
            live = response.json().get('liveData', [])
        except Exception as e:
            errors.append(f'{park_name}: {e}')
            continue
        for item in live:
            if item.get('entityType') != 'ATTRACTION':
                continue
            queue = item.get('queue') or {}
            ll_type, ll = None, {}
            if 'PAID_RETURN_TIME' in queue:
                ll_type, ll = 'ILL', queue['PAID_RETURN_TIME']
            elif 'RETURN_TIME' in queue:
                ll_type, ll = 'MP', queue['RETURN_TIME']
            rows.append({
                'fetch_timestamp': fetch_time,
                'park_name': park_name,
                'ride_name': item.get('name'),
                'status': item.get('status'),
                'standby_wait': (queue.get('STANDBY') or {}).get('waitTime'),
                'single_rider_wait': (queue.get('SINGLE_RIDER') or {}).get('waitTime'),
                'll_type': ll_type,
                'll_state': ll.get('state'),
                'll_return_start': _local(ll.get('returnStart')),
                'll_return_end': _local(ll.get('returnEnd')),
            })
    return rows, errors


def prepare_tp(df):
    """Parses timestamps and numbers in ThemeParks.wiki rows."""
    df = df.copy()
    df['ts'] = pd.to_datetime(df['fetch_timestamp'], errors='coerce')
    df.dropna(subset=['ts', 'park_name', 'ride_name'], inplace=True)
    for col in ('standby_wait', 'single_rider_wait'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['ll_start'] = pd.to_datetime(df['ll_return_start'], errors='coerce')
    # Minutes from the snapshot until the earliest Lightning Lane return time
    df['ll_minutes_out'] = ((df['ll_start'] - df['ts']).dt.total_seconds() / 60).clip(lower=0)
    available = df['ll_state'] == 'AVAILABLE'
    df.loc[~available, 'll_minutes_out'] = None
    return df
