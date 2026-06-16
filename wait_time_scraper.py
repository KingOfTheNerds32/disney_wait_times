import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import pytz

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
        if os.path.exists(master_csv_file) and os.path.getsize(master_csv_file) > 0:
            try:
                existing_df = pd.read_csv(master_csv_file)
                combined_df = pd.concat([existing_df, new_data_df], ignore_index=True)
            except Exception:
                combined_df = new_data_df
        else:
            combined_df = new_data_df

        # 'coerce' turns any corrupted or broken timestamp strings into NaT (Not a Time) values safely
        combined_df['fetch_timestamp'] = pd.to_datetime(combined_df['fetch_timestamp'], errors='coerce')
        
        # Drop any rows that couldn't be parsed so they don't break the rest of the script
        combined_df.dropna(subset=['fetch_timestamp'], inplace=True)

        combined_df.drop_duplicates(subset=['fetch_timestamp', 'ride_name'], keep='last', inplace=True)

        # =========================================================================
        # TIER 1: UPDATE HISTORICAL PARQUET ARCHIVE
        # =========================================================================
        os.makedirs('history', exist_ok=True)
        combined_df['year_month'] = combined_df['fetch_timestamp'].dt.strftime('%Y_%m')

        for year_month, group in combined_df.groupby('year_month'):
            history_parquet = f'history/wait_times_{year_month}.parquet'
            
            if os.path.exists(history_parquet):
                try:
                    hist_exist = pd.read_parquet(history_parquet)
                    hist_exist['fetch_timestamp'] = pd.to_datetime(hist_exist['fetch_timestamp'])
                    final_hist = pd.concat([hist_exist, group], ignore_index=True)
                except Exception:
                    final_hist = group
            else:
                final_hist = group
                
            final_hist.drop_duplicates(subset=['fetch_timestamp', 'ride_name'], keep='last', inplace=True)
            
            if 'year_month' in final_hist.columns:
                final_hist = final_hist.drop(columns=['year_month'])
                
            final_hist.to_parquet(history_parquet, index=False, compression='snappy')

        # =========================================================================
        # TIER 2: PRUNE LIVE DASHBOARD CSV (LAST 14 DAYS ONLY)
        # =========================================================================
        cutoff_date = datetime.now() - timedelta(days=14)
        live_dash_df = combined_df[combined_df['fetch_timestamp'] >= cutoff_date].copy()

        if 'year_month' in live_dash_df.columns:
            live_dash_df.drop(columns=['year_month'], inplace=True)

        # This will overwrite the local 100MB file with a tiny ~2MB file before git push runs!
        live_dash_df.to_csv(master_csv_file, index=False)
        print(f"Logged {len(all_rows)} rides. Archive built, live file shrunk successfully.")

if __name__ == "__main__":
    pull_wait_times()
