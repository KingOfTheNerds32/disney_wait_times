import requests
import pandas as pd
from datetime import datetime
import os
import pytz

def pull_wait_times():
    # Disneyland (16), DCA (17), and Universal Studios Hollywood (13)
    parks = {
        16: "Disneyland",
        17: "Disney California Adventure",
        13: "Universal Studios Hollywood"
    }
    
    all_rows = []
    tz = pytz.timezone('America/Los_Angeles')
    fetch_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    
    for park_id, park_name in parks.items():
        url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
        try:
            # Added timeout=30 to prevent the script from hanging
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
        df = pd.DataFrame(all_rows)
        file_path = 'wait_times.csv'
        # Append to CSV, or create it if it doesn't exist
        df.to_csv(file_path, mode='a', header=not os.path.exists(file_path), index=False)
        print(f"Logged {len(all_rows)} rides at {fetch_time}")

if __name__ == "__main__":
    pull_wait_times()
