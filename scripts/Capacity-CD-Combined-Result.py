import pandas as pd
import numpy as np
import boto3
import gc
import os
import time
import re

s3_client = boto3.client('s3')

# --- CONFIGURATIONS ---
SECTOR_URLS = [
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xC-processed-result/',
    's3://neo-advanced-analytics/processed_network_data/sector-calculations/xD-processed-results/'
]
CONGESTION_URL = ['s3://neo-advanced-analytics/processed_network_data/congestion-analysis/']

OUTPUT_BUCKET = 'neo-advanced-analytics'
BASE_OUTPUT_KEY = 'processed_network_data/cd-combined-results/'

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

# --- SMART S3 LOADER (With Partition Injection) ---
def load_parquet_data(folder_urls, columns_to_keep=None):
    all_data = []
    for folder in folder_urls:
        print(f"Scanning: {folder}", flush=True)
        files = get_s3_files_from_url(folder)
        for f in files:
            bucket, key = parse_s3_url(f)
            local_path = f"/tmp/load_{int(time.time()*1000)}.parquet"
            s3_client.download_file(bucket, key, local_path)
            
            try:
                df = pd.read_parquet(local_path)
                
                # Re-inject partitions from folder structure
                year_match = re.search(r'year=(\d+)', key)
                week_match = re.search(r'week=(\d+)', key)
                if 'year' not in df.columns: df['year'] = int(year_match.group(1)) if year_match else 2025
                if 'week' not in df.columns: df['week'] = int(week_match.group(1)) if week_match else 1
                
                # Downcast immediately upon load to stop RAM buildup early
                df['year'] = df['year'].astype('int16')
                df['week'] = df['week'].astype('int8')
                
                # Drop unneeded columns IMMEDIATELY to prevent RAM buildup
                if columns_to_keep:
                    valid_cols = [c for c in columns_to_keep if c in df.columns]
                    if 'year' not in valid_cols: valid_cols.append('year')
                    if 'week' not in valid_cols: valid_cols.append('week')
                    df = df[list(set(valid_cols))]
                
                all_data.append(df)
            except Exception as e:
                print(f"Failed to read {f}: {e}")
            finally:
                if os.path.exists(local_path): os.remove(local_path)
                
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        del all_data
        gc.collect()
        return combined
    return pd.DataFrame()

# --- SHORT ID GENERATOR ---
def make_short_id(sec_id):
    if pd.isna(sec_id): return str(sec_id)
    parts = str(sec_id).split('_')
    if len(parts) >= 3:
        return f"{parts[0]}_{parts[1][0]}_{parts[2]}"
    return sec_id

