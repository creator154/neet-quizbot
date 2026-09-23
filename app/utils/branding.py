"""Global branding configuration."""

from telegram import InlineKeyboardButton


# Promotional branding is disabled.
GLOBAL_PROMO_TEXT = ""


def get_promo_keyboard_row():
    """Return promotional keyboard buttons.

    Promotional buttons are currently disabled.
    """
    return []
