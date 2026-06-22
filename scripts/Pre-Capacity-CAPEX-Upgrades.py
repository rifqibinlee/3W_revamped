import pandas as pd
import numpy as np
import boto3
import re
import os
import time
import gc
import ctypes

s3_client = boto3.client('s3')

def force_os_ram_clear():
    """Forces Python to return fragmented RAM to the Linux OS."""
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

# --- CONFIGURATIONS ---
BUCKET_NAME = 'neo-advanced-analytics'
CONGESTION_URL = f's3://{BUCKET_NAME}/processed_network_data/congestion-analysis/'
REF_URL = f's3://{BUCKET_NAME}/site_coverage_params/referenceData/'
RAW_XC_URL = f's3://{BUCKET_NAME}/raw_network_data/Huawei Dataset (xC)/'
RAW_XD_URL = f's3://{BUCKET_NAME}/raw_network_data/ZTE Dataset (xD)/'
OUTPUT_URL = f's3://{BUCKET_NAME}/processed_network_data/pre-capex-upgrades/'

def parse_s3_url(s3_url):
    clean = s3_url.replace("s3://", "")
    parts = clean.split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")

def get_s3_files(s3_url, extensions=('.parquet', '.csv', '.xlsx', '.xlsb')):
    bucket, prefix = parse_s3_url(s3_url)
    files = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                if obj['Key'].lower().endswith(extensions):
                    files.append(f"s3://{bucket}/{obj['Key']}")
    return files

def parse_sector_info(cell_name):
    if pd.isna(cell_name): return None, '1'
    s_cell = str(cell_name).strip()
    if '_' in s_cell:
        parts = s_cell.split('_')
        return parts[0], (re.findall(r'\d', parts[-1]) or ['1'])[-1]
    elif '-' in s_cell:
        parts = s_cell.split('-')
        return parts[0], (re.findall(r'\d', parts[-1]) or ['1'])[-1]
    return s_cell, '1'

def zoom_format(cell_name):
    if pd.isna(cell_name): return "Macro"
    cell_str = str(cell_name).upper()
    if 'BL' in cell_str or 'IB ' in cell_str or 'IB-' in cell_str: return "Inbuilding"
    elif 'PL' in cell_str: return "PBTS"
    return "Macro"

def extract_year_week(file_key):
    basename = os.path.basename(file_key).split('.')[0]
    
    # Extract Year
    year_match = re.search(r'year=(\d{4})', file_key, re.IGNORECASE)
    year = year_match.group(1) if year_match else "Unknown_Year"
    
    # Extract Week: Find all occurrences and grab the LAST one
    # This prevents 'WK4PK_WEEK2' from registering as Week 4
    week_matches = re.findall(r'(?:W|WK|WEEK)[\s_]*0*(\d+)', basename, re.IGNORECASE)
    
    if week_matches:
        week_num = int(week_matches[-1])
        week = f"W{week_num:02d}"
    else:
        week = "Unknown_Week"
        
    # Clean basename for safe S3 saving
    safe_basename = re.sub(r'[^a-zA-Z0-9_\-]', '_', basename)
    
    return year, week, safe_basename

