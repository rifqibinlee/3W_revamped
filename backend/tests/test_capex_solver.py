from app.ingestion.capex_solver import DEFAULT_PRICING, calculate_upgrade_path


def test_additional_rb_non_positive_returns_no_upgrade() -> None:
    sector_bands = [{"band": "L18", "layer": "F1", "avail_prb": 100, "current_xtxr": "2T2R"}]
    curr_map, sugg_map, label, capex, eq, es, prb = calculate_upgrade_path(
        sector_bands, "Rural", "Macro", "NIC", "Celcom", "xC", DEFAULT_PRICING,
        sum_rb_used=80, sum_existing_avail=100, additional_rb=-5, region="Central",
    )
    assert label is None
    assert capex == 0.0
    assert curr_map == sugg_map
    assert prb == 80.0  # 80/100*100


def test_first_step_pass_adds_network_layer() -> None:
    # No existing hardware at all -> step 1 of SEQ_PATH_A adds F1_L18=2T2R.
    # sum_rb_used=50 against rb_offered=100 -> projected 50% <= 73% threshold.
    curr_map, sugg_map, label, capex, eq, es, prb = calculate_upgrade_path(
        sector_bands=[], area_target="Rural", ibc_macro="Macro", bau_nic="NIC",
        vendor="Celcom", ds_type="xC", pricing=DEFAULT_PRICING,
        sum_rb_used=50, sum_existing_avail=0, additional_rb=100, region="Central",
    )
    assert curr_map == {}
    assert sugg_map["F1_L18"] == "2T2R"
    assert label == "Case 3 (Add network layer only)"
    assert eq == DEFAULT_PRICING["EQ"]["Add Layer"]  # layer_mult=1.0 for first added layer
    assert es == DEFAULT_PRICING["ES"]["Add Layer"]
    assert capex == eq + es
    assert prb == 50.0


def test_exhausted_sequence_returns_nns() -> None:
    # sum_rb_used astronomically high relative to anything 14 steps can
    # offer -> every step's projected PRB stays above 73%, falls through
    # to the NNS exhausted case.
    curr_map, sugg_map, label, capex, eq, es, prb = calculate_upgrade_path(
        sector_bands=[], area_target="Urban", ibc_macro="Macro", bau_nic="NIC",
        vendor="Celcom", ds_type="xC", pricing=DEFAULT_PRICING,
        sum_rb_used=1_000_000_000, sum_existing_avail=0, additional_rb=100, region="Central",
    )
    assert label == "Case 11 (NNS)"
    assert eq == DEFAULT_PRICING["EQ"]["NNS"]
    assert es == DEFAULT_PRICING["ES"]["NNS"]
    assert capex == eq + es
    assert prb == 100.0


def test_inbuilding_and_bau_nic_add_extra_cases() -> None:
    _, _, label, *_ = calculate_upgrade_path(
        sector_bands=[], area_target="Rural", ibc_macro="Inbuilding", bau_nic="BAU",
        vendor="Celcom", ds_type="xC", pricing=DEFAULT_PRICING,
        sum_rb_used=50, sum_existing_avail=0, additional_rb=100, region="Central",
    )
    assert "Case 8 (Add IBC)" in label
    assert "Case 10 (Accelerate NIC)" in label
