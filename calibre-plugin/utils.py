#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import random
from collections import namedtuple
from datetime import datetime
from decimal import localcontext, Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, Optional

from calibre.gui2 import is_dark_theme
from qt.core import QColor, QIcon, QPainter, QPixmap, QSvgRenderer, QXmlStreamReader

from .compat import (
    QPainter_CompositionMode_CompositionMode_SourceIn,
    Qt_GlobalColor_transparent,
)

try:
    from calibre_plugins.overdrive_link.link import (
        IDENT_AVAILABLE_LINK as OD_IDENTIFIER,
    )
except ImportError:
    OD_IDENTIFIER = "odid"

CARD_ICON = "images/card.svg"
COVER_PLACEHOLDER = "images/placeholder.png"


def obfuscate_date(dt: datetime, day=None, month=None, year=None):
    if not dt:
        return dt
    return dt.replace(day=day or 1, month=month or 1, year=year or datetime.now().year)


def obfuscate_name(name: str, offset=5, min_word_len=1, max_word_len=8):
    obfuscated = []
    if not name:
        return name
    for n in name.split(" "):
        min_n = max(min_word_len, len(n) - offset)
        max_n = min(max_word_len, len(n) + offset)
        if min_n == max_n:
            min_n = min_word_len
            max_n = max_word_len
        choices = range(min_n, max_n, 1 if max_n > min_n else -1)
        obfuscated.append(
            "*" * random.choice(choices or range(min_word_len, max_word_len))
        )
    return " ".join(obfuscated)


def obfuscate_int(value: int, offset=5, min_value=0, max_val=30):
    return random.choice(
        range(
            max(min_value, min(value, max_val) - offset), min(max_val, value + offset)
        )
    )


def generate_od_identifier(media: Dict, library: Dict) -> str:
    """
    Generates the OverDrive Link identifier.
    Should probably find a way to call the plugin to do it though.

    :param media:
    :param library:
    :return:
    """
    try:
        from calibre_plugins.overdrive_link.link import ODLink

        return str(
            ODLink(
                provider_id="",
                library_id=f'{library["preferredKey"]}.overdrive.com',
                book_id=media["id"],
            )
        )
    except ImportError:
        return f'{media["id"]}@{library["preferredKey"]}.overdrive.com'


def rating_to_stars(value, star="★"):
    # round() uses banker's rounding, so 4.5 rounds to 4
    # which is non-intuitive
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_UP
        value = int(Decimal(value).to_integral_value())
        r = max(0, min(value or 0, 5))
        return star * r


def svg_to_pixmap(
    data: bytes, color: Optional[QColor] = None, size=(64, 64)
) -> QPixmap:
    renderer = QSvgRenderer(QXmlStreamReader(data))
    pixmap = QPixmap(*size)
    pixmap.fill(Qt_GlobalColor_transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter_CompositionMode_CompositionMode_SourceIn)
    if color:
        painter.fillRect(pixmap.rect(), color)
    painter.end()
    return pixmap


def svg_to_qicon(data: bytes, color: Optional[QColor] = None, size=(64, 64)):
    """
    Converts an SVG to QIcon

    :param data:
    :param color:
    :param size:
    :return:
    """
    return QIcon(svg_to_pixmap(data, color, size))


class PluginColors(str, Enum):
    Red = "#FF0F00" if is_dark_theme() else "#E70E00"
    Green = "#00D228" if is_dark_theme() else "#00BA28"
    Blue = "#6EA8FE" if is_dark_theme() else "#0E6EFD"
    Purple = "#C0A4FF" if is_dark_theme() else "#7B47D1"
    Turquoise = "#07CAF0" if is_dark_theme() else "#07B0D3"
    Gray = "#CCCCCC" if is_dark_theme() else "#333333"
    Gray2 = "#9DB2BF" if is_dark_theme() else "#526D82"
    OrangeYellow = "#FFC107" if is_dark_theme() else "#FD7E14"
    ThemeGreen = "#63CBC1" if is_dark_theme() else "#25B0A7"

    def __str__(self):
        return str(self.value)


class PluginImages(str, Enum):
    Return = "return"
    Download = "download"
    ExternalLink = "ext-link"
    Refresh = "refresh"
    Add = "add-file"
    Delete = "delete"
    AddMagazine = "magazines-add"
    CancelMagazine = "cancel-sub"
    Edit = "pencil-line"
    Cancel = "cancel"
    Okay = "okay"
    Clover = "clover"
    Card = "card"
    Search = "search"
    Amazon = "amazon"
    Unlock = "unlock"
    CoverPlaceholder = "cover-placeholder"
    Information = "information"
    Renew = "renew"

    def __str__(self):
        return str(self.value)


IconDefinition = namedtuple("IconDefinition", ["file", "color"])

ICON_MAP = {
    PluginImages.Return: IconDefinition(
        file="images/arrow-go-back-line.svg", color=PluginColors.Red
    ),
    PluginImages.Download: IconDefinition(
        file="images/download-line.svg", color=PluginColors.Blue
    ),
    PluginImages.ExternalLink: IconDefinition(
        file="images/external-link-line.svg", color=PluginColors.Purple
    ),
    PluginImages.Refresh: IconDefinition(
        file="images/refresh-line.svg", color=PluginColors.OrangeYellow
    ),
    PluginImages.Add: IconDefinition(
        file="images/file-add-line.svg", color=PluginColors.Blue
    ),
    PluginImages.Delete: IconDefinition(
        file="images/delete-bin-line.svg", color=PluginColors.Red
    ),
    PluginImages.AddMagazine: IconDefinition(
        file="images/heart-add-line.svg",
        color="#EA868E" if is_dark_theme() else "#D63284",
    ),
    PluginImages.CancelMagazine: IconDefinition(
        file="images/dislike-line.svg", color=PluginColors.Red
    ),
    PluginImages.Edit: IconDefinition(
        file="images/pencil-line.svg", color=PluginColors.Turquoise
    ),
    PluginImages.Cancel: IconDefinition(
        file="images/close-line.svg", color=PluginColors.Gray
    ),
    PluginImages.Okay: IconDefinition(
        file="images/check-line.svg", color=PluginColors.Green
    ),
    PluginImages.Clover: IconDefinition(
        file="images/clover.svg", color=PluginColors.Green
    ),
    PluginImages.Search: IconDefinition(
        file="images/search-line.svg", color=PluginColors.Gray2
    ),
    PluginImages.Amazon: IconDefinition(
        file="images/brand-amazon.svg",
        color="#FF9900" if is_dark_theme() else "#FD9700",
    ),
    PluginImages.Unlock: IconDefinition(
        file="images/lock-unlock-line.svg", color=PluginColors.Green
    ),
    PluginImages.Information: IconDefinition(
        file="images/information-line.svg", color=PluginColors.Blue
    ),
    PluginImages.Renew: IconDefinition(
        file="images/arrow-go-forward-line.svg", color=PluginColors.Green
    ),
}
