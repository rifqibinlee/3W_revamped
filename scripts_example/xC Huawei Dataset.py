import pandas as pd
import numpy as np
import boto3
import re
import gc
import time
import os
import csv
import datetime
import pyxlsb
import ctypes # [NEW] Required for deep Linux memory clearing

s3_client = boto3.client('s3')

def force_os_ram_clear():
    """Forces Python to return fragmented RAM to the Linux OS."""
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

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
    
def compute_base_sector_id(full_sector_id):
    if full_sector_id is None: return None
    parts = str(full_sector_id).split('_')
    if len(parts) < 3: return full_sector_id
    prefix = '_'.join(parts[:-1])
    digits = re.findall(r'\d', parts[-1])
    if digits: return f"{prefix}_{digits[-1]}"
    return full_sector_id

def aggregate_f_layers(series):
    if series.empty: return None
    valid_tags = set([str(val).lower().strip() for val in series.dropna() if str(val).lower().strip() in ['f1', 'f2', 'f3']])
    if valid_tags: return "".join(sorted(valid_tags))
    return series.iloc[0]

# --- 1. PROCESS REFERENCE DATA ---
REF_INPUT_URL = 's3://neo-advanced-analytics/site_coverage_params/referenceData/'
ref_files = get_s3_files_from_url(REF_INPUT_URL)
all_refs = []

if ref_files:
    for r_file in ref_files:
        bucket, key = parse_s3_url(r_file)
        local_ref = f"/tmp/ref_{int(time.time())}_{os.path.basename(key)}"
        s3_client.download_file(bucket, key, local_ref)
        try:
            if local_ref.lower().endswith('.csv'):
                sheet_names = [None]
                xls = None
            else:
                xls = pd.ExcelFile(local_ref)
                sheet_names = xls.sheet_names
            
            for sheet in sheet_names:
                if xls: df_r = pd.read_excel(xls, sheet_name=sheet)
                else: df_r = pd.read_csv(local_ref, low_memory=False)

                clean_cols = [re.sub(r'[^a-z0-9]', '', str(c).lower()) for c in df_r.columns]
                cell_idx = next((i for i, c in enumerate(clean_cols) if any(k in c for k in ['cellname', 'cellid', 'sectorid'])), None)
                if cell_idx is None: cell_idx = next((i for i, c in enumerate(clean_cols) if 'site' in c), None)

                if cell_idx is not None:
                    temp = pd.DataFrame()
                    temp['cell_name'] = df_r.iloc[:, cell_idx].astype(str).str.strip()
                    
                    area_idx = next((i for i, c in enumerate(clean_cols) if any(k in c for k in ['urban', 'kmc', 'target', 'outside'])), None)
                    temp['area_target'] = df_r.iloc[:, area_idx] if area_idx is not None else np.nan
                        
                    bau_idx = next((i for i, c in enumerate(clean_cols) if any(k in c for k in ['bau', 'nic'])), None)
                    temp['bau_nic'] = df_r.iloc[:, bau_idx] if bau_idx is not None else np.nan
                    all_refs.append(temp)
                del df_r
                force_os_ram_clear()
            if xls: xls.close()
        except: pass
        finally:
            if os.path.exists(local_ref): os.remove(local_ref)

if all_refs:
    ref_df = pd.concat(all_refs, ignore_index=True)
    ref_df['area_target'] = ref_df['area_target'].replace(['', 'nan', 'NaN', 'None', 'Unknown'], np.nan)
    ref_df['bau_nic'] = ref_df['bau_nic'].replace(['', 'nan', 'NaN', 'None', 'Unknown'], np.nan)
    ref_df['join_key'] = ref_df['cell_name'].astype(str).str.upper().str.replace(r'[^A-Z0-9]', '', regex=True)
    ref_df = ref_df.sort_values(by=['area_target', 'bau_nic'], na_position='last')
    ref_cell = ref_df.drop_duplicates(subset=['join_key'], keep='first')[['join_key', 'area_target', 'bau_nic']]
    ref_df['site_id_join'] = ref_df['cell_name'].astype(str).str.upper().str.replace(r'[- ]', '_', regex=True).str.split('_').str[0]
    ref_site = ref_df.drop_duplicates(subset=['site_id_join'], keep='first')[['site_id_join', 'area_target', 'bau_nic']]
    ref_site = ref_site.rename(columns={'area_target': 'area_target_fallback', 'bau_nic': 'bau_nic_fallback'})
    del ref_df
    force_os_ram_clear()