def process_capacity_metrics():
    print("1. Loading Congestion Data for Filtering...", flush=True)
    cong_files = get_s3_files(CONGESTION_URL)
    if not cong_files:
        print("CRITICAL: No congestion files found.")
        return
        
    cong_df = pd.concat([pd.read_parquet(f, columns=['zoom_sector_id', 'area_target']) for f in cong_files])
    cong_df = cong_df.drop_duplicates(subset=['zoom_sector_id'])
    
    # Store congested sectors as a fast lookup set
    cong_sectors_set = set(cong_df['zoom_sector_id'])
    area_target_map = cong_df.set_index('zoom_sector_id')['area_target'].to_dict()
    
    del cong_df
    gc.collect()

    print("2. Loading Reference Data for Avail PRB & Mapping...", flush=True)
    ref_files = get_s3_files(REF_URL, extensions=('.xlsx', '.xlsb', '.csv'))
    ref_dfs = []
    
    for f in ref_files:
        bucket, key = parse_s3_url(f)
        tmp_ref = f"/tmp/ref_{int(time.time()*1000)}"
        s3_client.download_file(bucket, key, tmp_ref)
        
        if key.lower().endswith('.csv'):
            df_sheet = pd.read_csv(tmp_ref, low_memory=False)
            df_sheet.columns = df_sheet.columns.astype(str).str.lower().str.strip()
            ref_dfs.append(df_sheet)
        else:
            dict_dfs = pd.read_excel(tmp_ref, engine='pyxlsb' if key.endswith('.xlsb') else None, sheet_name=None)
            for sheet_name, df_sheet in dict_dfs.items():
                s_name = sheet_name.lower()
                if 'xc ref' in s_name or 'xd ref' in s_name:
                    df_sheet.columns = df_sheet.columns.astype(str).str.lower().str.strip()
                    ref_dfs.append(df_sheet)
        os.remove(tmp_ref)
        
    if not ref_dfs:
        print("CRITICAL: No reference data found. Exiting.")
        return

    master_ref = pd.concat(ref_dfs, ignore_index=True)
    del ref_dfs
    gc.collect()
    
    cell_col = next((c for c in master_ref.columns if 'cell' in c and 'name' in c), None)
    bw_col = next((c for c in master_ref.columns if 'bw' in c), None)

    if not cell_col:
        print("CRITICAL: Could not find cell name column in Reference Data.")
        return

    master_ref['avail_prb'] = pd.to_numeric(master_ref[bw_col], errors='coerce').fillna(0) * 5.0
    master_ref['cell_name_clean'] = master_ref[cell_col].astype(str).str.strip()
    
    parsed_info = master_ref['cell_name_clean'].apply(parse_sector_info)
    master_ref['site_id'] = parsed_info.apply(lambda x: x[0])
    master_ref['sector_suffix'] = parsed_info.apply(lambda x: x[1])
    master_ref['ibc_macro'] = master_ref['cell_name_clean'].apply(zoom_format)
    master_ref['zoom_sector_id'] = master_ref['site_id'].astype(str).str.upper() + '_' + master_ref['ibc_macro'] + '_' + master_ref['sector_suffix']

    # Dictionaries for mapping
    cell_to_sector_map = master_ref.set_index('cell_name_clean')['zoom_sector_id'].to_dict()
    cell_to_avail_prb_map = master_ref.set_index('cell_name_clean')['avail_prb'].to_dict()
    existing_prb_dict = master_ref.groupby('zoom_sector_id')['avail_prb'].sum().to_dict()
    
    del master_ref
    gc.collect()
    
    def process_and_save_file_results(sector_sums_dict, ds_type, year, week, basename):
        if not sector_sums_dict:
            return
            
        final_results = []
        for sector, sum_rb_used in sector_sums_dict.items():
            # Only process sectors that are in the Congestion Analysis
            if sector not in cong_sectors_set:
                continue
                
            sum_existing_prb = existing_prb_dict.get(sector, 0.0)
            
            area_target = str(area_target_map.get(sector, "unknown")).lower()
            is_urban = 'urban' in area_target or 'kmc' in area_target
            divisor = 0.8 if is_urban else 0.92
            
            additional_rb = (sum_rb_used / divisor) - sum_existing_prb
            
            final_results.append({
                'zoom_sector_id': sector,
                'dataset_type': ds_type,
                'sum_existing_prb': float(sum_existing_prb),
                'sum_rb_used': float(sum_rb_used),
                'additional_rb': float(additional_rb)
            })

        if final_results:
            final_df = pd.DataFrame(final_results)
            # --- PAD THE WEEK STRING HERE ---
            padded_week = str(week).zfill(2)
            out_key = f"{OUTPUT_URL}{ds_type}/year={year}/week={padded_week}/{basename}.parquet"
            # --------------------------------
            final_df.to_parquet(out_key, engine='pyarrow', compression='snappy', index=False)
            print(f"      -> Saved {len(final_df)} congested sectors to {ds_type}/year={year}/week={padded_week}/")

    print(f"\n3. Processing xC RAW Data from {RAW_XC_URL}...", flush=True)
    raw_xc_files = get_s3_files(RAW_XC_URL, extensions=('.parquet', '.csv', '.xlsb', '.xlsx'))
    
    def get_sort_key(file_path):
        year, week, _ = extract_year_week(file_path)
        return (str(year), str(week))
        
    raw_xc_files = sorted(raw_xc_files, key=get_sort_key)
    
    print(f"   -> Found {len(raw_xc_files)} xC files.", flush=True)

    for f in raw_xc_files:
        year, week, basename = extract_year_week(f)
        print(f"   [xC] Processing: Year {year} | {week} | File: {basename}", flush=True)
        
        master_xc_top4 = pd.DataFrame() 
        try:
            # --- [FIX] DYNAMIC CHUNK PROCESSING ---
            if f.lower().endswith('.csv'):
                with pd.read_csv(f, chunksize=150000, low_memory=False) as reader:
                    for chunk in reader:
                        chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                        
                        c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                        c_util = next((c for c in chunk.columns if 'bh' in c and 'rb' in c and 'util' in c), None)
                        c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                        c_user = next((c for c in chunk.columns if 'user' in c and 'count' in c), None)
                        
                        if c_cell and c_util:
                            rb_util = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                            
                            if c_bw:
                                bw_mhz = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                                avail_prb = bw_mhz.fillna(0) * 5.0
                            else:
                                avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                                
                            chunk['daily_rb_used'] = (rb_util.fillna(0) / 100.0) * avail_prb
                            
                            if c_user:
                                chunk['user count'] = pd.to_numeric(chunk[c_user], errors='coerce').fillna(0).astype(np.int32)
                            else:
                                chunk['user count'] = 0
                            
                            clean_chunk = pd.DataFrame({
                                'cell_name': chunk[c_cell].astype('category'),
                                'daily_rb_used': chunk['daily_rb_used'].astype(np.float32),
                                'user count': chunk['user count']
                            })
                            
                            master_xc_top4 = pd.concat([master_xc_top4, clean_chunk], ignore_index=True)
                            master_xc_top4.sort_values(by=['user count', 'daily_rb_used'], ascending=[False, False], inplace=True)
                            master_xc_top4 = master_xc_top4.groupby('cell_name', observed=True).head(4).reset_index(drop=True)
                            
                        del chunk
                        force_os_ram_clear()

            else:
                if f.lower().endswith('.parquet'):
                    chunk = pd.read_parquet(f)
                    chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                    
                    c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                    c_util = next((c for c in chunk.columns if 'bh' in c and 'rb' in c and 'util' in c), None)
                    c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                    c_user = next((c for c in chunk.columns if 'user' in c and 'count' in c), None)
                    
                    if c_cell and c_util:
                        rb_util = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                        
                        if c_bw:
                            bw_mhz = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                            avail_prb = bw_mhz.fillna(0) * 5.0
                        else:
                            avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                            
                        chunk['daily_rb_used'] = (rb_util.fillna(0) / 100.0) * avail_prb
                        
                        if c_user:
                            chunk['user count'] = pd.to_numeric(chunk[c_user], errors='coerce').fillna(0).astype(np.int32)
                        else:
                            chunk['user count'] = 0
                        
                        clean_chunk = pd.DataFrame({
                            'cell_name': chunk[c_cell].astype('category'),
                            'daily_rb_used': chunk['daily_rb_used'].astype(np.float32),
                            'user count': chunk['user count']
                        })
                        
                        master_xc_top4 = pd.concat([master_xc_top4, clean_chunk], ignore_index=True)
                        master_xc_top4.sort_values(by=['user count', 'daily_rb_used'], ascending=[False, False], inplace=True)
                        master_xc_top4 = master_xc_top4.groupby('cell_name', observed=True).head(4).reset_index(drop=True)
                        
                    del chunk
                    force_os_ram_clear()

                elif f.lower().endswith(('.xlsb', '.xlsx')):
                    bucket, key = parse_s3_url(f)
                    ext = f.split('.')[-1].lower()
                    tmp_raw = f"/tmp/raw_xc_{int(time.time()*1000)}.{ext}"
                    s3_client.download_file(bucket, key, tmp_raw)
                    engine = 'pyxlsb' if ext == 'xlsb' else None
                    
                    # Read only the sheet names first to avoid loading data into RAM
                    with pd.ExcelFile(tmp_raw, engine=engine) as xls:
                        sheet_names = xls.sheet_names
                        
                        # Process sheet by sheet
                        for sheet in sheet_names:
                            chunk = pd.read_excel(xls, sheet_name=sheet)
                            chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                            
                            c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                            c_util = next((c for c in chunk.columns if 'bh' in c and 'rb' in c and 'util' in c), None)
                            c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                            c_user = next((c for c in chunk.columns if 'user' in c and 'count' in c), None)
                            
                            if c_cell and c_util:
                                rb_util = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                                
                                if c_bw:
                                    bw_mhz = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                                    avail_prb = bw_mhz.fillna(0) * 5.0
                                else:
                                    avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                                    
                                chunk['daily_rb_used'] = (rb_util.fillna(0) / 100.0) * avail_prb
                                
                                if c_user:
                                    chunk['user count'] = pd.to_numeric(chunk[c_user], errors='coerce').fillna(0).astype(np.int32)
                                else:
                                    chunk['user count'] = 0
                                
                                clean_chunk = pd.DataFrame({
                                    'cell_name': chunk[c_cell].astype('category'),
                                    'daily_rb_used': chunk['daily_rb_used'].astype(np.float32),
                                    'user count': chunk['user count']
                                })
                                
                                master_xc_top4 = pd.concat([master_xc_top4, clean_chunk], ignore_index=True)
                                master_xc_top4.sort_values(by=['user count', 'daily_rb_used'], ascending=[False, False], inplace=True)
                                master_xc_top4 = master_xc_top4.groupby('cell_name', observed=True).head(4).reset_index(drop=True)
                                
                            del chunk
                            force_os_ram_clear()
                            
                    if os.path.exists(tmp_raw): os.remove(tmp_raw)
            
            if not master_xc_top4.empty:
                cell_avg_xc = master_xc_top4.groupby('cell_name', observed=True)['daily_rb_used'].mean().reset_index()
                cell_avg_xc['zoom_sector_id'] = cell_avg_xc['cell_name'].map(cell_to_sector_map)
                
                sector_sums_dict = cell_avg_xc.groupby('zoom_sector_id')['daily_rb_used'].sum().to_dict()
                process_and_save_file_results(sector_sums_dict, 'xC', year, week, basename)
                
        except Exception as e:
            print(f"Error reading {f}: {e}")
            
        del master_xc_top4
        gc.collect()

    print(f"\n4. Processing xD RAW Data from {RAW_XD_URL}...", flush=True)
    raw_xd_files = get_s3_files(RAW_XD_URL, extensions=('.parquet', '.csv', '.xlsb', '.xlsx'))
    
    raw_xd_files = sorted(raw_xd_files, key=get_sort_key)
    
    print(f"   -> Found {len(raw_xd_files)} xD files.", flush=True)
    
    for f in raw_xd_files:
        year, week, basename = extract_year_week(f)
        print(f"   [xD] Processing: Year {year} | {week} | File: {basename}", flush=True)
        
        file_sector_sums_dict = {}
        try:
            # --- [FIX] DYNAMIC CHUNK PROCESSING ---
            if f.lower().endswith('.csv'):
                with pd.read_csv(f, chunksize=150000, low_memory=False) as reader:
                    for chunk in reader:
                        chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                        
                        c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                        c_util = next((c for c in chunk.columns if 'eric_prb' in c and 'utilzation' in c), None)
                        c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                        
                        if c_cell and c_util:
                            eric_prb = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                            
                            if c_bw:
                                bw_mhz_xd = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                                avail_prb = bw_mhz_xd.fillna(0) * 5.0
                            else:
                                avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                            
                            chunk['cell_rb_used'] = (eric_prb.fillna(0) / 100.0) * avail_prb
                            chunk['zoom_sector_id'] = chunk[c_cell].astype(str).str.strip().map(cell_to_sector_map)
                            
                            # Group dynamically and add to dictionary
                            chunk_grouped = chunk.groupby('zoom_sector_id', observed=True)['cell_rb_used'].sum().to_dict()
                            for sector, val in chunk_grouped.items():
                                file_sector_sums_dict[sector] = file_sector_sums_dict.get(sector, 0) + val
                        
                        del chunk
                        force_os_ram_clear()

            else:
                if f.lower().endswith('.parquet'):
                    chunk = pd.read_parquet(f)
                    chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                    
                    c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                    c_util = next((c for c in chunk.columns if 'eric_prb' in c and 'utilzation' in c), None)
                    c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                    
                    if c_cell and c_util:
                        eric_prb = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                        
                        if c_bw:
                            bw_mhz_xd = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                            avail_prb = bw_mhz_xd.fillna(0) * 5.0
                        else:
                            avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                        
                        chunk['cell_rb_used'] = (eric_prb.fillna(0) / 100.0) * avail_prb
                        chunk['zoom_sector_id'] = chunk[c_cell].astype(str).str.strip().map(cell_to_sector_map)
                        
                        chunk_grouped = chunk.groupby('zoom_sector_id', observed=True)['cell_rb_used'].sum().to_dict()
                        for sector, val in chunk_grouped.items():
                            file_sector_sums_dict[sector] = file_sector_sums_dict.get(sector, 0) + val
                
                    del chunk
                    force_os_ram_clear()

                elif f.lower().endswith(('.xlsb', '.xlsx')):
                    bucket, key = parse_s3_url(f)
                    ext = f.split('.')[-1].lower()
                    tmp_raw = f"/tmp/raw_xd_{int(time.time()*1000)}.{ext}"
                    s3_client.download_file(bucket, key, tmp_raw)
                    engine = 'pyxlsb' if ext == 'xlsb' else None
                    
                    # Read only the sheet names first to avoid loading data into RAM
                    with pd.ExcelFile(tmp_raw, engine=engine) as xls:
                        sheet_names = xls.sheet_names
                        
                        # Process sheet by sheet
                        for sheet in sheet_names:
                            chunk = pd.read_excel(xls, sheet_name=sheet)
                            chunk.columns = chunk.columns.astype(str).str.lower().str.strip()
                            
                            c_cell = next((c for c in chunk.columns if 'cell' in c and 'name' in c), None)
                            c_util = next((c for c in chunk.columns if 'eric_prb' in c and 'utilzation' in c), None)
                            c_bw = next((c for c in chunk.columns if 'bw' in c), None)
                            
                            if c_cell and c_util:
                                eric_prb = pd.to_numeric(chunk[c_util], errors='coerce').astype(np.float32)
                                
                                if c_bw:
                                    bw_mhz_xd = pd.to_numeric(chunk[c_bw], errors='coerce').astype(np.float32)
                                    avail_prb = bw_mhz_xd.fillna(0) * 5.0
                                else:
                                    avail_prb = chunk[c_cell].astype(str).str.strip().map(cell_to_avail_prb_map).fillna(0)
                                
                                chunk['cell_rb_used'] = (eric_prb.fillna(0) / 100.0) * avail_prb
                                chunk['zoom_sector_id'] = chunk[c_cell].astype(str).str.strip().map(cell_to_sector_map)
                                
                                chunk_grouped = chunk.groupby('zoom_sector_id', observed=True)['cell_rb_used'].sum().to_dict()
                                for sector, val in chunk_grouped.items():
                                    file_sector_sums_dict[sector] = file_sector_sums_dict.get(sector, 0) + val
                        
                            del chunk
                            force_os_ram_clear()
                            
                    if os.path.exists(tmp_raw): os.remove(tmp_raw)

            # Save results for this specific file/week
            process_and_save_file_results(file_sector_sums_dict, 'xD', year, week, basename)
            
        except Exception as e:
            print(f"Error reading {f}: {e}")

    print("\nPre-Aggregation Complete.")

if __name__ == '__main__':
    process_capacity_metrics()
