import pandas as pd
import numpy as np
import boto3
import gc
from datetime import date
import time
import os
import re

s3_client = boto3.client('s3')

# --- CONFIGURATIONS ---
INPUT_URLS = [
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xC-processed-result/',
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xD-processed-results/'
]
OUTPUT_URL = 's3://neo-advanced-analytics/processed_network_data/congestion-analysis/'

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

def process_congestion_analysis():
    all_sectors_data = []

    # --- 1. LOAD ALL PROCESSED SECTOR CALCULATIONS ---
    # Define categorical columns to compress immediately upon load
    cat_cols = ['zoom_sector_id', 'region', 'ibc_macro', 'f1f2f3', 'area_target', 'bau_nic', 'operator', 'site_id', 'cluster', 'vendor']
    
    for folder in INPUT_URLS:
        print(f"Scanning for Parquet files in: {folder}", flush=True)
        files = get_s3_files_from_url(folder)
        current_dataset = 'xC' if 'xC' in folder else 'xD'
        
        for file_url in files:
            bucket, key = parse_s3_url(file_url)
            local_path = f"/tmp/calc_{int(time.time()*1000)}.parquet"
            s3_client.download_file(bucket, key, local_path)
            
            try:
                df = pd.read_parquet(local_path)
                
                # --- IMMEDIATE OPTIMIZATION BEFORE APPENDING ---
                # 1. Cast strings to categoricals immediately to save ~90% memory per chunk
                for c in cat_cols:
                    if c in df.columns:
                        df[c] = df[c].fillna("Unknown").astype('category')
                        
                # 2. Standardize Region Early & Drop Unknowns
                if 'region' in df.columns:
                    df = df[~df['region'].astype(str).str.upper().str.strip().isin(['0', 'UNKNOWN', 'NAN', 'NONE'])]
                    
                # 3. Downcast Numeric Types Early
                float_cols = ['eric_prb_util_rate', 'eric_dl_user_ip_thpt', 'eric_data_volume_ul_dl']
                for c in float_cols:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype(np.float32)
                        
                if 'eric_max_rrc_user' in df.columns:
                    df['eric_max_rrc_user'] = pd.to_numeric(df['eric_max_rrc_user'], errors='coerce').fillna(0).astype(np.int32)
                if 'max_active_user' in df.columns:
                    df['max_active_user'] = pd.to_numeric(df['max_active_user'], errors='coerce').fillna(0).astype(np.int32)

                # Parse partition logic
                year_match = re.search(r'year=(\d+)', key)
                week_match = re.search(r'week=(\d+)', key)
                
                if year_match: df['year'] = int(year_match.group(1))
                else: 
                    if 'year' not in df.columns: df['year'] = 2025
                    
                if week_match: df['week'] = int(week_match.group(1))
                else:
                    if 'week' not in df.columns: df['week'] = 1
                
                df['dataset_type'] = current_dataset
                all_sectors_data.append(df)
                
            except Exception as e:
                print(f"Error reading {file_url}: {e}", flush=True)
            finally:
                if os.path.exists(local_path): os.remove(local_path)
                
    if not all_sectors_data:
        print("No sector data found to analyze. Exiting.", flush=True)
        return
        
    master_df = pd.concat(all_sectors_data, ignore_index=True)
    del all_sectors_data
    gc.collect()

    # --- [FIX 1] RE-COMPRESS CATEGORICALS IMMEDIATELY ---
    # pd.concat reverts categories to objects if chunks differ slightly. 
    # We must instantly re-cast to compress master_df and survive the next steps.
    str_cols = ['zoom_sector_id', 'region', 'ibc_macro', 'f1f2f3', 'area_target', 'bau_nic', 'dataset_type', 'operator', 'site_id', 'cluster', 'vendor']
    for c in str_cols:
        if c in master_df.columns:
            master_df[c] = master_df[c].fillna("Unknown").astype('category')
    gc.collect()

    print(f"Data loaded: {len(master_df)} records after cleaning. Starting Analysis...", flush=True)

    # --- [CHANGED] 3. OPTIMIZE NUMERIC TYPES ---
    float_cols = ['eric_prb_util_rate', 'eric_dl_user_ip_thpt', 'eric_data_volume_ul_dl']
    for c in float_cols:
        if c in master_df.columns:
            master_df[c] = pd.to_numeric(master_df[c], errors='coerce').fillna(0.0).astype(np.float32)

    if 'eric_max_rrc_user' in master_df.columns:
        master_df['eric_max_rrc_user'] = pd.to_numeric(master_df['eric_max_rrc_user'], errors='coerce').fillna(0).astype(np.int32)
    if 'max_active_user' in master_df.columns:
        master_df['max_active_user'] = pd.to_numeric(master_df['max_active_user'], errors='coerce').fillna(0).astype(np.int32)

    # ZERO VALUE DROPPER
    master_df = master_df[~((master_df['eric_prb_util_rate'] == 0.0) & 
                            (master_df['eric_dl_user_ip_thpt'] == 0.0) & 
                            (master_df['eric_data_volume_ul_dl'] == 0.0))]

    # --- 4. VECTORIZED MONTH CALC ---
    master_df['month'] = ((master_df['week'] - 1) // 4 + 1).clip(1, 12).astype(np.int8)

    # --- [FIX 2] CONGESTION ANALYSIS (AVOID STRING COPIES) ---
    # Using case=False natively on categoricals stops Pandas from allocating huge string arrays
    is_urban_kmc = master_df['area_target'].str.contains('urban|kmc', case=False, na=False)
    is_nic = master_df['bau_nic'].str.contains('nic', case=False, na=False)

    c1 = is_urban_kmc & is_nic & (master_df['eric_prb_util_rate'] >= 80.0) & (master_df['eric_dl_user_ip_thpt'] < 7.0)
    c2 = is_urban_kmc & ~is_nic & (master_df['eric_prb_util_rate'] >= 80.0) & (master_df['eric_dl_user_ip_thpt'] < 5.0)
    c3 = ~is_urban_kmc & (master_df['eric_prb_util_rate'] >= 92.0) & (master_df['eric_dl_user_ip_thpt'] < 3.0)

    master_df['congested'] = c1 | c2 | c3

    master_df.sort_values(by=['zoom_sector_id', 'year', 'week'], inplace=True)
    
    # --- [FIX 3] observed=True ---
    # Prevents Pandas from building a multi-index cartesian product in memory for Categoricals!
    master_df['congested_weeks'] = master_df.groupby('zoom_sector_id', observed=True)['congested'].cumsum().fillna(0).astype(np.int32)
    master_df['congested_count_month'] = master_df.groupby(['zoom_sector_id', 'year', 'month'], observed=True)['congested'].transform('sum').fillna(0).astype(np.int32)

    # --- 7. ROUTING TO S3 (MEMORY OPTIMIZED & CHUNKED) ---
    print("Routing Congestion Analysis to respective S3 folders...", flush=True)
    
    target_xC = f"{OUTPUT_URL}xC-congestion-result/"
    target_xD = f"{OUTPUT_URL}xD-congestion-result/"
    
    # Group by dataset_type ALONG with year and week directly on master_df.
    # This prevents creating massive temporary DataFrame copies.
    for (ds_type, yr, wk), group in master_df.groupby(['dataset_type', 'year', 'week']):
        target_folder = target_xC if ds_type == 'xC' else target_xD
        
        # --- [INSERT THIS CHANGE] ZERO-PAD THE WEEK FOR S3 ALPHABETICAL SORTING ---
        padded_wk = str(wk).zfill(2) 
        partition_path = f"{target_folder}year={yr}/week={padded_wk}/data_{int(time.time()*1000)}.parquet"
        # -------------------------------------------------------------------------
        
        group.drop(columns=['dataset_type', 'year', 'week']).to_parquet(
            partition_path, 
            engine='pyarrow', 
            compression='snappy', 
            index=False
        )
        del group
        
    del master_df
    gc.collect()
    print("Congestion Analysis successfully split and saved!", flush=True)

if __name__ == '__main__':
    process_congestion_analysis()