else:
    ref_cell = pd.DataFrame(columns=['join_key', 'area_target', 'bau_nic'])
    ref_site = pd.DataFrame(columns=['site_id_join', 'area_target_fallback', 'bau_nic_fallback'])

OUTPUT_DESTINATION_URL = 's3://neo-advanced-analytics/processed_network_data/sector-calculations/xC-processed-result/'
text_cols = ['site_id', 'region', 'cluster', 'ibc_macro', 'f1f2f3', 'operator', 'area_target', 'bau_nic', 'vendor']

# --- 2. PROCESS xC DATASETS ---
XC_INPUT_URL = 's3://neo-advanced-analytics/raw_network_data/Huawei Dataset (xC)/'
xc_files = get_s3_files_from_url(XC_INPUT_URL)

# --- [INSERT THIS EXACT BLOCK] FORCE ASCENDING CHRONOLOGICAL SORT ---
def get_chronological_order(file_path):
    year_match = re.search(r'(?:year|y)[-_=\s]*(\d{4})', file_path, re.IGNORECASE)
    if not year_match: year_match = re.search(r'(202\d)', file_path)
    
    week_match = re.search(r'(?:week|wk|w)[-_=\s]*(\d{1,2})', file_path, re.IGNORECASE)
    
    # Default to 9999/99 so unparsed files go to the end, not the beginning
    y = int(year_match.group(1)) if year_match else 9999
    w = int(week_match.group(1)) if week_match else 99
    return (y, w)

xc_files = sorted(xc_files, key=get_chronological_order)

