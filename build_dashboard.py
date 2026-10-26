"""Precomputes the small JSON files the dashboard (index.html) loads.

data/live.json     - rebuilt every poll from wait_times.csv: current waits, today's
                     sparklines, status/uptime, compared against history.json.
data/history.json  - rebuilt daily by archive.py from the Parquet archive + CSV:
                     day-of-week x hour heatmaps, best times, typical daily curves.

All timestamps are Pacific time, matching fetch_timestamp.
"""
import json
import math
import os
from datetime import datetime, timedelta

import pandas as pd
import pytz

TZ = pytz.timezone('America/Los_Angeles')
SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES
LIVE_JSON = 'data/live.json'
HISTORY_JSON = 'data/history.json'

# Ride durations in minutes, used for the efficiency score.
RIDE_DURATIONS = {"Adventureland Treehouse inspired by Walt Disney’s Swiss Family Robinson": 15.0, "Indiana Jones™ Adventure": 3.4, "Jungle Cruise": 8.0, "Walt Disney's Enchanted Tiki Room": 15.6, "Davy Crockett's Explorer Canoes": 10.0, "The Many Adventures of Winnie the Pooh": 3.0, "Tiana's Bayou Adventure": 11.0, "it's a small world": 15.0, "Alice in Wonderland": 3.6, "Casey Jr. Circus Train": 3.6, "Dumbo the Flying Elephant": 1.5, "King Arthur Carrousel": 2.0, "Mad Tea Party": 1.5, "Matterhorn Bobsleds": 2.0, "Mr. Toad's Wild Ride": 2.0, "Peter Pan's Flight": 2.3, "Pinocchio's Daring Journey": 3.0, "Snow White's Enchanted Wish": 2.0, "Storybook Land Canal Boats": 6.0, "Big Thunder Mountain Railroad": 3.3, "Mark Twain Riverboat": 14.0, "Sailing Ship Columbia": 12.0, "Disneyland Railroad": 22.0, "Great Moments with Mr. Lincoln": 16.0, "Chip 'n' Dale's GADGETcoaster": 0.75, "Mickey & Minnie's Runaway Railway": 5.0, "Haunted Mansion": 9.0, "Pirates of the Caribbean": 16.0, "Millennium Falcon: Smugglers Run": 4.5, "Star Wars: Rise of the Resistance": 18.0, "Astro Orbitor": 1.5, "Autopia": 5.1, "Disneyland Monorail": 15.0, "Finding Nemo Submarine Voyage": 14.0, "Space Mountain": 3.0, "Star Tours – The Adventures Continue": 5.0, "Guardians of the Galaxy – Mission: BREAKOUT!": 2.1, "WEB SLINGERS: A Spider-Man Adventure": 3.4, "Luigi's Rollickin' Roadsters": 1.0, "Mater's Junkyard Jamboree": 1.5, "Radiator Springs Racers": 4.0, "Grizzly River Run": 6.0, "Soarin' Around the World": 4.75, "Mickey's PhilharMagic": 12.0, "Monsters, Inc. Mike & Sulley to the Rescue!": 4.1, "Turtle Talk with Crush": 17.0, "Golden Zephyr": 1.5, "Goofy's Sky School": 1.75, "The Little Mermaid ~ Ariel's Undersea Adventure": 7.0, "Incredicoaster": 1.3, "Inside Out Emotional Whirlwind": 1.5, "Jessie's Critter Carousel": 2.0, "Jumpin' Jellyfish": 1.5, "Pixar Pal-A-Round – Non-Swinging": 9.0, "Pixar Pal-A-Round – Swinging": 9.0, "Toy Story Midway Mania!": 8.0, "Jurassic World — The Ride": 9.5, "Revenge of the Mummy – The Ride": 2.0, "Despicable Me Minion Mayhem": 4.0, "Silly Swirly": 2.0, "The Secret Life of Pets: Off the Leash": 4.0, "The Simpsons Ride™": 4.5, "Mario Kart™: Bowser’s Challenge": 4.0, "Flight of the Hippogriff™": 1.0, "Harry Potter and the Forbidden Journey™": 4.0, "TRANSFORMERS™: The Ride-3D": 4.5, "Studio Tour": 60.0}


