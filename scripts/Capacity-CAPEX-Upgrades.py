import pandas as pd
import numpy as np
import boto3
import json
import re
import os
import time
import gc

s3_client = boto3.client('s3')

# --- CONFIGURATIONS ---
BUCKET_NAME = 'neo-advanced-analytics'
CONGESTION_URL = f's3://{BUCKET_NAME}/processed_network_data/congestion-analysis/'
REF_URL = f's3://{BUCKET_NAME}/site_coverage_params/referenceData/'
PRE_AGG_URL = f's3://{BUCKET_NAME}/processed_network_data/pre-capex-upgrades/'
PRICING_KEY = 'capex_pricing/capex_pricing.json'
OUTPUT_URL = f's3://{BUCKET_NAME}/processed_network_data/capex-upgrades/'

BW_MAP_GLOBAL = {
    ('F1', 'L9', 'xC'): 3, ('F1', 'L18', 'xC'): 20, ('F1', 'L21', 'xC'): 20, ('F1', 'L26', 'xC'): 10,
    ('F2', 'L9', 'xC'): 10, ('F2', 'L18', 'xC'): 15, ('F2', 'L21', 'xC'): 5, ('F2', 'L26', 'xC'): 10,
    ('F1', 'L9', 'xD'): 3, ('F1', 'L18', 'xD'): 20, ('F1', 'L21', 'xD'): 15, ('F1', 'L26', 'xD'): 10,
    ('F2', 'L9', 'xD'): 10, ('F2', 'L18', 'xD'): 15, ('F2', 'L21', 'xD'): 5, ('F2', 'L26', 'xD'): 10
}

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

def load_capex_pricing():
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=PRICING_KEY)
        return json.loads(response['Body'].read().decode('utf-8'))
    except:
        return {
            "EQ": {"BW Upg": 5000, "Add Layer": 39000, "Bi-Sect Radio": 49000.72, "Bi-Sect Antenna + Accessory": 7000, "MM": 85000.42, "Swap all Sector Radio Ericsson to ZTE": 150000, "Add Sector Outdoor": 47000, "Add Sector IBC": 25000, "Accelerate NIC": 65000, "NNS": 290000, "Split Omni to Sector": 12123.75},
            "ES": {"BW Upg": 1650, "Add Layer": 36000, "Bi-Sect": 38000, "MM": 41000, "Dismantle": 29000, "Split Omni to Sector": 52000, "Swap all sector radio Ericsson to ZTE": 48000, "Add Sector Outdoor": 21000, "Add Sector IBC": 20000, "Accelerate NIC": 31000, "NNS": 48000}
        }

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

def classify_f1f2f3(cell_name):
    if pd.isna(cell_name): return 'F1'
    cell_str = str(cell_name).upper().strip("_")
    if re.fullmatch(r"^\d{2,3}$", cell_str): return "F1"              
    if re.search(r"(_\d{2}_\d$)|(-XL\d+$)", cell_str): return "F3"  
    if re.search(r"(CMM|BLC|DLC|MLC|PLC|CL|RAMO|[A-Z]{2}\d{5}_\d+_\d+)", cell_str): return "F2"  
    if re.search(r"(DMM|DLD|DL|LD|ML(?!C)|BL|UL|BLD)", cell_str): return "F1" 
    return 'F1'

def normalize_band_key(raw_band):
    s = str(raw_band).upper().strip()
    if '900' in s or 'L9' in s or 'G9' in s or 'U9' in s: return 'L9'
    if '1800' in s or 'L18' in s or '1.8' in s: return 'L18'
    if '2100' in s or 'L21' in s or '2.1' in s: return 'L21'
    if '2600' in s or 'L26' in s or '2.6' in s: return 'L26'
    
    nums = re.findall(r'\d+', s)
    if nums:
        if '900' in nums: return 'L9'
        if '1800' in nums: return 'L18'
        if '2100' in nums: return 'L21'
        if '2600' in nums: return 'L26'
        
    return 'UNKNOWN'

def get_cell_count(config_str):
    if pd.isna(config_str) or config_str == '0': return 0
    if '32T' in config_str: return 4
    if '2*' in config_str: return 2
    return 1

