import pandas as pd
import numpy as np
import boto3
import gc
from datetime import date, timedelta
import time
import os
import re
from sklearn.linear_model import LinearRegression

s3_client = boto3.client('s3')

# --- CONFIGURATIONS ---
INPUT_URLS = [
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xC-processed-result/',
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xD-processed-results/'
]

# [FIX 1] Base URL so we can dynamically attach xC/xD folder names
BASE_OUTPUT_URL = 's3://neo-advanced-analytics/processed_network_data/forecast-results/'

FORECAST_HORIZON = 52

def parse_s3_url(s3_url):
    clean_url = s3_url.replace("s3://", "")
    parts = clean_url.split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")

def get_s3_files_from_url(s3_url, extensions=('.parquet')):
    bucket, prefix = parse_s3_url(s3_url)
    files = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].lower().endswith(extensions):
                    files.append(f"s3://{bucket}/{obj['Key']}")
    return files

def get_iso_date(year, week):
    try: return date.fromisocalendar(int(year), int(week), 1)
    except: return None

# --- STREAMING S3 UPLOAD HELPER ---
def process_and_upload_chunk(chunk_list, batch_num):
    if not chunk_list: return
    
    df_chunk = pd.DataFrame(chunk_list)
    
    summary_df = df_chunk.groupby('zoom_sector_id')['congested'].sum().reset_index()
    summary_df = summary_df.rename(columns={'congested': 'forecast_congested_weeks'})
    summary_df['month_congested'] = summary_df['forecast_congested_weeks'] >= 3
    
    df_chunk = df_chunk.merge(summary_df, on='zoom_sector_id', how='left')

    df_chunk['zoom_sector_id_override'] = df_chunk['zoom_sector_id_override'].astype(str)
    df_chunk['congested'] = df_chunk['congested'].astype(bool)
    df_chunk['month_congested'] = df_chunk['month_congested'].astype(bool)

    # =====================================================================
    # [FIX 2] SPLIT BY DATASET TYPE AND ROUTE TO RESPECTIVE S3 FOLDERS
    # =====================================================================
    for d_type, d_group in df_chunk.groupby('dataset_type'):
        safe_d_type = str(d_type).strip() if pd.notna(d_type) else 'Unknown'
        target_s3_url = f"{BASE_OUTPUT_URL}{safe_d_type}-forecast-result/"
        
        print(f"Uploading Batch {batch_num} for {safe_d_type} ({len(d_group)} rows) directly to S3...", flush=True)
        
        d_group.to_parquet(
            target_s3_url, 
            engine='pyarrow', 
            compression='snappy', 
            index=False,
            partition_cols=['year', 'week']
        )
        
    print(f"Batch {batch_num} uploaded successfully. Emptying RAM...", flush=True)