def _norm(name):
    return ''.join(c for c in str(name).lower() if c.isalnum())


_NORM_DURATIONS = {_norm(k): v for k, v in RIDE_DURATIONS.items()}


def ride_duration(name):
    return RIDE_DURATIONS.get(name) or _NORM_DURATIONS.get(_norm(name))


def prepare(df):
    """Normalizes raw rows and flags whether each park was operating at each snapshot.

    A park counts as operating when at least a quarter of its rides report open (a
    few attractions report "open" overnight); snapshots outside operating hours are
    ignored for uptime and averages.
    """
    df = df[['fetch_timestamp', 'park_name', 'land', 'ride_name', 'wait_time', 'is_open']].copy()
    df['ts'] = pd.to_datetime(df['fetch_timestamp'], errors='coerce')
    df.dropna(subset=['ts', 'park_name', 'ride_name'], inplace=True)
    df['is_open'] = df['is_open'].astype(str).str.lower() == 'true'
    df['wait_time'] = pd.to_numeric(df['wait_time'], errors='coerce').fillna(0).astype(int)
    df['operating'] = df.groupby(['park_name', 'ts'])['is_open'].transform('mean') >= 0.25
    df['slot'] = (df['ts'].dt.hour * 60 + df['ts'].dt.minute) // SLOT_MINUTES
    return df.drop(columns=['fetch_timestamp'])


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return int(round(v))


def _slot_array(series):
    """Series indexed by slot -> fixed-length list with None for gaps."""
    out = [None] * SLOTS_PER_DAY
    for slot, v in series.items():
        out[int(slot)] = _clean(v)
    return out


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _park_minute_avg(open_rows):
    """Average posted wait across open rides at each snapshot."""
    return open_rows.groupby(['park_name', 'ts'])['wait_time'].mean().reset_index()


def build_history(df, now=None, weeks=8):
    """Writes history.json from all archived + live rows (already passed through prepare)."""
    now = now or df['ts'].max()
    recent = df[df['ts'] >= now - timedelta(weeks=weeks)]
    open_rows = recent[recent['is_open'] & recent['operating']].copy()
    open_rows['dow'] = open_rows['ts'].dt.dayofweek  # Monday = 0
    open_rows['hour'] = open_rows['ts'].dt.hour
    open_rows['date'] = open_rows['ts'].dt.date

    week_rows = open_rows[open_rows['ts'] >= now - timedelta(days=7)]

    parks = {}
    for park, prow in open_rows.groupby('park_name'):
        # Typical park-wide curve: daily average per slot, then quartiles across days.
        per_snap = _park_minute_avg(prow)
        per_snap['date'] = per_snap['ts'].dt.date
        per_snap['slot'] = (per_snap['ts'].dt.hour * 60 + per_snap['ts'].dt.minute) // SLOT_MINUTES
        daily = per_snap[per_snap['ts'] >= now - timedelta(days=28)].groupby(['date', 'slot'])['wait_time'].mean()
        by_slot = daily.groupby(level='slot')
        band = {q: _slot_array(by_slot.quantile(p)) for q, p in (('p25', .25), ('p50', .5), ('p75', .75))}

        rides = {}
        for ride, rrow in prow.groupby('ride_name'):
            cells = rrow.groupby(['dow', 'hour'])['wait_time'].agg(['mean', 'count'])
            heat = [[None] * 24 for _ in range(7)]
            for (dow, hour), c in cells.iterrows():
                if c['count'] >= 3:
                    heat[int(dow)][int(hour)] = _clean(c['mean'])

            hourly = rrow.groupby('hour')['wait_time'].agg(['mean', 'count'])
            hourly = hourly[hourly['count'] >= 24]
            best = None
            if not hourly.empty:
                h = hourly['mean'].idxmin()
                best = {'hour': int(h), 'wait': _clean(hourly.loc[h, 'mean'])}

            wk = week_rows[(week_rows['park_name'] == park) & (week_rows['ride_name'] == ride)]
            rides[ride] = {
                'heat': heat,
                'best': best,
                'avg': _clean(rrow['wait_time'].mean()),
                'profile': _slot_array(wk.groupby('slot')['wait_time'].mean()),
            }
        parks[park] = {'band': band, 'rides': rides}

    _write_json(HISTORY_JSON, {
        'generated': TZ.localize(now.to_pydatetime()).isoformat(),
        'weeks': weeks,
        'slotMinutes': SLOT_MINUTES,
        'parks': parks,
    })


