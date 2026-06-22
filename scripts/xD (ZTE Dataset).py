import pandas as pd
import numpy as np
import boto3
import re
import gc 

s3_client = boto3.client('s3')

def parse_s3_url(s3_url):
    clean_url = s3_url.replace("s3://", "")
    parts = clean_url.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix

def get_s3_files_from_url(s3_url, extensions=('.csv', '.xls', '.xlsx', '.xlsb')):
    bucket, prefix = parse_s3_url(s3_url)
    files = []
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    if 'Contents' in response:
        for obj in response['Contents']:
            if obj['Key'].lower().endswith(extensions):
                files.append(f"s3://{bucket}/{obj['Key']}")
    return files
    
def parse_sector_info(cell_name):
    if pd.isna(cell_name) or str(cell_name).strip() == '': 
        return 'UNKNOWN', '1', 'Unknown'
    s_cell = str(cell_name).strip()
    if '_' in s_cell:
        parts = s_cell.split('_')
        return parts[0], (re.findall(r'\d', parts[-1]) or ['1'])[-1], 'Celcom' 
    elif '-' in s_cell:
        parts = s_cell.split('-')
        return parts[0], (re.findall(r'\d', parts[-1]) or ['1'])[-1], 'Digi'   
    return s_cell, '1', 'Unknown'

def zoom_format(cell_name):
    if pd.isna(cell_name): return "Macro"
    cell_str = str(cell_name).upper()
    if 'BL' in cell_str or 'IB ' in cell_str or 'IB-' in cell_str: return "Inbuilding"
    elif 'PL' in cell_str: return "PBTS"
    return "Macro"

def classify_f1f2f3(cell_name):
    if pd.isna(cell_name): return 'Other'
    cell_str = cell_name.strip("_")
    if re.fullmatch(r"^\d{2,3}$", cell_str): return "f1"
    if re.search(r"(_\d{2}_\d$)|(-XL\d+$)", cell_str, flags=re.IGNORECASE): return "f3"
    if re.search(r"(CMM|BLC|DLC|MLC|PLC|CL|RAMO|[A-Z]{2}\d{5}_\d+_\d+)", cell_str, flags=re.IGNORECASE): return "f2"
    if re.search(r"(DMM|DLD|DL|LD|ML(?!C)|BL|UL|BLD)", cell_str, flags=re.IGNORECASE): return "f1"
    return 'Other'

def aggregate_f_layers(series):
    if series.empty: return None
    valid_tags = set([str(val).lower().strip() for val in series.dropna() if str(val).lower().strip() in ['f1', 'f2', 'f3']])
    if valid_tags: return "".join(sorted(valid_tags))
    return series.iloc[0]

REF_INPUT_URL = 's3://neo-advanced-analytics/site_coverage_params/referenceData/'
ref_files = get_s3_files_from_url(REF_INPUT_URL)
ref_df = pd.read_excel(ref_files[0])
ref_df.columns = ref_df.columns.astype(str).str.lower().str.strip().str.replace(' ', '_').str.replace('(', '').str.replace(')', '').str.replace('/', '_')

cell_col = next((c for c in ref_df.columns if 'cell_name' in c or 'cellname' in c or 'cell_id' in c), None)
prb_col = next((c for c in ref_df.columns if 'avail_prb' in c or 'available_prb' in c), None)
area_col = next((c for c in ref_df.columns if 'urban' in c and 'outside' in c), None)
bau_col = next((c for c in ref_df.columns if 'bau' in c or 'nic' in c), None)

ref_df = ref_df.rename(columns={cell_col: 'cell_name', prb_col: 'avail_prb', area_col: 'area_target', bau_col: 'bau_nic'})
ref_df['cell_name'] = ref_df['cell_name'].astype(str).str.strip()
ref_df = ref_df.drop_duplicates(subset=['cell_name'], keep='first')

OUTPUT_DESTINATION_URL = 's3://neo-advanced-analytics/processed_network_data/sector-calculations/xD-processed-results/'
text_cols = ['site_id', 'region', 'cluster', 'ibc_macro', 'f1f2f3', 'operator', 'area_target', 'bau_nic', 'vendor']