def process_predictive_forecasts():
    all_sectors_data = []

    # --- 1. LOAD AGGREGATED SECTOR DATA ---
    for folder in INPUT_URLS:
        print(f"Scanning for Parquet files in: {folder}", flush=True)
        files = get_s3_files_from_url(folder)
        
        for file_url in files:
            bucket, key = parse_s3_url(file_url)
            local_path = f"/tmp/fcast_{int(time.time()*1000)}.parquet"
            s3_client.download_file(bucket, key, local_path)
            
            try:
                df = pd.read_parquet(local_path)
                
                # =========================================================
                # [FIX 3] FORCE INJECT S3 PARTITION WEEKS
                # =========================================================
                year_match = re.search(r'year=(\d+)', key)
                week_match = re.search(r'week=(\d+)', key)
                
                if year_match: df['year'] = int(year_match.group(1))
                elif 'year' not in df.columns: df['year'] = 2026
                    
                if week_match: df['week'] = int(week_match.group(1))
                elif 'week' not in df.columns: df['week'] = 1
                    
                all_sectors_data.append(df)
            except Exception as e:
                print(f"Error reading {file_url}: {e}", flush=True)
            finally:
                if os.path.exists(local_path): os.remove(local_path)
                
    if not all_sectors_data: return
        
    master_df = pd.concat(all_sectors_data, ignore_index=True)
    del all_sectors_data
    gc.collect()
    
    master_df['user_metric'] = np.where(
        master_df['dataset_type'] == 'xC',
        master_df['eric_max_rrc_user'],
        master_df['max_active_user']
    )
    master_df['user_metric'] = pd.to_numeric(master_df['user_metric'], errors='coerce').fillna(0)
    master_df['week'] = pd.to_numeric(master_df['week'], errors='coerce').fillna(1).astype(int)
    master_df['year'] = pd.to_numeric(master_df['year'], errors='coerce').fillna(2026).astype(int)
    
    # Sort guarantees the AI sees the true chronological order ending at Week 52
    master_df = master_df.sort_values(by=['zoom_sector_id', 'year', 'week'])

    global_max_year = int(master_df['year'].max())
    global_max_week = int(master_df[master_df['year'] == global_max_year]['week'].max())
    global_base_date = get_iso_date(global_max_year, global_max_week)

    print(f"Data loaded: {len(master_df)} rows. Global End Date: Year {global_max_year} Week {global_max_week}. Running AI...", flush=True)

    # --- 2. VECTORIZED SKLEARN WITH DIRECT S3 STREAMING ---
    grouped = master_df.groupby('zoom_sector_id')
    
    forecast_results_chunk = []
    sector_count = 0
    batch_index = 0

    for sector_id, group in grouped:
        n_points = len(group)
        if n_points < 2: continue 

        last_row = group.iloc[-1]
        ibc_macro = last_row.get('ibc_macro', 'Unknown')
        f1f2f3 = last_row.get('f1f2f3', 'Unknown')
        dataset_type = last_row.get('dataset_type', 'Unknown')
        operator = last_row.get('operator', 'Unknown')
        zoom_override = last_row.get('zoom_sector_id_override', None)
        avg_user_count = group['user_metric'].mean()

        x = np.arange(1, n_points + 1)
        x_reshaped = x.reshape(-1, 1) 

        def calc_sklearn_slr(y_series):
            y = y_series.fillna(0).values
            model = LinearRegression()
            model.fit(x_reshaped, y)
            slope = model.coef_[0]
            intercept = model.intercept_
            return slope, intercept

        slope_vol, int_vol = calc_sklearn_slr(group['eric_data_volume_ul_dl'])
        slope_prb, int_prb = calc_sklearn_slr(group['eric_prb_util_rate'])
        slope_thp, int_thp = calc_sklearn_slr(group['eric_dl_user_ip_thpt'])

        # With the fix above, this will perfectly capture the true final week (e.g. 52)
        last_year = int(last_row['year'])
        last_week = int(last_row['week'])
        sector_end_date = get_iso_date(last_year, last_week)
        
        if not sector_end_date or not global_base_date: continue
    
        week_gap = (global_base_date - sector_end_date).days // 7
        if week_gap < 0: week_gap = 0 # Safety catch

        future_offsets = np.arange(1, FORECAST_HORIZON + 1)
        future_x = np.arange(n_points + week_gap + 1, n_points + week_gap + 1 + FORECAST_HORIZON)
        
        for i, f_x in enumerate(future_x):
            future_date = global_base_date + timedelta(days=int(future_offsets[i] * 7))
            f_year, f_week, _ = future_date.isocalendar()
            f_month = future_date.month
            
            pred_vol_c = max(0.0, (slope_vol * f_x) + int_vol)
            pred_prb_c = max(0.0, min(100.0, (slope_prb * f_x) + int_prb))
            pred_thp_c = max(0.0, (slope_thp * f_x) + int_thp)

            is_congested = bool((pred_prb_c >= 80.0) and (pred_thp_c < 3.0) and (avg_user_count >= 120))

            forecast_results_chunk.append({
                'zoom_sector_id': sector_id,
                'zoom_sector_id_override': str(zoom_override) if pd.notna(zoom_override) else None,
                'week': f"{int(f_week):02d}",
                'year': int(f_year),
                'month': int(f_month),
                'ibc_macro': ibc_macro,
                'f1f2f3': f1f2f3,
                'predicted_eric_data_volume_ul_dl': float(pred_vol_c),
                'predicted_eric_prb_util_rate': float(pred_prb_c),
                'predicted_eric_dl_user_ip_thpt': float(pred_thp_c),
                'congested': is_congested,
                'data_points_used': int(n_points),
                'dataset_type': dataset_type,
                'operator': operator
            })

        sector_count += 1
        if sector_count % 2000 == 0:
            batch_index += 1
            process_and_upload_chunk(forecast_results_chunk, batch_index)
            forecast_results_chunk = [] 
            gc.collect()

    if forecast_results_chunk:
        batch_index += 1
        process_and_upload_chunk(forecast_results_chunk, batch_index)
        del forecast_results_chunk
        gc.collect()

    print(f"All {sector_count} sectors calculated and streamed to S3 Data Lake successfully!", flush=True)

if __name__ == '__main__':
    process_predictive_forecasts()