def _load_history():
    try:
        with open(HISTORY_JSON, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'parks': {}}


def build_live(df):
    """Writes live.json from the rolling CSV rows (already passed through prepare)."""
    if df.empty:
        return
    history = _load_history()
    latest_overall = df['ts'].max()
    week = df[df['ts'] >= latest_overall - timedelta(days=7)]

    parks = {}
    for park, prow in week.groupby('park_name'):
        latest = prow['ts'].max()
        snap = prow[prow['ts'] == latest]
        operating = bool(snap['is_open'].mean() >= 0.25)
        # A park "day" runs 4am-4am so after-midnight hours stay with the night before.
        day_of = lambda ts: (ts - timedelta(hours=4)).dt.date
        today = prow[day_of(prow['ts']) == (latest - timedelta(hours=4)).date()]
        hist_rides = history.get('parks', {}).get(park, {}).get('rides', {})

        today_open = today[today['is_open'] & today['operating']]
        snaps = _park_minute_avg(today_open)
        snaps['slot'] = (snaps['ts'].dt.hour * 60 + snaps['ts'].dt.minute) // SLOT_MINUTES
        park_today = _slot_array(snaps.groupby('slot')['wait_time'].mean())

        rides = []
        for _, r in snap.sort_values('ride_name').iterrows():
            name = r['ride_name']
            rw = prow[prow['ride_name'] == name]
            during_hours = rw[rw['operating']]
            uptime = _clean(during_hours['is_open'].mean() * 100) if len(during_hours) else None
            ever_open = bool(rw['is_open'].any())

            h = hist_rides.get(name, {})
            typical = None
            if h.get('heat'):
                typical = h['heat'][latest.dayofweek][latest.hour]
            # Rides with no history at this hour (e.g. night-only Halloween mazes) are
            # simply not scheduled now rather than broken down.
            usually_runs_now = typical is not None or not h.get('heat')

            if r['is_open']:
                status = 'open'
            elif not ever_open:
                status = 'refurb'
            elif operating and usually_runs_now:
                status = 'down'
            else:
                status = 'closed'

            down_since = None
            if status == 'down':
                rt = today[today['ride_name'] == name].sort_values('ts')
                opened = rt[rt['is_open']]
                if not opened.empty:
                    after = rt[rt['ts'] > opened['ts'].max()]
                    if not after.empty:
                        down_since = after['ts'].min().strftime('%H:%M')
                else:
                    down_since = 'open'  # hasn't run since the park opened

            rt_open = today[(today['ride_name'] == name) & today['is_open']]
            spark = _slot_array(rt_open.groupby('slot')['wait_time'].mean())

            dur = ride_duration(name)
            wait = int(r['wait_time'])
            rides.append({
                'name': name,
                'land': r['land'],
                'status': status,
                'wait': wait if status == 'open' else None,
                'typical': typical,
                'downSince': down_since,
                'uptime': uptime,
                'eff': round(dur / (wait + dur) * 100) if dur and status == 'open' else None,
                'duration': dur,
                'best': h.get('best'),
                'spark': spark,
            })

        parks[park] = {
            'updated': latest.strftime('%Y-%m-%dT%H:%M:%S'),
            'operating': operating,
            'today': park_today,
            'rides': rides,
        }

    _write_json(LIVE_JSON, {
        'generated': TZ.localize(latest_overall.to_pydatetime()).isoformat(),
        'slotMinutes': SLOT_MINUTES,
        'parks': parks,
    })


if __name__ == '__main__':
    # Manual rebuild of both files: python build_dashboard.py
    import glob
    frames = [pd.read_parquet(f) for f in sorted(glob.glob('history/*.parquet'))]
    live = pd.read_csv('wait_times.csv')
    all_rows = prepare(pd.concat(frames + [live], ignore_index=True))
    all_rows = all_rows.drop_duplicates(subset=['ts', 'park_name', 'ride_name'], keep='last')
    build_history(all_rows)
    build_live(prepare(live))
    print('Wrote', HISTORY_JSON, 'and', LIVE_JSON)
