from src.services.strategy_store import slugify


def test_slugify_basic():
    assert slugify("Alpha Momentum") == "alpha-momentum"


def test_slugify_special_chars():
    assert slugify("My Strategy #1!") == "my-strategy-1"


def test_slugify_extra_spaces():
    assert slugify("  multi  space  ") == "multi-space"


def test_slugify_already_dashed():
    assert slugify("already-dashed") == "already-dashed"
