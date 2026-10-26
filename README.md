# disney_wait_times

# Theme Park Telemetry & Wait Time Analytics

An automated pipeline and lightweight analytics dashboard tracking live attraction wait times and operational uptime across **Disneyland**, **Disney California Adventure**, **Universal Studios Hollywood**, and **Legoland California**.

The system operates entirely on free, serverless infrastructure—using an external cron trigger, GitHub Actions runners for ingestion, a dual-tier storage strategy (CSV + Parquet), and a static GitHub Pages frontend.

---

## Architecture Overview

```
     [cron-job.org] every 5 min              [GitHub schedule] daily, ~3-4 AM PT
              │                                          │
              ▼                                          ▼
   poll.yml → wait_time_scraper.py           archive.yml → archive.py
     • pulls Queue-Times API                   • merges both CSVs into
     • pulls ThemeParks.wiki API                 history/*.parquet
     • appends to wait_times.csv +
       themeparks.csv
       (rolling 10 days)                       • rebuilds data/history.json
     • rebuilds data/live.json                   (heatmaps, best times,
                                                  typical daily curves)
              │                                          │
              └──────────────┬───────────────────────────┘
                             ▼
                 [GitHub Pages] index.html
          loads data/live.json + data/history.json (~200 KB)
```

1. **Polling (every 5 min):** `cron-job.org` sends a `poll-disney` webhook that runs `.github/workflows/poll.yml`. `wait_time_scraper.py` fetches every park from two sources with the same timestamp:
   * **Queue-Times** → `wait_times.csv`
   * **ThemeParks.wiki** (`themeparks.py`) → `themeparks.csv`: ride status, standby, single rider, and Lightning Lane return times.

   Both CSVs are pruned to the last 10 days, then `data/live.json` is rebuilt via `build_dashboard.py`. A ThemeParks.wiki outage never blocks the Queue-Times data.
2. **Archiving (daily):** `.github/workflows/archive.yml` runs on GitHub's own scheduler, so no extra cron-job.org job is needed. `archive.py` folds each CSV into its monthly Parquet files (`history/wait_times_YYYY_MM.parquet`, `history/themeparks_YYYY_MM.parquet`) and rebuilds `data/history.json`. Each Parquet file is rewritten at most once a day, which keeps git history growth small. Because the CSV holds 10 days, a missed or late daily run loses nothing.
3. **Dashboard:** `index.html` on GitHub Pages loads only the two precomputed JSON files, so it no longer downloads or parses the raw CSV. It refreshes itself every 5 minutes.

The two workflows touch different files (`wait_times.csv` + `data/live.json` vs `history/` + `data/history.json`), so when they push at the same time a `git pull --rebase` always resolves cleanly.

To rebuild both JSON files by hand: `python build_dashboard.py`.

---

## Self-Healing & Alerts

The pipeline is built to keep running unattended and to tell you when it had to step in.

**Automatic recovery**
* **Damaged `wait_times.csv`:** the scraper skips unreadable lines (and recovers from a damaged header line). If the file is unreadable, it is moved to `quarantine/` and a fresh CSV is started, so polling never stops and nothing is deleted.
* **Quarantined files:** the daily archive job salvages their rows into the Parquet archive and removes them. Anything it can't salvage stays in `quarantine/` for a manual look.
* **Push races** between the two workflows are retried with `git pull --rebase`. API hiccups resolve on the next poll.

**Alerts:** a GitHub Issue labeled `pipeline-health` opens when:
* a run recovered from a problem or failed outright (both workflows), or
* the newest data is more than 6 hours old (checked daily by the archive job), which catches polling that stopped entirely, e.g. the cron-job.org job dying.

At most one alert issue is open at a time; while it is open, new problems are added as comments, at most once every 6 hours. GitHub emails you about new issues and comments. Close the issue once you've looked, and a new one opens if problems come back. Requires Issues to be enabled on the repo (Settings → General → Features).

---

## Monitored Destinations

The scraper collects metrics for four Southern California theme parks:

| Destination | Park ID | Included Lands / Areas |
| --- | --- | --- |
| **Disneyland Park** | `16` | Fantasyland, Tomorrowland, Adventureland, Frontierland, New Orleans Square, Star Wars: Galaxy's Edge, Mickey's Toontown, Bayou Country, Main Street U.S.A. |
| **Disney California Adventure** | `17` | Cars Land, Avengers Campus, Pixar Pier, Grizzly Peak, Hollywood Land, Paradise Gardens Park, San Fransokyo Square |
| **Universal Studios Hollywood** | `66` | Full park aggregated (Upper Lot, Lower Lot, Super Nintendo World, Wizarding World of Harry Potter, Minion Land, etc.) |
| **Legoland California** | `279` | Full park. Standby waits and status only: neither source publishes Reserve 'N' Ride return times. |

---

## Data Schema

The live `wait_times.csv` file records the following fields:

| Field | Type | Description |
| --- | --- | --- |
| `fetch_timestamp` | `ISO 8601 String` | Local timestamp of scraper execution (`YYYY-MM-DD HH:MM:SS`, PT). |
| `park_name` | `String` | Target theme park name. |
| `land` | `String` | Designated park land or zone. |
| `ride_name` | `String` | Official attraction name. |
| `wait_time` | `Integer` | Current posted standby wait time in minutes. |
| `is_open` | `Boolean` | Operational status (`True` if open/running, `False` if down/closed). |
| `last_updated` | `ISO 8601 String` | Source API timestamp when the park system last refreshed the line. |

