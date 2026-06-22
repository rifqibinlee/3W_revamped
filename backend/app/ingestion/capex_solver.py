"""12-case CAPEX upgrade solver.

Ports `calculate_upgrade_path` from `scripts_example/Capacity-CAPEX-Upgrades.py`
near-verbatim. This is an iterative state machine over two 14-step antenna
upgrade sequences (2T2R-rooted "Path A" vs 4T4R-rooted "Path B") with an
early exit once projected PRB utilization drops to <=73% — there's no
sensible vectorized/SQL form for this, it's fundamentally a per-sector
search, exactly as the legacy script implements it. Kept here as a pure
function so it's unit-testable in isolation from the data-loading stage.
"""

DEFAULT_PRICING = {
    "EQ": {
        "BW Upg": 5000, "Add Layer": 39000, "Bi-Sect Radio": 49000.72,
        "Bi-Sect Antenna + Accessory": 7000, "MM": 85000.42,
        "Swap all Sector Radio Ericsson to ZTE": 150000, "Add Sector Outdoor": 47000,
        "Add Sector IBC": 25000, "Accelerate NIC": 65000, "NNS": 290000,
        "Split Omni to Sector": 12123.75,
    },
    "ES": {
        "BW Upg": 1650, "Add Layer": 36000, "Bi-Sect": 38000, "MM": 41000,
        "Dismantle": 29000, "Split Omni to Sector": 52000,
        "Swap all sector radio Ericsson to ZTE": 48000, "Add Sector Outdoor": 21000,
        "Add Sector IBC": 20000, "Accelerate NIC": 31000, "NNS": 48000,
    },
}

BW_MAP_GLOBAL = {
    ("F1", "L9", "xC"): 3, ("F1", "L18", "xC"): 20, ("F1", "L21", "xC"): 20, ("F1", "L26", "xC"): 10,
    ("F2", "L9", "xC"): 10, ("F2", "L18", "xC"): 15, ("F2", "L21", "xC"): 5, ("F2", "L26", "xC"): 10,
    ("F1", "L9", "xD"): 3, ("F1", "L18", "xD"): 20, ("F1", "L21", "xD"): 15, ("F1", "L26", "xD"): 10,
    ("F2", "L9", "xD"): 10, ("F2", "L18", "xD"): 15, ("F2", "L21", "xD"): 5, ("F2", "L26", "xD"): 10,
}

HW_RANK = {"0": 0, "2T2R": 1, "4T4R": 2, "2*2T2R": 3, "2*4T4R": 4, "32T32R": 5}

LAYER_BAND_KEYS = ("F1_L18", "F1_L21", "F1_L26", "F1_L9", "F2_L18", "F2_L21", "F2_L26", "F2_L9")


def _cfg(f1_18, f1_21, f1_26, f1_9, f2_18, f2_21, f2_26, f2_9):
    return {"F1_L18": f1_18, "F1_L21": f1_21, "F1_L26": f1_26, "F1_L9": f1_9,
            "F2_L18": f2_18, "F2_L21": f2_21, "F2_L26": f2_26, "F2_L9": f2_9}


