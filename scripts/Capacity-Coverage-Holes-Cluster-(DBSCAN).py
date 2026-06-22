import pandas as pd
import numpy as np
import boto3
import re
import os
import time
import gc
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

s3_client = boto3.client('s3')

def parse_s3_url(s3_url):
    clean_url = s3_url.replace("s3://", "")
    parts = clean_url.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix

def get_s3_files_from_url(s3_url, extensions=('.csv', '.xls', '.xlsx', '.xlsb', '.parquet')):
    bucket, prefix = parse_s3_url(s3_url)
    files = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].lower().endswith(extensions):
                    files.append(f"s3://{bucket}/{obj['Key']}")
    return files

# Input Configurations
INPUT_URLS = [
    's3://neo-advanced-analytics/coverage_holes/MR-Data/',
    's3://neo-advanced-analytics/coverage_holes/Ookla-Data/'
]
# Output Configurations
OUTPUT_URL = 's3://neo-advanced-analytics/processed_network_data/coverage-holes-clustered/'

# DBSCAN Model
def auto_tune_dbscan(X_radians):
    n_points = len(X_radians)
    if n_points < 6:
        return 0.05/6371.0088, 3 
        
    neigh = NearestNeighbors(n_neighbors=6, metric='haversine')
    nbrs = neigh.fit(X_radians)
    distances, _ = nbrs.kneighbors(X_radians)
    
    avg_nn = float(np.mean(distances[:, 1])) 
    avg_d5 = float(np.mean(distances[:, -1])) 
    beta = 2.0 
    safe_avg_nn = max(avg_nn, 1e-9) 
    
    min_pts = max(3, int(round(beta * (avg_d5 / safe_avg_nn))))
    min_pts = min(min_pts, n_points - 1) 
    
    neigh_k = NearestNeighbors(n_neighbors=min_pts, metric='haversine')
    nbrs_k = neigh_k.fit(X_radians)
    distances_k, _ = nbrs_k.kneighbors(X_radians)
    k_distances = np.sort(distances_k[:, -1])
    
    elbow_index = int(len(k_distances) * 0.745) 
    eps_rad = float(k_distances[elbow_index])
    
    return eps_rad, min_pts

