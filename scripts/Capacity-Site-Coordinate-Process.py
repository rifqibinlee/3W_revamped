import pandas as pd
import numpy as np
import boto3
import re
import os
import time
import gc

s3_client = boto3.client('s3')

# Splits S3 URL for easy read
def parse_s3_url(s3_url):
    clean_url = s3_url.replace("s3://", "")
    parts = clean_url.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix

def get_s3_files_from_url(s3_url, extensions=('.csv', '.xls', '.xlsx', '.xlsb')):
    bucket, prefix = parse_s3_url(s3_url)
    files = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].lower().endswith(extensions):
                    files.append(f"s3://{bucket}/{obj['Key']}")
    return files

# Clean Site ID whenever encountered dash or underscore
def clean_site_id(sid):
    if pd.isna(sid): return None
    site_str = str(sid).strip().upper()
    base_id = re.split(r'[_ -]', site_str)[0]
    return base_id
    
# Input and Output file configurations
INPUT_URL = 's3://neo-advanced-analytics/site_coverage_params/locationData/'
OUTPUT_URL = 's3://neo-advanced-analytics/processed_network_data/site-coordinates/'

# Keywords mapping to fetch data from dataset
SITE_KEYWORDS = ['site', 'site_id', 'site id', 'location', 'location_id', 'code', 'id', 'site id(new)']
LAT_KEYWORDS = ['latitude', 'lat', 'y_coord', 'north']
LON_KEYWORDS = ['longitude', 'long', 'lng', 'x_coord', 'east']

# Data Processing
def process_site_coordinates():
    print(f"Gathering geo-location datasets from: {INPUT_URL}", flush=True)
    geo_files = get_s3_files_from_url(INPUT_URL)
    
    all_sites_list = []

    def extract_geo_data(df):
        if df is None or df.empty: return
        
        df.columns = df.columns.astype(str).str.lower().str.strip() \
            .str.replace(' ', '_', regex=False) \
            .str.replace('(', '', regex=False) \
            .str.replace(')', '', regex=False) \
            .str.replace('/', '_', regex=False)
        
        site_col = lat_col = lon_col = region_col = cluster_col = None
        
        for c in df.columns:
            cl = str(c).lower().strip()
            if site_col is None and any(k == cl or k in cl for k in SITE_KEYWORDS): site_col = c
            if lat_col is None and any(k == cl or k in cl for k in LAT_KEYWORDS): lat_col = c
            if lon_col is None and any(k == cl or k in cl for k in LON_KEYWORDS): lon_col = c
            if region_col is None and 'region' in cl: region_col = c
            if cluster_col is None and ('cluster' in cl or 'district' in cl): cluster_col = c
        
        if not (site_col and lat_col and lon_col): return
        
        cols_to_keep = {site_col: 'site_id', lat_col: 'latitude', lon_col: 'longitude'}
        if region_col: cols_to_keep[region_col] = 'region'
        if cluster_col: cols_to_keep[cluster_col] = 'cluster'
        
        working_df = df[list(cols_to_keep.keys())].rename(columns=cols_to_keep)
        
        working_df['site_id'] = working_df['site_id'].apply(clean_site_id)
        working_df['latitude'] = pd.to_numeric(working_df['latitude'], errors='coerce')
        working_df['longitude'] = pd.to_numeric(working_df['longitude'], errors='coerce')
        working_df = working_df.dropna(subset=['site_id', 'latitude', 'longitude'])
        
        if 'region' not in working_df.columns: working_df['region'] = None
        if 'cluster' not in working_df.columns: working_df['cluster'] = None
        
        all_sites_list.append(working_df[['site_id', 'region', 'cluster', 'latitude', 'longitude']])
    
    for file_url in geo_files:
        print(f"Processing file: {file_url}", flush=True)
        bucket, key = parse_s3_url(file_url)
        local_path = f"/tmp/geo_{int(time.time())}_{os.path.basename(key)}"
        s3_client.download_file(bucket, key, local_path)
        
        try:
            if local_path.lower().endswith('.csv'):
                for chunk in pd.read_csv(local_path, chunksize=50000, low_memory=False):
                    extract_geo_data(chunk)
                    del chunk
                    gc.collect()
            else:
                if local_path.lower().endswith('.xlsb'):
                    xls = pd.ExcelFile(local_path, engine='pyxlsb')
                else:
                    xls = pd.ExcelFile(local_path)
                    
                for sheet in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet)
                    extract_geo_data(df)
                    del df
                    gc.collect()
                xls.close()
                
        except Exception as e:
            print(f"Error processing {file_url}: {e}", flush=True)
        finally:
            if os.path.exists(local_path): os.remove(local_path)
            gc.collect() 

    if all_sites_list:
        final_sites_df = pd.concat(all_sites_list, ignore_index=True)
        final_sites_df = final_sites_df.drop_duplicates(subset=['site_id'], keep='last')
        
        # =========================================================
        # --- STRICT DATA TYPING (PYARROW FIX) ---
        # =========================================================
        # Force string types to prevent PyArrow from choking on mixed integers/strings
        final_sites_df['site_id'] = final_sites_df['site_id'].astype(str)
        final_sites_df['region'] = final_sites_df['region'].fillna("Unknown").astype(str)
        final_sites_df['cluster'] = final_sites_df['cluster'].fillna("Unknown").astype(str)
        
        # Ensure coordinates are floats
        final_sites_df['latitude'] = final_sites_df['latitude'].astype(float)
        final_sites_df['longitude'] = final_sites_df['longitude'].astype(float)

        print(f"Extracted {len(final_sites_df)} unique sites. Saving to Parquet...", flush=True)
        
        final_sites_df.to_parquet(
            f"{OUTPUT_URL}site_coordinates.parquet", 
            engine='pyarrow', 
            compression='snappy', 
            index=False
        )
        print("Site Coordinates successfully written to S3!", flush=True)
    else:
        print("No valid site coordinates found in the provided files.", flush=True)

if __name__ == '__main__':
    process_site_coordinates()
