import pandas as pd
import numpy as np
import boto3
import re
import os
import time
import gc
import math

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

# Step 1: Normalization and Feature Engineering
def clean_site_id(sid):
    if pd.isna(sid): return None
    site_str = str(sid).strip().upper()
    return re.split(r'[_ -]', site_str)[0]

# Predefined Radius Calculations
def calculate_dynamic_radius(row):
    # Default radii based on technology if specific tilt/height data is missing
    tech = str(row.get('technology', '')).upper()
    default_radius = 1500 # Default to 1.5km
    if '2G' in tech: default_radius = 5000
    elif '3G' in tech: default_radius = 3000
    elif '4G' in tech or 'LTE' in tech: default_radius = 1500
    elif '5G' in tech or 'NR' in tech: default_radius = 500
    
    # Check for Femto/Inbuilding overrides
    remark = str(row.get('remark', '')).upper()
    if 'FEMTO' in remark or 'IBC' in remark or 'INBUILDING' in remark:
        return 50 # 50 meters for indoor cells
        
    try:
        height = float(row.get('antenna_height', 0))
        m_tilt = float(row.get('m_tilt', 0))
        e_tilt = float(row.get('e_tilt', 0))
        
        total_tilt = m_tilt + e_tilt
        
        # If we have valid height and downward tilt, use trigonometry
        if height > 0 and total_tilt > 0:
            tilt_rad = math.radians(total_tilt)
            # radius = height / tan(tilt)
            calc_radius = height / math.tan(tilt_rad)
            # Cap at 35,000 meters (35km) to prevent infinite/unrealistic projections
            return min(calc_radius, 35000.0)
    except (ValueError, TypeError):
        pass
        
    return float(default_radius)

# Input and Output file configurations
INPUT_URL = 's3://neo-advanced-analytics/site_coverage_params/locationData/'
OUTPUT_URL = 's3://neo-advanced-analytics/processed_network_data/site-coverage-params/'

# Keywords mapping to fetch data from dataset
SITE_KEYWORDS = ['site', 'site_id', 'site id', 'location', 'code']
CELL_KEYWORDS = ['cell', 'cell_name', 'sector', 'cellname']
AZIMUTH_KEYWORDS = ['azimuth', 'dir', 'orientation']
TECH_KEYWORDS = ['tech', 'technology', 'system', 'band']
HEIGHT_KEYWORDS = ['height', 'ant_height', 'agl', 'antenna_height']
MTILT_KEYWORDS = ['m_tilt', 'mtilt', 'mech_tilt', 'mechanical']
ETILT_KEYWORDS = ['e_tilt', 'etilt', 'elec_tilt', 'electrical']
REMARK_KEYWORDS = ['remark', 'type', 'category']