def generate_cd_combined_file():
    
    # =====================================================================
    # [CRITICAL FIX] STEP 1: LOAD CONGESTION FIRST, THEN ANNIHILATE IT
    # =====================================================================
    print("--- 1. PRE-PROCESSING CONGESTION ANALYSIS ---", flush=True)
    cong_columns = ['zoom_sector_id', 'congested_weeks', 'congested']
    full_cong_df = load_parquet_data(CONGESTION_URL, columns_to_keep=cong_columns)
    
    if not full_cong_df.empty:
        # Extract the tiny mapped version
        cong_slim = full_cong_df[['zoom_sector_id', 'year', 'week', 'congested_weeks', 'congested']].drop_duplicates(subset=['zoom_sector_id', 'year', 'week'])
        congested_only = full_cong_df[full_cong_df['congested'] == True] if 'congested' in full_cong_df.columns else full_cong_df.copy()
        
        # DESTROY the massive original dataset before loading the sector data
        del full_cong_df
        gc.collect()

        print("Exporting Congested_Sectors.csv to S3...", flush=True)
        cong_csv_path = "/tmp/Congested_Sectors.csv"
        congested_only.to_csv(cong_csv_path, index=False, chunksize=50000)
        s3_client.upload_file(cong_csv_path, OUTPUT_BUCKET, f"{BASE_OUTPUT_KEY}Congested_Sectors.csv")
        os.remove(cong_csv_path)
        
        del congested_only
        gc.collect()
    else:
        # Empty placeholder if no congestion data exists
        cong_slim = pd.DataFrame(columns=['zoom_sector_id', 'year', 'week', 'congested_weeks', 'congested'])
        gc.collect()


    # =====================================================================
    # STEP 2: LOAD MASSIVE SECTOR DATA ONLY AFTER RAM IS CLEARED
    # =====================================================================
    print("--- 2. LOADING & EXPORTING HISTORICAL SECTOR DATA ---", flush=True)
    sector_columns = [
        'zoom_sector_id', 'region', 'cluster', 'ibc_macro', 'f1f2f3',
        'eric_data_volume_ul_dl', 'eric_prb_util_rate', 'eric_dl_user_ip_thpt',
        'eric_max_rrc_user', 'max_active_user', 'area_target', 'bau_nic',
        'dataset_type', 'operator'
    ]
    master_df = load_parquet_data(SECTOR_URLS, columns_to_keep=sector_columns)
    
    if master_df.empty:
        print("No sector data found. Aborting export.")
        return
    
    print("Exporting Sector_Metrics.csv to S3...", flush=True)
    sector_csv_path = "/tmp/Sector_Metrics.csv"
    master_df.to_csv(sector_csv_path, index=False, chunksize=50000)
    s3_client.upload_file(sector_csv_path, OUTPUT_BUCKET, f"{BASE_OUTPUT_KEY}Sector_Metrics.csv")
    os.remove(sector_csv_path)

    master_df['short_sector_id'] = master_df['zoom_sector_id'].apply(make_short_id)


    # =====================================================================
    # STEP 3: SAFELY JOIN DATA (IN-PLACE MAPPING)
    # =====================================================================
    print("--- 3. JOINING DATA ---", flush=True)
    if not cong_slim.empty:
        # IN-PLACE INDEX MAPPING: completely avoids pd.merge memory spike
        master_df.set_index(['zoom_sector_id', 'year', 'week'], inplace=True)
        cong_slim.set_index(['zoom_sector_id', 'year', 'week'], inplace=True)
        
        # Direct assignment uses almost zero extra memory
        master_df['congested_weeks'] = cong_slim['congested_weeks']
        master_df['congested'] = cong_slim['congested']
        
        # Reset the index back to normal columns
        master_df.reset_index(inplace=True)
        
        del cong_slim
        gc.collect()
    else:
        master_df['congested_weeks'] = 0
        master_df['congested'] = False

    # =====================================================================
    # STEP 4: FINAL EXPORT
    # =====================================================================
    print("--- 4. FORMATTING FINAL CD COMBINED EXPORT ---", flush=True)
    master_df['area_target'] = master_df.get('area_target', pd.Series()).fillna('Unknown')
    master_df['bau_nic'] = master_df.get('bau_nic', pd.Series()).fillna('Unknown')
    master_df['dataset_type'] = master_df.get('dataset_type', pd.Series()).fillna('Unknown')
    master_df['operator'] = master_df.get('operator', pd.Series()).fillna('Unknown')
    master_df['congested_weeks'] = master_df['congested_weeks'].fillna(0).astype(int)
    master_df['is_congested'] = master_df['congested'].fillna(False).astype(bool)

    final_columns = [
        'year', 'week', 'zoom_sector_id', 'short_sector_id',
        'region', 'cluster', 'ibc_macro', 'f1f2f3',
        'eric_data_volume_ul_dl', 'eric_prb_util_rate', 'eric_dl_user_ip_thpt',
        'eric_max_rrc_user', 'max_active_user',
        'area_target', 'bau_nic', 'dataset_type', 'operator',
        'congested_weeks', 'is_congested'
    ]
    
    master_df = master_df[[c for c in final_columns if c in master_df.columns]]

    print(f"Exporting {len(master_df)} rows to CD_Combined_Results.csv...", flush=True)
    local_cd_path = "/tmp/CD_Combined_Results.csv"
    master_df.to_csv(local_cd_path, index=False, chunksize=50000)
    
    cd_s3_key = f"{BASE_OUTPUT_KEY}CD_Combined_Results.csv"
    print(f"Uploading to s3://{OUTPUT_BUCKET}/{cd_s3_key}...", flush=True)
    s3_client.upload_file(local_cd_path, OUTPUT_BUCKET, cd_s3_key)
    os.remove(local_cd_path)
    
    print("SUCCESS: CD Combined, Sector Metrics, and Congested Sectors saved to Data Lake!", flush=True)

if __name__ == '__main__':
    generate_cd_combined_file()