def extract_time_from_path(file_path):
    year, week = 2026, 0
    y_match = re.search(r'year=(\d+)', file_path, re.IGNORECASE)
    if y_match: year = int(y_match.group(1))
    
    w_match = re.search(r'/W(\d+)/', file_path, re.IGNORECASE)
    if not w_match: w_match = re.search(r'week=(\d+)', file_path, re.IGNORECASE)
    if w_match: week = int(w_match.group(1))
    
    return year, week

# --- 12-CASE UPGRADE CALCULATOR ---
def calculate_upgrade_path(sector_bands, area_target, ibc_macro, bau_nic, vendor, ds_type, pricing, sum_rb_used, sum_existing_avail, additional_rb, region):
    target_str = str(area_target).lower()
    is_urban = 'urban' in target_str or 'kmc' in target_str
    OVERHEAD = 0.75 
    d_key = 'xC' if 'xC' in str(ds_type) else 'xD'

    def cfg(f1_18, f1_21, f1_26, f1_9, f2_18, f2_21, f2_26, f2_9):
        return {"F1_L18": f1_18, "F1_L21": f1_21, "F1_L26": f1_26, "F1_L9": f1_9, 
                "F2_L18": f2_18, "F2_L21": f2_21, "F2_L26": f2_26, "F2_L9": f2_9}

    SEQ_PATH_A = [
        {"id": 1, "config": cfg("2T2R", "0", "0", "0", "0", "0", "0", "0")},
        {"id": 2, "config": cfg("2T2R", "2T2R", "0", "0", "0", "0", "0", "0")},
        {"id": 3, "config": cfg("2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "0")},
        {"id": 4, "config": cfg("2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
        {"id": 5, "config": cfg("2*2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
        {"id": 6, "config": cfg("2*2T2R", "2*2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
        {"id": 7, "config": cfg("2*2T2R", "2*2T2R", "0", "0", "2*2T2R", "0", "0", "2T2R")},
        {"id": 8, "config": cfg("2*2T2R", "2*2T2R", "2T2R", "0", "2*2T2R", "0", "0", "2T2R")},
        {"id": 9, "config": cfg("2*2T2R", "2*2T2R", "2T2R", "0", "2*2T2R", "0", "2T2R", "2T2R")},
        {"id": 10, "config": cfg("2*2T2R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2T2R", "2T2R")},
        {"id": 11, "config": cfg("2*2T2R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
        {"id": 12, "config": cfg("32T32R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
        {"id": 13, "config": cfg("32T32R", "32T32R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
        {"id": 14, "config": cfg("32T32R", "32T32R", "2*2T2R", "0", "32T32R", "0", "2*2T2R", "2T2R")}
    ]

    SEQ_PATH_B = [
        {"id": 1, "config": cfg("4T4R", "0", "0", "0", "0", "0", "0", "0")},
        {"id": 2, "config": cfg("4T4R", "4T4R", "0", "0", "0", "0", "0", "0")},
        {"id": 3, "config": cfg("4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "0")},
        {"id": 4, "config": cfg("4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
        {"id": 5, "config": cfg("2*4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
        {"id": 6, "config": cfg("2*4T4R", "2*4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
        {"id": 7, "config": cfg("2*4T4R", "2*4T4R", "0", "0", "2*4T4R", "0", "0", "4T4R")},
        {"id": 8, "config": cfg("2*4T4R", "2*4T4R", "4T4R", "0", "2*4T4R", "0", "0", "4T4R")},
        {"id": 9, "config": cfg("2*4T4R", "2*4T4R", "4T4R", "0", "2*4T4R", "0", "4T4R", "4T4R")},
        {"id": 10, "config": cfg("2*4T4R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "4T4R", "4T4R")},
        {"id": 11, "config": cfg("2*4T4R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
        {"id": 12, "config": cfg("32T32R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
        {"id": 13, "config": cfg("32T32R", "32T32R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
        {"id": 14, "config": cfg("32T32R", "32T32R", "2*4T4R", "0", "32T32R", "0", "2*4T4R", "4T4R")}
    ]

    is_path_b = False
    current_config_map = {}
    current_prb_map = {}
    
    HW_RANK = {"0": 0, "2T2R": 1, "4T4R": 2, "2*2T2R": 3, "2*4T4R": 4, "32T32R": 5}
    
    for b in sector_bands:
        if b['band'] == 'UNKNOWN': continue
            
        key = f"{b['layer']}_{b['band']}"
        curr_hw = str(b.get('current_xtxr', '2T2R')).upper()
        current_prb_map[key] = b.get('avail_prb', 0)
        
        if '32T' in curr_hw or 'MM' in curr_hw: curr_hw = '32T32R'
        elif '4T' in curr_hw: curr_hw = '4T4R'
        elif '2T' in curr_hw: curr_hw = '2T2R'
        else: curr_hw = '2T2R'
        
        if '2*' in str(b.get('current_xtxr', '')) or '2X' in str(b.get('current_xtxr', '')).upper() or 'BI' in str(b.get('current_xtxr', '')).upper():
            if not curr_hw.startswith('2*'): curr_hw = '2*' + curr_hw
            
        current_config_map[key] = curr_hw
        if '4T' in curr_hw or '32T' in curr_hw: is_path_b = True

    if additional_rb <= 0:
        curr_prb_pct = (sum_rb_used / sum_existing_avail) * 100.0 if sum_existing_avail > 0 else 0.0
        return current_config_map, current_config_map, None, 0.0, 0.0, 0.0, curr_prb_pct

    ACTIVE_SEQUENCE = SEQ_PATH_B if is_path_b else SEQ_PATH_A

    def build_case_label_and_capex(bw_exp, bd_add, h_split, h_mm, f2_split, added_layers):
        eq_prices = pricing["EQ"]; es_prices = pricing["ES"]
        labels = []; eq_costs = []; es_options = []; has_primary = False
        
        layer_mult = {1: 1.0, 2: 1.7, 3: 2.7, 4: 3.5, 5: 4.5, 6: 5.5, 7: 6.5, 8: 7.2}.get(added_layers, 1.0) if added_layers > 0 else 0
        add_layer_eq_cost = eq_prices["Add Layer"] * layer_mult

        if h_mm: 
            labels.append("Case 4 (MM Only)"); eq_costs.append(eq_prices["MM"]); es_options.append(es_prices["MM"]); has_primary = True
        else:
            if bw_exp and bd_add and h_split: 
                labels.extend(["Case 5 (Add bandwidth + add layer)", "Case 2 (Add Bi-Sector Only)"])
                eq_costs.extend([eq_prices["BW Upg"], add_layer_eq_cost, eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
                es_options.extend([es_prices["Add Layer"], es_prices["Bi-Sect"]])
                has_primary = True
            elif bw_exp and bd_add: 
                labels.append("Case 5 (Add bandwidth + add layer)"); eq_costs.extend([eq_prices["BW Upg"], add_layer_eq_cost]); es_options.append(es_prices["Add Layer"]); has_primary = True
            elif bw_exp and h_split: 
                labels.append("Case 6 (Add bi-sector + Add Bandwidth)"); eq_costs.extend([eq_prices["BW Upg"], eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]]); es_options.append(es_prices["Bi-Sect"]); has_primary = True
            elif h_split and bd_add: 
                labels.append("Case 7 (Add Bi-Sector + Add Layer)"); eq_costs.extend([add_layer_eq_cost, eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]]); es_options.append(es_prices["Bi-Sect"]); has_primary = True
            elif bw_exp: 
                labels.append("Case 1 (Bandwidth)"); eq_costs.append(eq_prices["BW Upg"]); es_options.append(es_prices["BW Upg"]); has_primary = True
            elif h_split: 
                labels.append("Case 2 (Add Bi-Sector Only)"); eq_costs.extend([eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]]); es_options.append(es_prices["Bi-Sect"]); has_primary = True
            elif bd_add: 
                labels.append("Case 3 (Add network layer only)"); eq_costs.append(add_layer_eq_cost); es_options.append(es_prices["Add Layer"]); has_primary = True
            
        if not has_primary: 
            labels.insert(0, "Case 3 (Add network layer only)"); eq_costs.append(eq_prices["Add Layer"]); es_options.append(es_prices["Add Layer"])

        if ibc_macro and 'inbuilding' in str(ibc_macro).lower(): 
            labels.append("Case 8 (Add IBC)"); eq_costs.append(eq_prices["Add Sector IBC"]); es_options.append(es_prices["Add Sector IBC"])
        if f2_split: 
            labels.append("Case 9 (Add BI/2)"); eq_costs.extend([eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]]); es_options.append(es_prices["Bi-Sect"])
        if bau_nic and 'bau' in str(bau_nic).lower(): 
            labels.append("Case 10 (Accelerate NIC)"); eq_costs.append(eq_prices["Accelerate NIC"]); es_options.append(es_prices["Accelerate NIC"])
        
        if d_key == 'xC' and vendor and 'ericsson' in str(vendor).lower(): 
            reg_str = str(region).upper()
            target_vendor = "Huawei" if reg_str in ['EASTERN', 'SOUTHERN'] else "ZTE"
            labels.append(f"Case 12 (Swap E2{target_vendor[0]})")
            eq_costs.append(eq_prices["Swap all Sector Radio Ericsson to ZTE"])
            es_options.append(es_prices["Swap all sector radio Ericsson to ZTE"])
        
        final_eq = sum(eq_costs)
        final_es = max(es_options) if es_options else 0
        total_capex = final_eq + final_es
        
        return " + ".join(labels), total_capex, final_eq, final_es

    for step in ACTIVE_SEQUENCE:
        cfg_map = step['config']
        merged_config = {}
        rb_offered = 0.0
        
        added_layers_count = 0
        has_split = False
        has_mm = False
        f2_split = False
        bw_expanded = False
        
        for k in ["F1_L18", "F1_L21", "F1_L26", "F1_L9", "F2_L18", "F2_L21", "F2_L26", "F2_L9"]:
            curr_ant = current_config_map.get(k, '0')
            step_ant = cfg_map.get(k, '0')
            
            rank_curr = HW_RANK.get(curr_ant, 0)
            rank_step = HW_RANK.get(step_ant, 0)
            
            merged_ant = step_ant if rank_step > rank_curr else curr_ant
            merged_config[k] = merged_ant
            
            parts = k.split('_')
            layer, band = parts[0], parts[1]
            lookup_band = band
            if '900' in band or 'L9' in band: lookup_band = 'L9'
            elif '18' in band: lookup_band = 'L18'
            elif '21' in band: lookup_band = 'L21'
            elif '26' in band: lookup_band = 'L26'
            
            bw_val = BW_MAP_GLOBAL.get((layer, lookup_band, d_key), 0)
            raw_prb = 5.0 * bw_val
            
            existing_band_prb = current_prb_map.get(k, 0)
            if curr_ant != '0' and existing_band_prb < raw_prb:
                rb_offered += (raw_prb - existing_band_prb)
                bw_expanded = True
                
            if rank_step > rank_curr:
                if curr_ant == '0': added_layers_count += 1
                if '2*' in merged_ant and '2*' not in curr_ant: has_split = True
                if '32T' in merged_ant and '32T' not in curr_ant: has_mm = True
                if k.startswith('F2_') and '2*' in merged_ant and '2*' not in curr_ant: f2_split = True
                
                if raw_prb > 0:
                    avail_cells = get_cell_count(curr_ant)
                    target_cells = get_cell_count(merged_ant)
                    
                    if target_cells > avail_cells:
                        net_cells = target_cells - avail_cells
                        if merged_ant in ['2T2R', '4T4R']:
                            rb_offered += net_cells * raw_prb * 1.0
                        elif merged_ant == '2*2T2R':
                            multiplier = 1.65 if is_urban else 1.43
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD
                        elif merged_ant == '2*4T4R':
                            multiplier = 1.82 if is_urban else 1.57
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD
                        elif merged_ant == '32T32R':
                            multiplier = 3.00 if is_urban else 2.61
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD

        if rb_offered == 0:
            continue

        if (rb_offered + sum_existing_avail) > 0:
            projected_prb = (sum_rb_used / (rb_offered + sum_existing_avail)) * 100.0
            if projected_prb <= 73.0:
                band_added = added_layers_count > 0
                lbl, capex, eq, es = build_case_label_and_capex(bw_expanded, band_added, has_split, has_mm, f2_split, added_layers_count)
                return current_config_map, merged_config, lbl, capex, eq, es, projected_prb

    exhausted_labels = ["Case 11 (NNS)"]
    if ibc_macro and 'inbuilding' in str(ibc_macro).lower(): exhausted_labels.append("Case 8 (Add IBC)")
    if bau_nic and 'bau' in str(bau_nic).lower(): exhausted_labels.append("Case 10 (Accelerate NIC)")
    if d_key == 'xC' and vendor and 'ericsson' in str(vendor).lower(): 
        reg_str = str(region).upper()
        target_vendor = "Huawei" if reg_str in ['EASTERN', 'SOUTHERN'] else "ZTE"
        exhausted_labels.append(f"Case 12 (Swap E2{target_vendor[0]})")
    
    eq_nns = pricing["EQ"]["NNS"]
    es_nns = pricing["ES"]["NNS"]
    total_exhausted_capex = eq_nns + es_nns
    
    final_merged = {}
    last_cfg = ACTIVE_SEQUENCE[-1]['config']
    for k in ["F1_L18", "F1_L21", "F1_L26", "F1_L9", "F2_L18", "F2_L21", "F2_L26", "F2_L9"]:
        c_ant = current_config_map.get(k, '0')
        s_ant = last_cfg.get(k, '0')
        final_merged[k] = s_ant if HW_RANK.get(s_ant, 0) > HW_RANK.get(c_ant, 0) else c_ant
        
    return current_config_map, final_merged, " + ".join(exhausted_labels), total_exhausted_capex, eq_nns, es_nns, 100.0

def process_capex_upgrades():
    pricing = load_capex_pricing()

    print("1. Loading Reference Data for Hardware Baseline...", flush=True)
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
                if 'xc ref' in sheet_name.lower() or 'xd ref' in sheet_name.lower():
                    df_sheet.columns = df_sheet.columns.astype(str).str.lower().str.strip()
                    ref_dfs.append(df_sheet)
        os.remove(tmp_ref)
        
    master_ref = pd.concat(ref_dfs, ignore_index=True)
    del ref_dfs
    gc.collect() 
    
    cell_col = next((c for c in master_ref.columns if 'cell' in c and 'name' in c), None)
    band_cols = [c for c in master_ref.columns if ('band' in c or 'layer' in c) and 'width' not in c and 'mhz' not in c]
    band_col = band_cols[0] if band_cols else next((c for c in master_ref.columns if 'freq' in c), None)
    xtxr_cols = [c for c in master_ref.columns if 'txrx' in c or 'xtxr' in c or 'mimo' in c or 'antenna' in c]
    xtxr_col = xtxr_cols[0] if xtxr_cols else None
    bw_cols = [c for c in master_ref.columns if 'bw' in c or 'width' in c or 'mhz' in c]
    bw_col = bw_cols[0] if bw_cols else None

    if not band_col and cell_col:
        def extract_from_cell(cell):
            c = str(cell).upper()
            if '900' in c or 'L9' in c or '_9_' in c or '-9' in c: return 'L9'
            if '1800' in c or 'L18' in c or '_18_' in c or '-18' in c: return 'L18'
            if '2100' in c or 'L21' in c or '_21_' in c or '-21' in c: return 'L21'
            if '2600' in c or 'L26' in c or '_26_' in c or '-26' in c or '_7_' in c or '-7' in c: return 'L26'
            return 'UNKNOWN'
        master_ref['extracted_band'] = master_ref[cell_col].apply(extract_from_cell)
        band_col = 'extracted_band'

    master_ref['avail_prb'] = pd.to_numeric(master_ref[bw_col], errors='coerce').fillna(0) * 5.0 if bw_col else 0.0
    master_ref['cell_name_clean'] = master_ref[cell_col].astype(str).str.strip()
    
    parsed_info = master_ref['cell_name_clean'].apply(parse_sector_info)
    master_ref['site_id'] = parsed_info.apply(lambda x: x[0])
    master_ref['sector_suffix'] = parsed_info.apply(lambda x: x[1])
    master_ref['ibc_macro'] = master_ref['cell_name_clean'].apply(zoom_format)
    master_ref['f1f2f3'] = master_ref['cell_name_clean'].apply(classify_f1f2f3)
    master_ref['zoom_sector_id'] = master_ref['site_id'].astype(str).str.upper() + '_' + master_ref['ibc_macro'] + '_' + master_ref['sector_suffix']

    print("Pre-processing Reference Data into memory-safe dictionary...", flush=True)
    ref_dict = {}
    for row in master_ref.itertuples(index=False):
        sid = row.zoom_sector_id
        if sid not in ref_dict:
            ref_dict[sid] = []
            
        b_val = getattr(row, band_col) if band_col and hasattr(row, band_col) else getattr(row, 'extracted_band', 'UNKNOWN')
        x_val = getattr(row, xtxr_col) if xtxr_col and hasattr(row, xtxr_col) else '2T2R'
        
        ref_dict[sid].append({
            'band': b_val,
            'f1f2f3': row.f1f2f3,
            'xtxr': x_val,
            'avail_prb': row.avail_prb
        })
    
    del master_ref
    gc.collect()

    print("2. Loading Congestion Analysis Data...", flush=True)
    cong_files = get_s3_files(CONGESTION_URL)
    if not cong_files: return
    
    c_list = []
    for f in cong_files:
        try:
            try:
                temp_df = pd.read_parquet(f, columns=['zoom_sector_id', 'area_target', 'ibc_macro', 'bau_nic', 'operator', 'region', 'year', 'week'])
            except ValueError:
                temp_df = pd.read_parquet(f, columns=['zoom_sector_id', 'area_target', 'ibc_macro', 'bau_nic', 'operator', 'region'])
            
            if 'year' not in temp_df.columns or 'week' not in temp_df.columns:
                yr, wk = extract_time_from_path(f)
                if 'year' not in temp_df.columns: temp_df['year'] = yr
                if 'week' not in temp_df.columns: temp_df['week'] = wk
                
            c_list.append(temp_df)
        except Exception as e:
            continue
            
    cong_df = pd.concat(c_list, ignore_index=True)
    cong_df['year'] = pd.to_numeric(cong_df['year'], errors='coerce')
    cong_df['week'] = pd.to_numeric(cong_df['week'], errors='coerce')
    cong_df = cong_df.drop_duplicates(subset=['zoom_sector_id', 'year', 'week'])

    print("3. Processing Pre-Aggregated Metrics 1 File at a Time...", flush=True)
    pre_agg_files = get_s3_files(PRE_AGG_URL, extensions=('.parquet',))
    if not pre_agg_files:
        print("No Pre-Aggregated data found.")
        return
        
    for file_idx, f in enumerate(pre_agg_files):
        print(f"-> Processing File {file_idx + 1}/{len(pre_agg_files)}: {f}", flush=True)
        try:
            temp_df = pd.read_parquet(f)
            
            # Identify partition
            if 'dataset_type' not in temp_df.columns:
                if '/xC/' in f: ds_type = 'xC'
                elif '/xD/' in f: ds_type = 'xD'
                else: ds_type = 'Unknown'
                temp_df['dataset_type'] = ds_type
            else:
                ds_type = temp_df['dataset_type'].iloc[0]
                
            if 'year' not in temp_df.columns or 'week' not in temp_df.columns:
                yr, wk = extract_time_from_path(f)
                if 'year' not in temp_df.columns: temp_df['year'] = yr
                if 'week' not in temp_df.columns: temp_df['week'] = wk
            else:
                yr = temp_df['year'].iloc[0]
                wk = temp_df['week'].iloc[0]
                
            temp_df['year'] = pd.to_numeric(temp_df['year'], errors='coerce')
            temp_df['week'] = pd.to_numeric(temp_df['week'], errors='coerce')
            temp_df = temp_df.drop_duplicates(subset=['zoom_sector_id', 'year', 'week'])

            # Filter corresponding congestion
            chunk_cong_df = cong_df[(cong_df['year'] == yr) & (cong_df['week'] == wk)]
            if chunk_cong_df.empty:
                del temp_df
                gc.collect()
                continue
                
            master_context_df = pd.merge(temp_df, chunk_cong_df, on=['zoom_sector_id', 'year', 'week'], how='inner')
            del temp_df, chunk_cong_df
            gc.collect()

            if master_context_df.empty:
                continue

            final_capex_results = []
            
            for idx, context in master_context_df.iterrows():
                sector_id = context['zoom_sector_id']
                year = context['year']
                week = context['week']
                
                if sector_id not in ref_dict:
                    continue
                    
                cells = ref_dict[sector_id]
                
                vendor = context.get('operator', 'Unknown') 
                region = context.get('region', 'Unknown') 
                
                sum_rb_used = context.get('sum_rb_used', 0.0)
                sum_existing_avail = context.get('sum_existing_prb', 0.0)
                additional_rb = context.get('additional_rb', 0.0)

                grouped_cells = {}
                for c in cells:
                    k = (c['band'], c['f1f2f3'])
                    if k not in grouped_cells:
                        grouped_cells[k] = []
                    grouped_cells[k].append(c)

                aggregated_bands = []
                for (b_raw, l_raw), c_group in grouped_cells.items():
                    band_val = normalize_band_key(b_raw)
                    layer_val = str(l_raw).upper() if pd.notna(l_raw) else 'F1'
                    base_xtxr = str(c_group[0]['xtxr']) if pd.notna(c_group[0]['xtxr']) else '2T2R'
                    
                    total_avail_prb = sum([x['avail_prb'] for x in c_group])
                    if total_avail_prb == 0:
                        lookup = BW_MAP_GLOBAL.get((layer_val, band_val, ds_type if ds_type == 'xC' else 'xD'), 0)
                        total_avail_prb = lookup * 5.0
                    
                    aggregated_bands.append({
                        'band': band_val, 
                        'layer': layer_val,
                        'avail_prb': total_avail_prb,
                        'current_xtxr': base_xtxr
                    })

                curr_map, sugg_map, case_label, total_capex, eq_capex, es_capex, projected_prb = calculate_upgrade_path(
                    aggregated_bands, 
                    context.get('area_target', 'Unknown'), 
                    context.get('ibc_macro', 'Unknown'), 
                    context.get('bau_nic', 'Unknown'), 
                    vendor,
                    ds_type, 
                    pricing,
                    sum_rb_used,
                    sum_existing_avail,
                    additional_rb,
                    region 
                )
                
                final_capex_results.append({
                    'zoom_sector_id': sector_id,
                    # RENAME THESE TO AVOID HIVE METADATA COLLISIONS
                    'data_year': year,
                    'data_week': week,
                    'area_target': context.get('area_target', 'Unknown'),
                    'dataset_type': ds_type,
                    'suggested_upgrade_case': case_label,
                    'estimated_total_capex_rm': float(total_capex),
                    'eq_capex_rm': float(eq_capex), 
                    'es_capex_rm': float(es_capex), 
                    'projected_prb_pct': float(projected_prb),
                    
                    'current_f1_l9':  curr_map.get('F1_L9', '0'),  'suggested_f1_l9':  sugg_map.get('F1_L9', '0'),
                    'current_f1_l18': curr_map.get('F1_L18', '0'), 'suggested_f1_l18': sugg_map.get('F1_L18', '0'),
                    'current_f1_l21': curr_map.get('F1_L21', '0'), 'suggested_f1_l21': sugg_map.get('F1_L21', '0'),
                    'current_f1_l26': curr_map.get('F1_L26', '0'), 'suggested_f1_l26': sugg_map.get('F1_L26', '0'),
                    
                    'current_f2_l9':  curr_map.get('F2_L9', '0'),  'suggested_f2_l9':  sugg_map.get('F2_L9', '0'),
                    'current_f2_l18': curr_map.get('F2_L18', '0'), 'suggested_f2_l18': sugg_map.get('F2_L18', '0'),
                    'current_f2_l21': curr_map.get('F2_L21', '0'), 'suggested_f2_l21': sugg_map.get('F2_L21', '0'),
                    'current_f2_l26': curr_map.get('F2_L26', '0'), 'suggested_f2_l26': sugg_map.get('F2_L26', '0')
                })

            if final_capex_results:
                final_df = pd.DataFrame(final_capex_results)
                final_df.replace({'-': None, np.nan: None}, inplace=True)
                
                wk_str = f"W{int(wk):02d}"
                file_name = os.path.basename(f)
                s3_path = f"{OUTPUT_URL}{ds_type}/year={int(yr)}/{wk_str}/capex_{file_name}"
                
                final_df.to_parquet(s3_path, engine='pyarrow', compression='snappy', index=False)
                print(f"   -> Saved {len(final_df)} rows to {s3_path}", flush=True)

            # FORCE CLEAR RAM FOR THE NEXT FILE
            del master_context_df, final_capex_results
            if 'final_df' in locals(): del final_df
            gc.collect()

        except Exception as e:
            print(f"   -> ERROR processing file {f}: {str(e)}", flush=True)
            continue

if __name__ == '__main__':
    process_capex_upgrades()