for file in xc_files:
    print(f"\nProcessing dataset: {file}", flush=True)
    bucket, key = parse_s3_url(file)
    
    year_match = re.search(r'(?:year|y)[-_=\s]*(\d{4})', key, re.IGNORECASE)
    if not year_match: year_match = re.search(r'(202\d)', key)
    file_year = int(year_match.group(1)) if year_match else 2025
    
    week_match = re.search(r'(?:week|wk|w)[-_=\s]*(\d{1,2})', key, re.IGNORECASE)
    file_week = int(week_match.group(1)) if week_match else 1
    
    file_ext = os.path.splitext(key)[1].lower()
    local_download_path = f"/tmp/temp_xc_dl_{int(time.time())}{file_ext}"
    local_csv = f"/tmp/temp_xc_parsed_{int(time.time())}.csv"
    
    s3_client.download_file(bucket, key, local_download_path)
    
    # --- IF EXCEL, CONVERT IT ---
    if file_ext == '.xlsb':
        needed_cols = {
            'location_id', 'site_id', 'cellname', 'cell_name', 'week_number', 'week',
            'bh_max_user_#', 'eric_max_rrc_user', 'bh_dl_rb_util_pct', 'dl_rb_util',
            'dl_user_throughput', 'dl_throughput', 'traffic', 'data_volume', 'volume',
            'dl_prb_num', 'dl_prb_denom', 'user_dl_thp_num', 'user_dl_thp_denom',
            'band', 'year', 'date', 'time', 'region'
        }
        header_map = {}
        with pyxlsb.open_workbook(local_download_path) as wb:
            with wb.get_sheet(wb.sheets[0]) as sheet:
                with open(local_csv, 'w', newline='', encoding='utf-8') as f_csv:
                    writer = csv.writer(f_csv)
                    for r_idx, row in enumerate(sheet.rows()):
                        cells = [c.v for c in row]
                        if r_idx == 0:
                            ordered_headers = []
                            for c_idx, val in enumerate(cells):
                                if val is None: continue
                                clean_col = str(val).lower().replace(' ', '_').replace('(', '').replace(')', '').replace('+','_').replace('%','pct')
                                if clean_col in needed_cols or 'volume' in clean_col or 'traffic' in clean_col or 'cellname' in clean_col or 'cell_name' in clean_col or 'date' in clean_col or 'time' in clean_col or 'region' in clean_col:
                                    header_map[c_idx] = clean_col
                                    ordered_headers.append(clean_col)
                            writer.writerow(ordered_headers)
                        else:
                            if not any(cells): continue
                            row_out = []
                            for c_idx in header_map.keys():
                                row_out.append(cells[c_idx] if c_idx < len(cells) else None)
                            writer.writerow(row_out)
                        if r_idx > 0 and r_idx % 50000 == 0: force_os_ram_clear()
        file_to_process = local_csv
        
    # --- IF ALREADY CSV, BYPASS CONVERSION ---
    else:
        file_to_process = local_download_path

    force_os_ram_clear()
    
    chunk_size = 100000  # [FIX 1] Reduced chunk size to strictly cap peak memory
    master_top4 = pd.DataFrame()
    master_agg_list = []
    
    # [FIX 2] Predefined Categoricals. This gives massive memory savings AND prevents concat fragmentation!
    op_cat = pd.CategoricalDtype(categories=['Celcom', 'Digi', 'Unknown'], ordered=False)
    ibc_cat = pd.CategoricalDtype(categories=['Inbuilding', 'PBTS', 'Macro'], ordered=False)
    f_cat = pd.CategoricalDtype(categories=['f1', 'f2', 'f3', 'Other'], ordered=False)

    with pd.read_csv(file_to_process, chunksize=chunk_size, low_memory=False) as reader:
        for chunk in reader:
            chunk.columns = [str(c).lower().replace(' ', '_').replace('(', '').replace(')', '').replace('+','_').replace('%','pct') for c in chunk.columns]
            col_map = {
                'location_id': 'site_id', 'cellname': 'cell_name', 'week_number': 'week',
                'bh_max_user_#': 'eric_max_rrc_user', 'bh_dl_rb_util_pct': 'dl_rb_util',
                'dl_user_throughput': 'dl_throughput', 'traffic': 'data_volume'
            }
            chunk = chunk.rename(columns=col_map)
            
            if 'cell_name' not in chunk.columns: continue
            chunk = chunk.dropna(subset=['cell_name'], how='all')
            if chunk.empty: continue
            
            # Numeric downcasting early to shed memory
            if 'year' not in chunk.columns: chunk['year'] = file_year
            else: chunk['year'] = pd.to_numeric(chunk['year'], errors='coerce').fillna(file_year).astype('int16')
                
            if 'week' not in chunk.columns: chunk['week'] = file_week
            else: chunk['week'] = pd.to_numeric(chunk['week'], errors='coerce').fillna(file_week).astype('int8')
            
            vol_col = next((c for c in chunk.columns if 'volume' in c or 'traffic' in c), None)
            if vol_col and 'data_volume' not in chunk.columns:
                chunk = chunk.rename(columns={vol_col: 'data_volume'})

            chunk['cell_name'] = chunk['cell_name'].astype(str).str.strip()
            cn_upper = chunk['cell_name'].str.upper()
            cn_clean = chunk['cell_name'].str.strip('_')
            
            # Apply predefined categories
            chunk['operator'] = pd.Series(np.select(
                [chunk['cell_name'].str.contains('_', regex=False), chunk['cell_name'].str.contains('-', regex=False)],
                ['Celcom', 'Digi'], default='Unknown'
            )).astype(op_cat)
            
            chunk['ibc_macro'] = pd.Series(np.select(
                [cn_upper.str.contains('BL|IB |IB-', regex=True), cn_upper.str.contains('PL', regex=False)],
                ['Inbuilding', 'PBTS'], default='Macro'
            )).astype(ibc_cat)
            
            chunk['f1f2f3'] = pd.Series(np.select([
                cn_clean.str.fullmatch(r"^\d{2,3}$"),
                cn_clean.str.contains(r"_\d{2}_\d$|-XL\d+$", flags=re.IGNORECASE, regex=True),
                cn_clean.str.contains(r"CMM|BLC|DLC|MLC|PLC|CL|RAMO|[a-zA-Z]{2}\d{5}_\d+_\d+", flags=re.IGNORECASE, regex=True),
                cn_clean.str.contains(r"DMM|DLD|DL|LD|ML(?!C)|BL|UL|BLD", flags=re.IGNORECASE, regex=True)
            ], ['f1', 'f3', 'f2', 'f1'], default='Other')).astype(f_cat)
            
            chunk['sector_suffix'] = chunk['cell_name'].str.extract(r'(\d)[^\d]*$').fillna('1')
            if 'site_id' not in chunk.columns: chunk['site_id'] = chunk['cell_name'].str.replace(r'[- ]', '_', regex=True).str.split('_').str[0]
            else: chunk['site_id'] = chunk['site_id'].fillna(chunk['cell_name'].str.replace(r'[- ]', '_', regex=True).str.split('_').str[0])
                
            chunk['site_id'] = chunk['site_id'].astype(str).str.strip().str.upper()
            chunk['zoom_sector_id'] = chunk['site_id'] + '_' + chunk['ibc_macro'].astype(str) + '_' + chunk['sector_suffix']

            for num_col in ['dl_rb_util', 'dl_throughput', 'data_volume', 'eric_max_rrc_user', 'dl_prb_num', 'dl_prb_denom', 'user_dl_thp_num', 'user_dl_thp_denom']:
                if num_col in chunk.columns: 
                    chunk[num_col] = pd.to_numeric(chunk[num_col], errors='coerce').fillna(0).astype('float32')
                    
            cols_to_keep = [
                'cell_name', 'zoom_sector_id', 'band', 'week', 'year', 'region', 'cluster', 
                'ibc_macro', 'f1f2f3', 'operator', 'dl_prb_num', 'dl_prb_denom', 
                'user_dl_thp_num', 'user_dl_thp_denom', 'data_volume', 'eric_max_rrc_user', 'dl_rb_util','vendor','site_id'
            ]
            chunk = chunk[[c for c in cols_to_keep if c in chunk.columns]]
            
            # ON-THE-FLY REDUCTION
            chunk.sort_values(['cell_name', 'band', 'week', 'year', 'eric_max_rrc_user', 'dl_rb_util'], ascending=[True, True, True, True, False, False], inplace=True)
            chunk = chunk.groupby(['cell_name', 'band', 'week', 'year'], dropna=False).head(4)
            
            master_agg_list.append(chunk)
            
            if len(master_agg_list) >= 5: # [FIX 3] Dropped batch limit to 5 to protect AWS Glue's strict RAM ceiling
                temp_concat = pd.concat(master_agg_list, ignore_index=True)
                temp_concat.sort_values(['cell_name', 'band', 'week', 'year', 'eric_max_rrc_user', 'dl_rb_util'], ascending=[True, True, True, True, False, False], inplace=True)
                
                if master_top4.empty:
                    master_top4 = temp_concat.groupby(['cell_name', 'band', 'week', 'year'], dropna=False).head(4)
                else:
                    master_top4 = pd.concat([master_top4, temp_concat], ignore_index=True)
                    master_top4.sort_values(['cell_name', 'band', 'week', 'year', 'eric_max_rrc_user', 'dl_rb_util'], ascending=[True, True, True, True, False, False], inplace=True)
                    master_top4 = master_top4.groupby(['cell_name', 'band', 'week', 'year'], dropna=False).head(4)
                    
                master_agg_list.clear() 
                del temp_concat
                force_os_ram_clear()
                
            del chunk
    
    # Process remainder chunks outside the loop
    if master_agg_list:
        temp_concat = pd.concat(master_agg_list, ignore_index=True)
        if master_top4.empty:
            master_top4 = temp_concat.sort_values(['cell_name', 'band', 'week', 'year', 'eric_max_rrc_user', 'dl_rb_util'], ascending=[True, True, True, True, False, False]).groupby(['cell_name', 'band', 'week', 'year'], dropna=False).head(4)
        else:
            master_top4 = pd.concat([master_top4, temp_concat], ignore_index=True)
            master_top4.sort_values(['cell_name', 'band', 'week', 'year', 'eric_max_rrc_user', 'dl_rb_util'], ascending=[True, True, True, True, False, False], inplace=True)
            master_top4 = master_top4.groupby(['cell_name', 'band', 'week', 'year'], dropna=False).head(4)
        del temp_concat, master_agg_list
        force_os_ram_clear()
    
    if master_top4.empty: continue
        
    unique_cells = master_top4['cell_name'].unique()
    batch_size = 5000 
    all_final_results = []
    
    for i in range(0, len(unique_cells), batch_size):
        cell_batch = unique_cells[i:i+batch_size]
        batch_df = master_top4[master_top4['cell_name'].isin(cell_batch)].copy()
    
        agg_dict = {
            'zoom_sector_id': 'first', 'ibc_macro': 'first', 'f1f2f3': 'first', 'operator': 'first',
            'dl_prb_num': 'sum', 'dl_prb_denom': 'sum', 'user_dl_thp_num': 'sum', 'user_dl_thp_denom': 'sum',
            'data_volume': 'mean', 'eric_max_rrc_user': 'mean', 'vendor': 'first', 'site_id': 'first'
        }
        if 'region' in batch_df.columns: agg_dict['region'] = 'first'

        df_cells = batch_df.groupby(['cell_name', 'band', 'week', 'year'], dropna=False).agg(agg_dict).reset_index()
        
        df_cells['join_key'] = df_cells['cell_name'].astype(str).str.upper().str.replace(r'[^A-Z0-9]', '', regex=True)
        df_cells['site_id_join'] = df_cells['cell_name'].astype(str).str.upper().str.replace(r'[- ]', '_', regex=True).str.split('_').str[0]
        
        df_cells = df_cells.merge(ref_cell, on='join_key', how='left')
        df_cells = df_cells.merge(ref_site, on='site_id_join', how='left')
        
        df_cells['area_target'] = df_cells['area_target'].fillna(df_cells['area_target_fallback'])
        df_cells['bau_nic'] = df_cells['bau_nic'].fillna(df_cells['bau_nic_fallback'])

        df_cells = df_cells.rename(columns={
            'dl_prb_num': 'sum_dl_prb_num', 'dl_prb_denom': 'sum_dl_prb_denom',
            'user_dl_thp_num': 'sum_thp_num', 'user_dl_thp_denom': 'sum_thp_denom',
            'data_volume': 'sum_vol', 'eric_max_rrc_user': 'sum_users'
        })
        
        df_cells['base_sector'] = df_cells['zoom_sector_id'].apply(compute_base_sector_id)

        for (base_sec, wk, yr), group in df_cells.groupby(['base_sector', 'week', 'year'], dropna=False):
            prb_denom = group['sum_dl_prb_denom'].sum()
            thp_denom = group['sum_thp_denom'].sum()
            
            valid_areas = [a for a in group['area_target'].dropna().unique() if str(a).strip().lower() not in ['', 'nan', 'unknown', 'none']]
            valid_baus = [b for b in group['bau_nic'].dropna().unique() if str(b).strip().lower() not in ['', 'nan', 'unknown', 'none']]
            
            all_final_results.append({
                'site_id': group['site_id'].iloc[0] if 'site_id' in group.columns else "Unknown",
                'zoom_sector_id': base_sec, 
                'week': int(wk), 
                'year': int(yr),
                'region': str(group['region'].iloc[0]).upper().strip() if 'region' in group.columns and pd.notna(group['region'].iloc[0]) and str(group['region'].iloc[0]).strip() not in ['0', 'Unknown', 'nan'] else "Unknown",
                'cluster': "Unknown", 
                'ibc_macro': group['ibc_macro'].iloc[0], 
                'f1f2f3': aggregate_f_layers(group['f1f2f3']),
                'eric_data_volume_ul_dl': float(group['sum_vol'].sum()), 
                'eric_prb_util_rate': float((group['sum_dl_prb_num'].sum() / prb_denom) * 100.0 if prb_denom > 0 else 0.0),
                'eric_dl_user_ip_thpt': float((group['sum_thp_num'].sum() / thp_denom) / 1000.0 if thp_denom > 0 else 0.0), 
                'eric_max_rrc_user': int(group['sum_users'].sum()),
                'max_active_user': int(group['sum_users'].sum()), 
                'dataset_type': 'xC', 
                'operator': group['operator'].iloc[0],
                'area_target': str(valid_areas[0]) if valid_areas else "Unknown",
                'bau_nic': str(valid_baus[0]) if valid_baus else "Unknown",
                'vendor': group['vendor'].iloc[0] if 'vendor' in group.columns and pd.notna(group['vendor'].iloc[0]) else 'Unknown'
            })
        
        del batch_df, df_cells
        force_os_ram_clear()

    if all_final_results:
        final_df = pd.DataFrame(all_final_results)
        for c in text_cols:
            if c in final_df.columns:
                final_df[c] = final_df[c].fillna("Unknown").astype(str)
                
        # --- [INSERT THIS LINE] ZERO-PAD THE WEEK COLUMN FOR S3 SORTING ---
        final_df['week'] = final_df['week'].astype(str).str.zfill(2)
        # ------------------------------------------------------------------
                
        final_df.to_parquet(
            OUTPUT_DESTINATION_URL, 
            engine='pyarrow', 
            compression='snappy', 
            index=False,
            partition_cols=['year', 'week']
        )
        
    # [NEW] AGGRESSIVE CLEANUP BETWEEN FILES
    del master_top4, all_final_results
    try: del final_df
    except: pass
    
    # --- [INSERT THIS EXACT BLOCK] DELETE RESIDUAL TEMP FILES TO PREVENT OOM ---
    if 'local_download_path' in locals() and os.path.exists(local_download_path):
        os.remove(local_download_path)
    if 'local_csv' in locals() and os.path.exists(local_csv):
        os.remove(local_csv)
    # ---------------------------------------------------------------------------
        
    force_os_ram_clear()

print("All xC files processed and saved to S3 successfully!", flush=True)