# Process Site Coverage Calculations
def process_site_coverage():
    print(f"Gathering site coverage datasets from: {INPUT_URL}", flush=True)
    geo_files = get_s3_files_from_url(INPUT_URL)
    
    all_coverage_list = []

    def extract_coverage_data(df):
        if df is None or df.empty: return
        
        # Standardize columns strictly
        df.columns = df.columns.astype(str).str.lower().str.strip() \
            .str.replace(' ', '_', regex=False) \
            .str.replace('(', '', regex=False) \
            .str.replace(')', '', regex=False) \
            .str.replace('/', '_', regex=False)
        
        site_col = cell_col = az_col = tech_col = None
        height_col = mtilt_col = etilt_col = remark_col = None
        
        # Dynamically map columns
        for c in df.columns:
            cl = str(c).lower().strip()
            if site_col is None and any(k == cl or k in cl for k in SITE_KEYWORDS): site_col = c
            if cell_col is None and any(k == cl or k in cl for k in CELL_KEYWORDS): cell_col = c
            if az_col is None and any(k == cl or k in cl for k in AZIMUTH_KEYWORDS): az_col = c
            if tech_col is None and any(k == cl or k in cl for k in TECH_KEYWORDS): tech_col = c
            if height_col is None and any(k == cl or k in cl for k in HEIGHT_KEYWORDS): height_col = c
            if mtilt_col is None and any(k == cl or k in cl for k in MTILT_KEYWORDS): mtilt_col = c
            if etilt_col is None and any(k == cl or k in cl for k in ETILT_KEYWORDS): etilt_col = c
            if remark_col is None and any(k == cl or k in cl for k in REMARK_KEYWORDS): remark_col = c
        
        # We need at least site/cell and azimuth to make a meaningful coverage map
        if not (site_col and az_col): return
        
        cols_to_keep = {site_col: 'site_id', az_col: 'azimuth'}
        if cell_col: cols_to_keep[cell_col] = 'cell_name'
        if tech_col: cols_to_keep[tech_col] = 'technology'
        if height_col: cols_to_keep[height_col] = 'antenna_height'
        if mtilt_col: cols_to_keep[mtilt_col] = 'm_tilt'
        if etilt_col: cols_to_keep[etilt_col] = 'e_tilt'
        if remark_col: cols_to_keep[remark_col] = 'remark'
        
        working_df = df[list(cols_to_keep.keys())].rename(columns=cols_to_keep)
        
        # Clean data
        working_df['site_id'] = working_df['site_id'].apply(clean_site_id)
        if 'cell_name' not in working_df.columns: 
            working_df['cell_name'] = working_df['site_id'] + "_1" # Fallback
            
        working_df['azimuth'] = pd.to_numeric(working_df['azimuth'], errors='coerce').fillna(0)
        
        for num_col in ['antenna_height', 'm_tilt', 'e_tilt']:
            if num_col in working_df.columns:
                working_df[num_col] = pd.to_numeric(working_df[num_col], errors='coerce').fillna(0)
            else:
                working_df[num_col] = 0.0

        if 'technology' not in working_df.columns: working_df['technology'] = 'Unknown'
        if 'remark' not in working_df.columns: working_df['remark'] = ''

        working_df = working_df.dropna(subset=['site_id'])
        
        # Apply the dynamic radius logic
        working_df['coverage_radius_m'] = working_df.apply(calculate_dynamic_radius, axis=1)
        
        all_coverage_list.append(working_df)
    
    # --- STREAMING EXECUTION ---
    for file_url in geo_files:
        print(f"Processing file: {file_url}", flush=True)
        bucket, key = parse_s3_url(file_url)
        local_path = f"/tmp/geo_{int(time.time())}_{os.path.basename(key)}"
        s3_client.download_file(bucket, key, local_path)
        
        try:
            if local_path.lower().endswith('.csv'):
                for chunk in pd.read_csv(local_path, chunksize=50000, low_memory=False):
                    extract_coverage_data(chunk)
                    del chunk
                    gc.collect()
            else:
                if local_path.lower().endswith('.xlsb'):
                    xls = pd.ExcelFile(local_path, engine='pyxlsb')
                else:
                    xls = pd.ExcelFile(local_path)
                    
                for sheet in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet)
                    extract_coverage_data(df)
                    del df
                    gc.collect()
                xls.close()
                
        except Exception as e:
            print(f"Error processing {file_url}: {e}", flush=True)
        finally:
            if os.path.exists(local_path): os.remove(local_path)
            gc.collect() 

    if all_coverage_list:
        final_coverage_df = pd.concat(all_coverage_list, ignore_index=True)
        final_coverage_df = final_coverage_df.drop_duplicates(subset=['cell_name'], keep='last')
        
        # =========================================================
        # --- STRICT DATA TYPING (PYARROW FIX) ---
        # =========================================================
        final_coverage_df['site_id'] = final_coverage_df['site_id'].astype(str)
        final_coverage_df['cell_name'] = final_coverage_df['cell_name'].astype(str)
        final_coverage_df['technology'] = final_coverage_df['technology'].astype(str)
        final_coverage_df['remark'] = final_coverage_df['remark'].astype(str)
        
        final_coverage_df['azimuth'] = final_coverage_df['azimuth'].astype(float)
        final_coverage_df['antenna_height'] = final_coverage_df['antenna_height'].astype(float)
        final_coverage_df['m_tilt'] = final_coverage_df['m_tilt'].astype(float)
        final_coverage_df['e_tilt'] = final_coverage_df['e_tilt'].astype(float)
        final_coverage_df['coverage_radius_m'] = final_coverage_df['coverage_radius_m'].astype(float)

        print(f"Extracted {len(final_coverage_df)} unique sector parameters. Saving to Parquet...", flush=True)
        
        final_coverage_df.to_parquet(
            f"{OUTPUT_URL}site_coverage_params.parquet", 
            engine='pyarrow', 
            compression='snappy', 
            index=False
        )
        print("Site Coverage Params successfully written to S3!", flush=True)
    else:
        print("No valid coverage parameters found in the provided files.", flush=True)

if __name__ == '__main__':
    process_site_coverage()
