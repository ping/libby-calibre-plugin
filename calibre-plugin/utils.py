import re
from collections import namedtuple
from enum import Enum
from typing import Dict, Tuple

from calibre.gui2 import is_dark_theme

try:
    from calibre_plugins.overdrive_link.link import (
        IDENT_AVAILABLE_LINK as OD_IDENTIFIER,
    )
except ImportError:
    OD_IDENTIFIER = "odid"


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


COLOR_HEX_RE = re.compile("^#[0-9a-f]{3,6}$", re.IGNORECASE)


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


class PluginColors(str, Enum):
    Red = "#FF0F00" if is_dark_theme() else "#E70E00"
    Green = "#00D228" if is_dark_theme() else "#00BA28"
    Blue = "#6EA8FE" if is_dark_theme() else "#0E6EFD"
    Purple = "#C0A4FF" if is_dark_theme() else "#7B47D1"
    Turquoise = "#07CAF0" if is_dark_theme() else "#07B0D3"
    Gray = "#cccccc" if is_dark_theme() else "#333333"

    def __str__(self):
        return str(self.value)


class PluginIcons(str, Enum):
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

    def __str__(self):
        return str(self.value)


IconDefinition = namedtuple("IconDefinition", ["file", "color"])

ICON_MAP = {
    PluginIcons.Return: IconDefinition(
        file="images/arrow-go-back-line.svg", color=PluginColors.Red
    ),
    PluginIcons.Download: IconDefinition(
        file="images/download-line.svg", color=PluginColors.Blue
    ),
    PluginIcons.ExternalLink: IconDefinition(
        file="images/external-link-line.svg", color=PluginColors.Purple
    ),
    PluginIcons.Refresh: IconDefinition(
        file="images/refresh-line.svg",
        color="#FFC107" if is_dark_theme() else "#FD7E14",
    ),
    PluginIcons.Add: IconDefinition(
        file="images/file-add-line.svg", color=PluginColors.Blue
    ),
    PluginIcons.Delete: IconDefinition(
        file="images/delete-bin-line.svg", color=PluginColors.Red
    ),
    PluginIcons.AddMagazine: IconDefinition(
        file="images/heart-add-line.svg",
        color="#EA868E" if is_dark_theme() else "#D63284",
    ),
    PluginIcons.CancelMagazine: IconDefinition(
        file="images/dislike-line.svg", color=PluginColors.Red
    ),
    PluginIcons.Edit: IconDefinition(
        file="images/pencil-line.svg", color=PluginColors.Turquoise
    ),
    PluginIcons.Cancel: IconDefinition(
        file="images/close-line.svg", color=PluginColors.Gray
    ),
    PluginIcons.Okay: IconDefinition(
        file="images/check-line.svg", color=PluginColors.Green
    ),
    PluginIcons.Clover: IconDefinition(
        file="images/clover.svg", color=PluginColors.Green
    ),
}
