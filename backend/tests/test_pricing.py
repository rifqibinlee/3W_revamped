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
    service.seed_defaults_if_empty(db_session)
    pricing_after_first_seed = service.get_pricing(db_session)
    assert pricing_after_first_seed == DEFAULT_PRICING

    service.upsert_price(db_session, "EQ", "BW Upg", 42.0, updated_by_id=None)
    service.seed_defaults_if_empty(db_session)  # should not overwrite the edit
    pricing = service.get_pricing(db_session)
    assert pricing["EQ"]["BW Upg"] == 42.0
