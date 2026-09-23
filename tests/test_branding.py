"""Unit tests for global branding configuration."""

from app.utils.branding import GLOBAL_PROMO_TEXT, get_promo_keyboard_row


def test_branding_content():
    """Verify promotional branding is disabled."""
    assert GLOBAL_PROMO_TEXT == ""


def test_branding_keyboards():
    """Verify promotional buttons are disabled."""
    row = get_promo_keyboard_row()
    assert row == []
