import requests
import pandas as pd
from datetime import datetime
import os

def pull_wait_times():
    # IDs for Disneyland (16) and Disney California Adventure (17)
    parks = {
        16: "Disneyland",
        17: "Disney California Adventure"
    }
    
    all_rows = []
    
    for park_id, park_name in parks.items():
        url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
        try:
            response = requests.get(url)
            data = response.json()
            
            for land in data.get('lands', []):
                land_name = land.get('name')
                for ride in land.get('rides', []):
                    all_rows.append({
                        'fetch_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M"),
                        'park_name': park_name,
                        'land': land_name,
                        'ride_id': ride.get('id'),
                        'ride_name': ride.get('name'),
                        'wait_time': ride.get('wait_time'),
                        'is_open': ride.get('is_open'),
                        'last_updated': ride.get('last_updated')
                    })
        except Exception as e:
            print(f"Error fetching park {park_id}: {e}")

    if all_rows:
        df = pd.DataFrame(all_rows)
        file_path = 'wait_times.csv'
        # Append to CSV, or create it if it doesn't exist
        df.to_csv(file_path, mode='a', header=not os.path.exists(file_path), index=False)

if __name__ == "__main__":
    pull_wait_times()
