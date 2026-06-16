import os
import subprocess
import pandas as pd

def recover_maximum_may_data():
    # List of dates to check, starting from the very end of the active period down to the middle
    dates_to_test = ["2026-05-21", "2026-05-19", "2026-05-17", "2026-05-15"]
    
    for target_date in dates_to_test:
        print(f"Testing historical commit from before {target_date}...")
        commit_cmd = f'git log -n 1 --before="{target_date}" --format="%H" -- wait_times.csv'
        
        try:
            commit_hash = subprocess.check_output(commit_cmd, shell=True).decode('utf-8').strip()
            if not commit_hash:
                continue
            
            # Pull that version to a temporary file
            os.system(f"git show {commit_hash}:wait_times.csv > temp_recovery.csv")
            
            # Try to load it
            df = pd.read_csv('temp_recovery.csv')
            
            # Use 'coerce' to protect against minor row corruptions, but keep the good data around them
            df['fetch_timestamp'] = pd.to_datetime(df['fetch_timestamp'], errors='coerce')
            df.dropna(subset=['fetch_timestamp'], inplace=True)
            
            # Isolate May data
            may_data = df[df['fetch_timestamp'].dt.strftime('%Y_%m') == '2026_05'].copy()
            
            # If we found a massive chunk of data, lock it in!
            if len(may_data) > 1000: 
                print(f"🎯 Success! Found a healthy snapshot with {len(may_data)} rows of May data.")
                
                os.makedirs('history', exist_ok=True)
                target_parquet = 'history/wait_times_2026_05.parquet'
                
                may_data.drop_duplicates(subset=['fetch_timestamp', 'ride_name'], keep='last', inplace=True)
                may_data.to_parquet(target_parquet, index=False, compression='snappy')
                print(f"Saved optimized historical archive to {target_parquet}")
                return # Exit the function completely since we won the biggest jackpot
                
        except Exception as e:
            print(f"Snapshot from {target_date} was unparseable, moving to next option...")
        finally:
            if os.path.exists('temp_recovery.csv'):
                os.remove('temp_recovery.csv')
                
    print("Core recovery loop finished checking options.")

if __name__ == "__main__":
    recover_maximum_may_data()
