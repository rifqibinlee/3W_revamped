from app.ingestion.capex_solver import DEFAULT_PRICING
from app.pricing import service


def test_empty_table_falls_back_to_defaults(db_session) -> None:
    pricing = service.get_pricing(db_session)
    assert pricing == DEFAULT_PRICING


def test_upsert_creates_then_updates(db_session) -> None:
    service.upsert_price(db_session, "EQ", "BW Upg", 9999.0, updated_by_id=None)
    pricing = service.get_pricing(db_session)
    assert pricing["EQ"]["BW Upg"] == 9999.0

    service.upsert_price(db_session, "EQ", "BW Upg", 1234.0, updated_by_id=None)
    pricing = service.get_pricing(db_session)
    assert pricing["EQ"]["BW Upg"] == 1234.0


def test_invalid_category_rejected(db_session) -> None:
    try:
        service.upsert_price(db_session, "BOGUS", "x", 1.0, updated_by_id=None)
        assert False, "expected InvalidCategoryError"
    except service.InvalidCategoryError:
        pass


def test_seed_defaults_is_idempotent(db_session) -> None:
    # Prefers the real price+range seed file (scripts_example/capex_pricing.json)
    # when present, falling back to capex_solver's flat DEFAULT_PRICING
    # otherwise — either way the *categories/items* match, only the exact
    # numbers might differ from DEFAULT_PRICING if a real seed is in play.
    service.seed_defaults_if_empty(db_session)
    pricing_after_first_seed = service.get_pricing(db_session)
    real_seed = service._load_real_pricing_seed()
    if real_seed:
        expected = {cat: {name: item["price"] for name, item in items.items()} for cat, items in real_seed.items()}
    else:
        expected = DEFAULT_PRICING
    assert pricing_after_first_seed == expected

    service.upsert_price(db_session, "EQ", "BW Upg", 42.0, updated_by_id=None)
    service.seed_defaults_if_empty(db_session)  # should not overwrite the edit
    pricing = service.get_pricing(db_session)
    assert pricing["EQ"]["BW Upg"] == 42.0


def test_detailed_pricing_defaults_to_zero_width_range_when_empty(db_session) -> None:
    detailed = service.get_pricing_detailed(db_session)
    item = detailed["EQ"]["BW Upg"]
    assert item["price"] == item["price_min"] == item["price_max"] == DEFAULT_PRICING["EQ"]["BW Upg"]


def test_detailed_pricing_defaults_range_to_exact_price_when_unset(db_session) -> None:
    service.upsert_price(db_session, "EQ", "BW Upg", 9999.0, updated_by_id=None)
    detailed = service.get_pricing_detailed(db_session)
    item = detailed["EQ"]["BW Upg"]
    assert item == {"price": 9999.0, "price_min": 9999.0, "price_max": 9999.0}


def test_upsert_with_explicit_range(db_session) -> None:
    service.upsert_price(db_session, "EQ", "BW Upg", 9999.0, updated_by_id=None, price_min=9000.0, price_max=11000.0)
    detailed = service.get_pricing_detailed(db_session)
    assert detailed["EQ"]["BW Upg"] == {"price": 9999.0, "price_min": 9000.0, "price_max": 11000.0}


def test_redact_for_role_hides_exact_price_for_non_admin(db_session) -> None:
    service.upsert_price(db_session, "EQ", "BW Upg", 9999.0, updated_by_id=None, price_min=9000.0, price_max=11000.0)
    detailed = service.get_pricing_detailed(db_session)

    admin_view = service.redact_for_role(detailed, is_admin=True)
    assert admin_view["EQ"]["BW Upg"]["price"] == 9999.0

    staff_view = service.redact_for_role(detailed, is_admin=False)
    assert "price" not in staff_view["EQ"]["BW Upg"]
    assert staff_view["EQ"]["BW Upg"] == {"price_min": 9000.0, "price_max": 11000.0}