---

## Dashboard

* **All parks:** average posted wait per park vs. what is usual for this time, rides open/down, the longest wait, and the best ride to do right now, plus a sparkline of today vs. a typical day.
* **Park view:**
  * **Worth riding now:** popular rides (usually ≥ 10 min) ranked by how far below their usual wait they are.
  * **Today vs a typical day:** park-wide average wait today, against the median and middle 50% of days over the last 4 weeks. Up to three rides can be pinned onto this chart.
  * **Ride cards:** current wait, colored and labeled by how it compares with the usual wait for this weekday and hour, a sparkline of today (vs. the 7-day average), status ("Down since 2:15pm", "Not running now", "Not open this week"), uptime, efficiency and best time. Filter by land, search, sort, or show open rides only.
* **Lightning Lane:** ride cards show the type (**Multi Pass** or **Single Pass**, the paid per-ride option) and the next return time ("return 2:55pm · in 3h 18m", or "sold out"). Filter to Lightning Lane rides, or sort by soonest return.
* **Ride detail:**
  * standby today from both sources vs. the last 7 days
  * how far out Lightning Lane return times ran through the day
  * weekday × hour heatmaps of standby waits, and of Lightning Lane return times (with usually-sold-out hours marked), over the last 8 weeks

  Ride detail links are shareable (`#park=…&ride=…`).
* **Data sources:** where Queue-Times and ThemeParks.wiki disagree right now, and how often they agree over the last 7 days (waits within 5 min, average gap, open/closed disagreements), park by park and ride by ride.
* Light/dark theme (follows the system by default), phone-friendly layout, "updated N min ago" with a warning when data is stale.

### ThemeParks.wiki data (`themeparks.csv`)

| Field | Description |
| --- | --- |
| `fetch_timestamp` | Same poll timestamp as `wait_times.csv`, so rows line up across sources. |
| `park_name`, `ride_name` | Park (same names as `wait_times.csv`) and attraction. |
| `status` | `OPERATING`, `DOWN`, `CLOSED` or `REFURBISHMENT`. |
| `standby_wait`, `single_rider_wait` | Posted waits in minutes (blank when not offered). |
| `ll_type` | `MP` = Lightning Lane Multi Pass, `ILL` = Lightning Lane Single Pass (paid per ride). |
| `ll_state` | `AVAILABLE`, `FINISHED` (sold out) or another state Disney reports. |
| `ll_return_start`, `ll_return_end` | Current return window (`YYYY-MM-DD HH:MM`, Pacific). |

## Key Metrics

* **Park operating:** a snapshot counts as "operating" when at least 25% of a park's rides report open. Overnight snapshots are excluded from uptime and averages.
* **Usual wait:** average posted wait for that ride at the same weekday and hour over the last 8 weeks, counting only times it was open.
* **7-Day Uptime:** open snapshots ÷ snapshots while the park was operating.
* **Status:** taken from ThemeParks.wiki, which reports Disney's and Universal's own status (`OPERATING`, `DOWN` for an unplanned stop, `CLOSED` for scheduled closures, `REFURBISHMENT`). For rides it doesn't list, status is inferred from Queue-Times: *Down* = closed while the park is operating at an hour the ride normally runs; *Not running now* = closed outside its usual hours or with the park closed; *Not open this week* = no open snapshots in 7 days.
* **Lightning Lane return:** minutes from the snapshot to the earliest available return time (0 = return now). "Sold out" = Disney reports no more return times today.
* **Efficiency Score:** ride duration ÷ (posted wait + ride duration) × 100, using the duration table in `build_dashboard.py`.
* **Best time:** the hour of day with the lowest average wait over 8 weeks (needs at least 24 samples).
* Trend curves are bucketed into 15-minute slots, and only open snapshots are averaged, so closed rides don't drag averages to zero.

---

## Local Development & Querying History

### Running the Pipeline Manually

Clone the repository and install the runtime dependencies:

```bash
git clone https://github.com/KingOfTheNerds32/disney_wait_times.git
cd disney_wait_times
pip install requests pandas pytz pyarrow
python wait_time_scraper.py   # one poll
python archive.py             # fold CSV into Parquet + rebuild history.json

```

### Analyzing Compressed Historical Parquet Data

You can query months of historical data using Python without decompressing raw CSVs:

```python
import pandas as pd

# Load a specific month
df_may = pd.read_parquet("history/wait_times_2026_05.parquet")

# Or read the entire archive across all months at once
import glob
all_history = pd.concat([pd.read_parquet(f) for f in glob.glob("history/*.parquet")])

# Calculate average wait time for Space Mountain
space_mtn = all_history[all_history["ride_name"] == "Space Mountain"]
print(f"Historical Average Wait: {space_mtn['wait_time'].mean():.1f} minutes")

```

---

## Deployment & Verification Checklist

1. Ensure GitHub Actions write permissions are active under **Settings > Actions > General > Workflow permissions** (`Read and write permissions`).
2. Verify GitHub Pages is configured under **Settings > Pages** to deploy from the `/root` directory of your `main` branch.
3. Keep `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` set in the workflows to prevent runner deprecation warnings.
