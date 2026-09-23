"""Unit tests for global branding configuration."""

from app.utils.branding import GLOBAL_PROMO_TEXT


def test_branding_content():
    """Verify promo text is disabled so messages stay clean."""
    assert GLOBAL_PROMO_TEXT == ""


def test_branding_keyboards():
    """Verify no promotional keyboard buttons are present."""
    from app.utils.branding import get_promo_keyboard_row

    row = get_promo_keyboard_row()
    assert len(row) == 0