SEQ_PATH_A = [
    {"id": 1, "config": _cfg("2T2R", "0", "0", "0", "0", "0", "0", "0")},
    {"id": 2, "config": _cfg("2T2R", "2T2R", "0", "0", "0", "0", "0", "0")},
    {"id": 3, "config": _cfg("2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "0")},
    {"id": 4, "config": _cfg("2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
    {"id": 5, "config": _cfg("2*2T2R", "2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
    {"id": 6, "config": _cfg("2*2T2R", "2*2T2R", "0", "0", "2T2R", "0", "0", "2T2R")},
    {"id": 7, "config": _cfg("2*2T2R", "2*2T2R", "0", "0", "2*2T2R", "0", "0", "2T2R")},
    {"id": 8, "config": _cfg("2*2T2R", "2*2T2R", "2T2R", "0", "2*2T2R", "0", "0", "2T2R")},
    {"id": 9, "config": _cfg("2*2T2R", "2*2T2R", "2T2R", "0", "2*2T2R", "0", "2T2R", "2T2R")},
    {"id": 10, "config": _cfg("2*2T2R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2T2R", "2T2R")},
    {"id": 11, "config": _cfg("2*2T2R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
    {"id": 12, "config": _cfg("32T32R", "2*2T2R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
    {"id": 13, "config": _cfg("32T32R", "32T32R", "2*2T2R", "0", "2*2T2R", "0", "2*2T2R", "2T2R")},
    {"id": 14, "config": _cfg("32T32R", "32T32R", "2*2T2R", "0", "32T32R", "0", "2*2T2R", "2T2R")},
]

SEQ_PATH_B = [
    {"id": 1, "config": _cfg("4T4R", "0", "0", "0", "0", "0", "0", "0")},
    {"id": 2, "config": _cfg("4T4R", "4T4R", "0", "0", "0", "0", "0", "0")},
    {"id": 3, "config": _cfg("4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "0")},
    {"id": 4, "config": _cfg("4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
    {"id": 5, "config": _cfg("2*4T4R", "4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
    {"id": 6, "config": _cfg("2*4T4R", "2*4T4R", "0", "0", "4T4R", "0", "0", "4T4R")},
    {"id": 7, "config": _cfg("2*4T4R", "2*4T4R", "0", "0", "2*4T4R", "0", "0", "4T4R")},
    {"id": 8, "config": _cfg("2*4T4R", "2*4T4R", "4T4R", "0", "2*4T4R", "0", "0", "4T4R")},
    {"id": 9, "config": _cfg("2*4T4R", "2*4T4R", "4T4R", "0", "2*4T4R", "0", "4T4R", "4T4R")},
    {"id": 10, "config": _cfg("2*4T4R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "4T4R", "4T4R")},
    {"id": 11, "config": _cfg("2*4T4R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
    {"id": 12, "config": _cfg("32T32R", "2*4T4R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
    {"id": 13, "config": _cfg("32T32R", "32T32R", "2*4T4R", "0", "2*4T4R", "0", "2*4T4R", "4T4R")},
    {"id": 14, "config": _cfg("32T32R", "32T32R", "2*4T4R", "0", "32T32R", "0", "2*4T4R", "4T4R")},
]


def _get_cell_count(config_str: str) -> int:
    if config_str is None or config_str == "0":
        return 0
    if "32T" in config_str:
        return 4
    if "2*" in config_str:
        return 2
    return 1


def normalize_band_key(raw_band) -> str:
    s = str(raw_band).upper().strip()
    if "900" in s or "L9" in s or "G9" in s or "U9" in s:
        return "L9"
    if "1800" in s or "L18" in s or "1.8" in s:
        return "L18"
    if "2100" in s or "L21" in s or "2.1" in s:
        return "L21"
    if "2600" in s or "L26" in s or "2.6" in s:
        return "L26"
    return "UNKNOWN"


def calculate_upgrade_path(
    sector_bands: list[dict],
    area_target,
    ibc_macro,
    bau_nic,
    vendor,
    ds_type: str,
    pricing: dict,
    sum_rb_used: float,
    sum_existing_avail: float,
    additional_rb: float,
    region,
) -> tuple[dict, dict, str | None, float, float, float, float]:
    """Returns (current_config_map, suggested_config_map, case_label,
    total_capex, eq_capex, es_capex, projected_prb_pct)."""
    target_str = str(area_target).lower()
    is_urban = "urban" in target_str or "kmc" in target_str
    OVERHEAD = 0.75
    d_key = "xC" if "xC" in str(ds_type) else "xD"

    is_path_b = False
    current_config_map: dict[str, str] = {}
    current_prb_map: dict[str, float] = {}

    for b in sector_bands:
        if b["band"] == "UNKNOWN":
            continue

        key = f"{b['layer']}_{b['band']}"
        curr_hw = str(b.get("current_xtxr", "2T2R")).upper()
        current_prb_map[key] = b.get("avail_prb", 0)

        if "32T" in curr_hw or "MM" in curr_hw:
            curr_hw = "32T32R"
        elif "4T" in curr_hw:
            curr_hw = "4T4R"
        elif "2T" in curr_hw:
            curr_hw = "2T2R"
        else:
            curr_hw = "2T2R"

        raw_xtxr = str(b.get("current_xtxr", ""))
        if "2*" in raw_xtxr or "2X" in raw_xtxr.upper() or "BI" in raw_xtxr.upper():
            if not curr_hw.startswith("2*"):
                curr_hw = "2*" + curr_hw

        current_config_map[key] = curr_hw
        if "4T" in curr_hw or "32T" in curr_hw:
            is_path_b = True

    if additional_rb <= 0:
        curr_prb_pct = (sum_rb_used / sum_existing_avail) * 100.0 if sum_existing_avail > 0 else 0.0
        return current_config_map, current_config_map, None, 0.0, 0.0, 0.0, curr_prb_pct

    active_sequence = SEQ_PATH_B if is_path_b else SEQ_PATH_A

    def build_case_label_and_capex(bw_exp, bd_add, h_split, h_mm, f2_split, added_layers):
        eq_prices = pricing["EQ"]
        es_prices = pricing["ES"]
        labels: list[str] = []
        eq_costs: list[float] = []
        es_options: list[float] = []
        has_primary = False

        layer_mult = (
            {1: 1.0, 2: 1.7, 3: 2.7, 4: 3.5, 5: 4.5, 6: 5.5, 7: 6.5, 8: 7.2}.get(added_layers, 1.0)
            if added_layers > 0 else 0
        )
        add_layer_eq_cost = eq_prices["Add Layer"] * layer_mult

        if h_mm:
            labels.append("Case 4 (MM Only)")
            eq_costs.append(eq_prices["MM"])
            es_options.append(es_prices["MM"])
            has_primary = True
        else:
            if bw_exp and bd_add and h_split:
                labels.extend(["Case 5 (Add bandwidth + add layer)", "Case 2 (Add Bi-Sector Only)"])
                eq_costs.extend([eq_prices["BW Upg"], add_layer_eq_cost, eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
                es_options.extend([es_prices["Add Layer"], es_prices["Bi-Sect"]])
                has_primary = True
            elif bw_exp and bd_add:
                labels.append("Case 5 (Add bandwidth + add layer)")
                eq_costs.extend([eq_prices["BW Upg"], add_layer_eq_cost])
                es_options.append(es_prices["Add Layer"])
                has_primary = True
            elif bw_exp and h_split:
                labels.append("Case 6 (Add bi-sector + Add Bandwidth)")
                eq_costs.extend([eq_prices["BW Upg"], eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
                es_options.append(es_prices["Bi-Sect"])
                has_primary = True
            elif h_split and bd_add:
                labels.append("Case 7 (Add Bi-Sector + Add Layer)")
                eq_costs.extend([add_layer_eq_cost, eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
                es_options.append(es_prices["Bi-Sect"])
                has_primary = True
            elif bw_exp:
                labels.append("Case 1 (Bandwidth)")
                eq_costs.append(eq_prices["BW Upg"])
                es_options.append(es_prices["BW Upg"])
                has_primary = True
            elif h_split:
                labels.append("Case 2 (Add Bi-Sector Only)")
                eq_costs.extend([eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
                es_options.append(es_prices["Bi-Sect"])
                has_primary = True
            elif bd_add:
                labels.append("Case 3 (Add network layer only)")
                eq_costs.append(add_layer_eq_cost)
                es_options.append(es_prices["Add Layer"])
                has_primary = True

        if not has_primary:
            labels.insert(0, "Case 3 (Add network layer only)")
            eq_costs.append(eq_prices["Add Layer"])
            es_options.append(es_prices["Add Layer"])

        if ibc_macro and "inbuilding" in str(ibc_macro).lower():
            labels.append("Case 8 (Add IBC)")
            eq_costs.append(eq_prices["Add Sector IBC"])
            es_options.append(es_prices["Add Sector IBC"])
        if f2_split:
            labels.append("Case 9 (Add BI/2)")
            eq_costs.extend([eq_prices["Bi-Sect Radio"], eq_prices["Bi-Sect Antenna + Accessory"]])
            es_options.append(es_prices["Bi-Sect"])
        if bau_nic and "bau" in str(bau_nic).lower():
            labels.append("Case 10 (Accelerate NIC)")
            eq_costs.append(eq_prices["Accelerate NIC"])
            es_options.append(es_prices["Accelerate NIC"])

        if d_key == "xC" and vendor and "ericsson" in str(vendor).lower():
            reg_str = str(region).upper()
            target_vendor = "Huawei" if reg_str in ["EASTERN", "SOUTHERN"] else "ZTE"
            labels.append(f"Case 12 (Swap E2{target_vendor[0]})")
            eq_costs.append(eq_prices["Swap all Sector Radio Ericsson to ZTE"])
            es_options.append(es_prices["Swap all sector radio Ericsson to ZTE"])

        final_eq = sum(eq_costs)
        final_es = max(es_options) if es_options else 0
        total_capex = final_eq + final_es

        return " + ".join(labels), total_capex, final_eq, final_es

    for step in active_sequence:
        cfg_map = step["config"]
        merged_config: dict[str, str] = {}
        rb_offered = 0.0

        added_layers_count = 0
        has_split = False
        has_mm = False
        f2_split = False
        bw_expanded = False

        for k in LAYER_BAND_KEYS:
            curr_ant = current_config_map.get(k, "0")
            step_ant = cfg_map.get(k, "0")

            rank_curr = HW_RANK.get(curr_ant, 0)
            rank_step = HW_RANK.get(step_ant, 0)

            merged_ant = step_ant if rank_step > rank_curr else curr_ant
            merged_config[k] = merged_ant

            layer, band = k.split("_")
            lookup_band = band
            if "900" in band or "L9" in band:
                lookup_band = "L9"
            elif "18" in band:
                lookup_band = "L18"
            elif "21" in band:
                lookup_band = "L21"
            elif "26" in band:
                lookup_band = "L26"

            bw_val = BW_MAP_GLOBAL.get((layer, lookup_band, d_key), 0)
            raw_prb = 5.0 * bw_val

            existing_band_prb = current_prb_map.get(k, 0)
            if curr_ant != "0" and existing_band_prb < raw_prb:
                rb_offered += raw_prb - existing_band_prb
                bw_expanded = True

            if rank_step > rank_curr:
                if curr_ant == "0":
                    added_layers_count += 1
                if "2*" in merged_ant and "2*" not in curr_ant:
                    has_split = True
                if "32T" in merged_ant and "32T" not in curr_ant:
                    has_mm = True
                if k.startswith("F2_") and "2*" in merged_ant and "2*" not in curr_ant:
                    f2_split = True

                if raw_prb > 0:
                    avail_cells = _get_cell_count(curr_ant)
                    target_cells = _get_cell_count(merged_ant)

                    if target_cells > avail_cells:
                        net_cells = target_cells - avail_cells
                        if merged_ant in ("2T2R", "4T4R"):
                            rb_offered += net_cells * raw_prb * 1.0
                        elif merged_ant == "2*2T2R":
                            multiplier = 1.65 if is_urban else 1.43
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD
                        elif merged_ant == "2*4T4R":
                            multiplier = 1.82 if is_urban else 1.57
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD
                        elif merged_ant == "32T32R":
                            multiplier = 3.00 if is_urban else 2.61
                            rb_offered += net_cells * raw_prb * multiplier * OVERHEAD

        if rb_offered == 0:
            continue

        if (rb_offered + sum_existing_avail) > 0:
            projected_prb = (sum_rb_used / (rb_offered + sum_existing_avail)) * 100.0
            if projected_prb <= 73.0:
                band_added = added_layers_count > 0
                lbl, capex, eq, es = build_case_label_and_capex(
                    bw_expanded, band_added, has_split, has_mm, f2_split, added_layers_count
                )
                return current_config_map, merged_config, lbl, capex, eq, es, projected_prb

    exhausted_labels = ["Case 11 (NNS)"]
    if ibc_macro and "inbuilding" in str(ibc_macro).lower():
        exhausted_labels.append("Case 8 (Add IBC)")
    if bau_nic and "bau" in str(bau_nic).lower():
        exhausted_labels.append("Case 10 (Accelerate NIC)")
    if d_key == "xC" and vendor and "ericsson" in str(vendor).lower():
        reg_str = str(region).upper()
        target_vendor = "Huawei" if reg_str in ["EASTERN", "SOUTHERN"] else "ZTE"
        exhausted_labels.append(f"Case 12 (Swap E2{target_vendor[0]})")

    eq_nns = pricing["EQ"]["NNS"]
    es_nns = pricing["ES"]["NNS"]
    total_exhausted_capex = eq_nns + es_nns

    final_merged: dict[str, str] = {}
    last_cfg = active_sequence[-1]["config"]
    for k in LAYER_BAND_KEYS:
        c_ant = current_config_map.get(k, "0")
        s_ant = last_cfg.get(k, "0")
        final_merged[k] = s_ant if HW_RANK.get(s_ant, 0) > HW_RANK.get(c_ant, 0) else c_ant

    return current_config_map, final_merged, " + ".join(exhausted_labels), total_exhausted_capex, eq_nns, es_nns, 100.0
