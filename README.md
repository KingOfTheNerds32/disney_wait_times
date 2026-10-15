# disney_wait_times

# Theme Park Telemetry & Wait Time Analytics

An automated pipeline and lightweight analytics dashboard tracking live attraction wait times and operational uptime across **Disneyland**, **Disney California Adventure**, and **Universal Studios Hollywood**.

The system operates entirely on free, serverless infrastructure—using an external cron trigger, GitHub Actions runners for ingestion, a dual-tier storage strategy (CSV + Parquet), and a static GitHub Pages frontend.

---

## Architecture Overview

```
                      [cron-job.org]
                            │
               Pings every 5 mins (Webhook)
                            ▼
                  [GitHub Actions Runner]
                            │
              Runs: wait_time_scraper.py
              Pulls: Queue-Times API
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
      [Live Dashboard Tier]     [Historical Tier]
        wait_times.csv          history/*.parquet
      (Rolling last 14 days)    (Monthly Snappy-compressed)
               │
               ▼
      [GitHub Pages UI]
         index.html
     (Vanilla JS + Chart.js)

```

1. **Ingestion Trigger:** An external scheduler (`cron-job.org`) issues a webhook ping (`poll-disney`) every 5 minutes to trigger the GitHub Actions workflow.
2. **Data Scraping & Pruning:** A Python runner executes `wait_time_scraper.py`, fetching live wait times and ride statuses from the public Queue-Times API endpoints.
3. **Dual-Tier Storage Architecture:**
* **Live Tier (`wait_times.csv`):** Dynamically pruned on every run to retain only the **most recent 14 days** (~2–4 MB). This bypasses GitHub's 100 MB single-file limit and ensures the frontend loads immediately.
* **Historical Archive Tier (`history/`):** Historical rows are partitioned by month and saved as binary **Parquet** files (`history/wait_times_YYYY_MM.parquet`) using Snappy compression. This reduces disk storage by ~90% while maintaining an immutable raw record.


4. **Visualization:** Hosted on GitHub Pages via `index.html`. It parses the 14-day CSV client-side using `PapaParse` and visualizes trends using `Chart.js`.

---

## Monitored Destinations

The scraper collects metrics for three Southern California theme parks:

| Destination | Park ID | Included Lands / Areas |
| --- | --- | --- |
| **Disneyland Park** | `16` | Fantasyland, Tomorrowland, Adventureland, Frontierland, New Orleans Square, Star Wars: Galaxy's Edge, Mickey's Toontown, Bayou Country, Main Street U.S.A. |
| **Disney California Adventure** | `17` | Cars Land, Avengers Campus, Pixar Pier, Grizzly Peak, Hollywood Land, Paradise Gardens Park, San Fransokyo Square |
| **Universal Studios Hollywood** | `66` | Full park aggregated (Upper Lot, Lower Lot, Super Nintendo World, Wizarding World of Harry Potter, Minion Land, etc.) |

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

## Key Metrics & Analytical Models

The dashboard exposes two calculated operational metrics:

### 1. Attraction Efficiency Score (%)

Measures the return on time invested for an attraction—identifying rides with lengthy runtimes that justify moderate lines versus short attractions with high queues:

$$\text{Efficiency Score} = \left( \frac{\text{Ride Duration}}{\text{Posted Standby Wait} + \text{Ride Duration}} \right) \times 100$$

*Ride durations are mapped via a static lookup dictionary compiled from verified attraction telemetry (e.g., Pirates of the Caribbean = 16.0 min; Space Mountain = 3.0 min).*

### 2. Operational Reliability & Uptime (%)

Evaluates attraction stability across the preceding 7 days, filtering out temporary breakdowns from long-term scheduled closures:

$$\text{7-Day Uptime} = \left( \frac{\sum \text{Open Snapshots}}{\sum \text{Total Recorded Snapshots}} \right) \times 100$$

* **Refurbishment Detection (`REFURB`):** Attractions reporting `0%` uptime over the entire 7-day window are classified as under scheduled maintenance/refurbishment.
* **Temporary Outage (`CLOSED`):** Attractions currently reporting `is_open = False` that have logged operational cycles within the past week are marked as mid-day breakdowns or standard closing states.

### 3. Consolidated Demand Profiles

The **7-Day Trends** tab normalizes the past week of measurements into a unified 24-hour composite baseline. Each 5-minute bucket calculates the true mathematical average across all 7 days to display standard daily wait time curves without single-day noise.

---

## Local Development & Querying History

### Running the Scraper Manually

Clone the repository and install the runtime dependencies:

```bash
git clone https://github.com/KingOfTheNerds32/disney_wait_times.git
cd disney_wait_times
pip install requests pandas pytz pyarrow
python wait_time_scraper.py

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
3. Keep `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` set in `.github/workflows/main.yml` to prevent runner deprecation warnings.
