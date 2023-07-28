#
# Keep compat functions here
#
import re
from typing import Tuple

from qt.core import Qt, QPainter, QToolButton, QSlider, QHeaderView, QColor

# noinspection PyUnreachableCode
if False:
    _ = None

try:
    from calibre.utils.localization import _ as _c
except ImportError:
    # fallback to global _ for calibre<6.12
    _c = _

COLOR_HEX_RE = re.compile("^#[0-9a-f]{3,6}$", re.IGNORECASE)

try:
    QHeaderView_ResizeMode_Stretch = QHeaderView.ResizeMode.Stretch
    QHeaderView_ResizeMode_ResizeToContents = QHeaderView.ResizeMode.ResizeToContents
    Qt_GlobalColor_transparent = Qt.GlobalColor.transparent
    QPainter_CompositionMode_CompositionMode_SourceIn = (
        QPainter.CompositionMode.CompositionMode_SourceIn
    )
    QToolButton_ToolButtonPopupMode_DelayedPopup = (
        QToolButton.ToolButtonPopupMode.DelayedPopup
    )
    QSlider_TickPosition_TicksBelow = QSlider.TickPosition.TicksBelow
except AttributeError:
    QHeaderView_ResizeMode_Stretch = QHeaderView.Stretch
    QHeaderView_ResizeMode_ResizeToContents = QHeaderView.ResizeToContents
    Qt_GlobalColor_transparent = Qt.transparent
    QPainter_CompositionMode_CompositionMode_SourceIn = (
        QPainter.CompositionMode_SourceIn
    )
    QToolButton_ToolButtonPopupMode_DelayedPopup = QToolButton.DelayedPopup
    QSlider_TickPosition_TicksBelow = QSlider.TicksBelow


def compat_enum(obj, name):
    """
    A compat utility to get PyQt6 Qt.scoped.enums Vs. PyQt5 Qt.enums
    so that we can support calibre 5?
    Example: compat_enum(Qt, "GlobalColor.transparent")

    :param obj:
    :param name:
    :return:
    """
    parent, child = name.split(".")
    result = getattr(obj, child, False)
    if result:  # Found using short name
        return result

    # Get parent, then child
    return getattr(getattr(obj, parent), child)


def QColor_fromString(color: str):
    """
    Compat helper for QColor.fromString() introduced in Qt6.4 (calibre>=6.12)

    :param color:
    :return:
    """
    try:
        return QColor.fromString(color)
    except AttributeError:
        return QColor(*hex_to_rgb(color))


def hex_to_rgb(hexcolor: str) -> Tuple:
    """
    Converts a hex color string into a rgb tuple, e.g. "#FFFFFF" to (255, 255, 255)
    so that we don't have to use QColor.fromString (introduced in Qt6.4).

    :param hexcolor:
    :return:
    """
    if not COLOR_HEX_RE.match(hexcolor):
        raise ValueError(f"Invalid hexcode: {hexcolor}")
    hexcolor = hexcolor.upper().lstrip("#")
    if len(hexcolor) == 3:
        return tuple(int(hexcolor[i : i + 1] * 2, 16) for i in (0, 1, 2))
    return tuple(int(hexcolor[i : i + 2], 16) for i in (0, 2, 4))