def process_coverage_holes():
    all_poor_points = []

    # --- EXACT EXTRACTION LOGIC FROM apptest.py ---
    def extract_poor_coverage(df):
        if df is None or df.empty: return
        
        df.columns = [str(c).strip() for c in df.columns]
        
        ookla_signatures = ['Operator_N', 'Sim_Slot', 'App_Versio', 'Cell_ID']
        is_ookla = any(col in df.columns for col in ookla_signatures)
        data_source = "Ookla" if is_ookla else "MR"
        
        s_col = next((c for c in ['Serving Cell', 'ServingCell', 'Cell_ID', 'Site_ID'] if c in df.columns), None)
        lat_col = 'Latitude' if 'Latitude' in df.columns else ('latitude' if 'latitude' in df.columns else None)
        lon_col = 'Longitude' if 'Longitude' in df.columns else ('longitude' if 'longitude' in df.columns else None)
        sig_col = 'Cell Server Signal' if 'Cell Server Signal' in df.columns else ('Signal' if 'Signal' in df.columns else None)
        
        if not (lat_col and lon_col and sig_col):
            return
            
        working_df = df.copy()
        working_df[lat_col] = pd.to_numeric(working_df[lat_col], errors='coerce')
        working_df[lon_col] = pd.to_numeric(working_df[lon_col], errors='coerce')
        working_df[sig_col] = pd.to_numeric(working_df[sig_col], errors='coerce')
        
        working_df = working_df.dropna(subset=[lat_col, lon_col, sig_col])
        
        # Filter exact same way as Flask App
        holes_df = working_df[working_df[sig_col] < -110].copy()
        
        if not holes_df.empty:
            # Map to standard database names
            holes_df['latitude'] = holes_df[lat_col]
            holes_df['longitude'] = holes_df[lon_col]
            holes_df['signal_strength'] = holes_df[sig_col]
            holes_df['serving_cell'] = holes_df[s_col].astype(str) if s_col else "Unknown"
            holes_df['data_source'] = data_source
            
            all_poor_points.append(holes_df[['latitude', 'longitude', 'signal_strength', 'serving_cell', 'data_source']])

    # --- 1. EXTRACT DATA STREAMING ---
    for input_folder in INPUT_URLS:
        print(f"Gathering coverage data from: {input_folder}", flush=True)
        data_files = get_s3_files_from_url(input_folder)
        
        for file_url in data_files:
            print(f"Processing file: {file_url}", flush=True)
            bucket, key = parse_s3_url(file_url)
            local_path = f"/tmp/cov_{int(time.time())}_{os.path.basename(key)}"
            s3_client.download_file(bucket, key, local_path)
            
            try:
                if local_path.lower().endswith('.csv'):
                    for chunk in pd.read_csv(local_path, chunksize=100000, low_memory=False):
                        extract_poor_coverage(chunk)
                        del chunk
                        gc.collect()
                elif local_path.lower().endswith('.parquet'):
                    df = pd.read_parquet(local_path)
                    extract_poor_coverage(df)
                    del df
                else:
                    xls = pd.ExcelFile(local_path, engine='pyxlsb' if local_path.endswith('.xlsb') else None)
                    for sheet in xls.sheet_names:
                        df = pd.read_excel(xls, sheet_name=sheet)
                        extract_poor_coverage(df)
                        del df
                        gc.collect()
                    xls.close()
            except Exception as e:
                print(f"Error processing {file_url}: {e}", flush=True)
            finally:
                if os.path.exists(local_path): os.remove(local_path)
                gc.collect()

    # --- 2. CLUSTER WITH DBSCAN & SAVE RAW POINTS ---
    if all_poor_points:
        master_points_df = pd.concat(all_poor_points, ignore_index=True)
        print(f"Total poor coverage points extracted: {len(master_points_df)}. Starting Spatial Clustering...", flush=True)
        
        X_rad = np.radians(master_points_df[['latitude', 'longitude']].values)
        
        if len(X_rad) > 10:
            eps_rad, min_pts = auto_tune_dbscan(X_rad)
        else:
            eps_rad, min_pts = 0.05/6371.0088, 3 
            
        print(f"Auto-Tuned DBSCAN -> EPS (Radians): {eps_rad:.6f}, Min Samples: {min_pts}", flush=True)
        
        db = DBSCAN(eps=eps_rad, min_samples=min_pts, metric='haversine', algorithm='ball_tree').fit(X_rad)
        
        # Add Cluster ID back to the RAW points (Including Noise, which is -1)
        master_points_df['cluster_id'] = db.labels_
        
        # Format explicitly for PyArrow
        master_points_df['latitude'] = master_points_df['latitude'].astype(float)
        master_points_df['longitude'] = master_points_df['longitude'].astype(float)
        master_points_df['signal_strength'] = master_points_df['signal_strength'].astype(float)
        master_points_df['cluster_id'] = master_points_df['cluster_id'].astype(int)
        master_points_df['serving_cell'] = master_points_df['serving_cell'].astype(str)
        master_points_df['data_source'] = master_points_df['data_source'].astype(str)

        print(f"Saving {len(master_points_df)} RAW clustered coverage points to Parquet...", flush=True)
        
        master_points_df.to_parquet(
            f"{OUTPUT_URL}coverage_holes_raw.parquet", 
            engine='pyarrow', 
            compression='snappy', 
            index=False
        )
        print("Coverage holes successfully clustered and written to S3!", flush=True)
    else:
        print("No poor coverage points found. Exiting gracefully.", flush=True)

if __name__ == '__main__':
    process_coverage_holes()