XD_INPUT_URL = 's3://neo-advanced-analytics/raw_network_data/ZTE Dataset (xD)/'
xd_files = get_s3_files_from_url(XD_INPUT_URL)

for file in xd_files:
    print(f"\nProcessing dataset: {file}")
    bucket, key = parse_s3_url(file)
    
    # Highly robust regex to catch year and week from filenames if needed as fallback
    year_match = re.search(r'(?:year|y)[-_=\s]*(\d{4})', key, re.IGNORECASE)
    if not year_match: year_match = re.search(r'(202\d)', key)
    file_year = int(year_match.group(1)) if year_match else 2026
    
    week_match = re.search(r'(?:week|wk|w)[-_=\s]*(\d{1,2})', key, re.IGNORECASE)
    file_week = int(week_match.group(1)) if week_match else 1
    
    df = pd.read_excel(file, engine='pyxlsb')
    df.columns = [str(c).lower().replace(' ', '_').replace('(', '').replace(')', '').replace('+','_').replace('%','pct') for c in list(df.columns)]
    
    target_cols = [col for col in df.columns if 'cellname' in col.lower() or 'cell_name' in col.lower()]
    if target_cols:
        df = df.dropna(subset=target_cols, how='all')
    
    col_map = {
        'week_number': 'week', 'cellname': 'cell_name', 
        'eric_prb_utilzation_rate': 'eric_prb_util_rate',
        'maximum_active_user_number_on_user_plane': 'max_active_user',
        'eric_data_volumeul_dl': 'eric_data_volume_ul_dl',
        'eric_dl_user_ip_thpt': 'eric_dl_user_ip_thpt',
        'eric_dl_usert_thpt_nom': 'eric_dl_user_thpt_nom'
    }
    df = df.rename(columns=col_map)
    
    # [FIX] Trust native data first. Only fallback to filename if missing/NaN.
    if 'year' not in df.columns: df['year'] = file_year
    else: df['year'] = pd.to_numeric(df['year'], errors='coerce').fillna(file_year)
        
    if 'week' not in df.columns: df['week'] = file_week
    else: df['week'] = pd.to_numeric(df['week'], errors='coerce').fillna(file_week)
        
    df['year'] = df['year'].astype(int)
    df['week'] = df['week'].astype(int)
    
    if 'eric_data_volume_ul_dl' in df.columns:
        df['eric_data_volume_ul_dl'] = pd.to_numeric(df['eric_data_volume_ul_dl'], errors='coerce').fillna(0)
        df['eric_data_volume_ul_dl'] = df['eric_data_volume_ul_dl'].apply(lambda x: x / 1000.0 if x >= 1000 else x)
        
    if 'eric_dl_user_ip_thpt' in df.columns:
        df['eric_dl_user_ip_thpt'] = pd.to_numeric(df['eric_dl_user_ip_thpt'], errors='coerce').fillna(0)
        df['eric_dl_user_ip_thpt'] = df['eric_dl_user_ip_thpt'].apply(lambda x: x / 1000.0 if x >= 1000 else x)
    
    df['cell_name'] = df['cell_name'].astype(str).str.strip()
    parsed = df['cell_name'].apply(parse_sector_info)
    df['site_id'] = parsed.apply(lambda x: x[0]).astype(str).str.upper()
    df['sector_suffix'] = parsed.apply(lambda x: x[1])
    df['operator'] = parsed.apply(lambda x: x[2])
    
    df['ibc_macro'] = df['cell_name'].apply(zoom_format)
    df['f1f2f3'] = df['cell_name'].apply(classify_f1f2f3)
    df['zoom_sector_id'] = df['site_id'] + '_' + df['ibc_macro'] + '_' + df['sector_suffix']
    
    df = df.merge(ref_df[['cell_name', 'avail_prb', 'area_target', 'bau_nic']], on='cell_name', how='left')
    
    # --- [FIX 1] COMPRESS STRINGS TO CATEGORICALS IMMEDIATELY ---
    cat_cols = ['zoom_sector_id', 'site_id', 'ibc_macro', 'f1f2f3', 'operator', 'region', 'cluster', 'area_target', 'bau_nic', 'vendor']
    for c in cat_cols:
        if c in df.columns:
            df[c] = df[c].fillna("Unknown").astype('category')

    # --- [FIX 2] DOWNCAST NUMERICS TO FLOAT32 / INT32 ---
    for c in ['eric_prb_util_rate', 'avail_prb', 'eric_data_volume_ul_dl', 'eric_dl_user_thpt_nom', 'eric_dl_user_ip_thpt_denom']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype(np.float32)
        
    if 'max_active_user' in df.columns:
        df['max_active_user'] = pd.to_numeric(df['max_active_user'], errors='coerce').fillna(0).astype(np.int32)
    
    if 'avail_prb' not in df.columns: df['avail_prb'] = 0.0
    df['prb_used'] = (df['eric_prb_util_rate'] / 100.0) * df['avail_prb']
    
    chunk_results = []
    
    # --- [FIX 3] ADD observed=True TO PREVENT CARTESIAN MEMORY EXPLOSION ---
    for (zoom_sec, wk, yr, ibc_macro), group in df.groupby(['zoom_sector_id', 'week', 'year', 'ibc_macro'], dropna=False, observed=True):
        sum_A = group['avail_prb'].sum()
        sum_B = group['prb_used'].sum()
        prb_final = (sum_B / sum_A * 100.0) if sum_A > 0 else 0
        
        sum_nom = group.get('eric_dl_user_thpt_nom', pd.Series([0])).sum()
        sum_denom = group.get('eric_dl_user_ip_thpt_denom', pd.Series([0])).sum()
        thpt_final = (sum_nom / sum_denom) if sum_denom > 0 else group.get('eric_dl_user_ip_thpt', pd.Series([0])).mean()

        chunk_results.append({
            'zoom_sector_id': zoom_sec, 'week': int(wk), 'year': int(yr),
            'site_id': group['site_id'].iloc[0],
            'region': str(group.get('region', pd.Series([None])).iloc[0]).upper().strip() if pd.notna(group.get('region', pd.Series([None])).iloc[0]) and str(group.get('region', pd.Series([None])).iloc[0]).strip() not in ['0', 'Unknown', 'nan'] else "Unknown",
            'cluster': group.get('cluster', pd.Series([None])).iloc[0],
            'ibc_macro': ibc_macro, 'f1f2f3': aggregate_f_layers(group['f1f2f3']),
            'eric_data_volume_ul_dl': float(group['eric_data_volume_ul_dl'].sum() if 'eric_data_volume_ul_dl' in group else 0), 
            'eric_prb_util_rate': float(prb_final),
            'eric_dl_user_ip_thpt': float(thpt_final), 
            'eric_max_rrc_user': int(group['max_active_user'].sum() if 'max_active_user' in group else 0),
            'max_active_user': int(group['max_active_user'].sum() if 'max_active_user' in group else 0),
            'dataset_type': 'xD', 'operator': group['operator'].iloc[0],
            'area_target': group['area_target'].dropna().iloc[0] if not group['area_target'].dropna().empty else None,
            'bau_nic': group['bau_nic'].dropna().iloc[0] if not group['bau_nic'].dropna().empty else None,
            'vendor': group['vendor'].dropna().iloc[0] if 'vendor' in group.columns and not group['vendor'].dropna().empty else 'Unknown'
        })

    if chunk_results:
        final_df = pd.DataFrame(chunk_results)
        for c in text_cols:
            if c in final_df.columns:
                final_df[c] = final_df[c].fillna("Unknown").astype(str)
                
        final_df.to_parquet(
            OUTPUT_DESTINATION_URL, 
            engine='pyarrow', 
            compression='snappy', 
            index=False, 
            partition_cols=['year', 'week']
        )
    
    del df, chunk_results
    try: del final_df
    except: pass
    gc.collect()

print("All xD files processed and saved to S3 successfully!")
