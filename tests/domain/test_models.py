import pytest
from pydantic import ValidationError

from fixtures import ENTITY_FIXTURES
from plumb.domain.models import Order


@pytest.mark.parametrize("model_cls, fixture", ENTITY_FIXTURES, ids=[m.__name__ for m, _ in ENTITY_FIXTURES])
def test_entity_round_trips(model_cls, fixture):
    instance = model_cls.model_validate(fixture)
    assert instance.model_dump(mode="json") == fixture


def test_strict_mode_rejects_float_in_money_field():
    fixture = dict(ENTITY_FIXTURES[0][1])
    fixture["gross_paise"] = 118000.0  # a float, even a whole-numbered one, must not coerce
    with pytest.raises(ValidationError):
        Order.model_validate(fixture)


def test_record_key_rejects_malformed_id():
    fixture = dict(ENTITY_FIXTURES[0][1])
    fixture["order_id"] = "order-42"  # wrong shape: not prefix_NNNNN
    with pytest.raises(ValidationError):
        Order.model_validate(fixture)
