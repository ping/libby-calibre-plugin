#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import io
import logging
import sys
from collections import namedtuple
from enum import Enum

from calibre.constants import is_debugging
from calibre.customize import InterfaceActionBase

load_translations()

__version__ = (0, 1, 4)
PLUGIN_NAME = "overdrive_libby"
PLUGIN_ICON = "images/plugin.svg"

DEMO_MODE = False  # make it easier for screenshots :P


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

    def __str__(self):
        return str(self.value)


IconDefinition = namedtuple(
    "IconDefinition", ["file", "dark_theme_color", "light_theme_color"]
)

ICON_MAP = {
    PluginIcons.Return: IconDefinition(
        file="images/arrow-go-back-line.svg",
        dark_theme_color="#DC3545",
        light_theme_color="#DC3545",
    ),
    PluginIcons.Download: IconDefinition(
        file="images/download-line.svg",
        dark_theme_color="#6EA8FE",
        light_theme_color="#0E6EFD",
    ),
    PluginIcons.ExternalLink: IconDefinition(
        file="images/external-link-line.svg",
        dark_theme_color="#07CAF0",
        light_theme_color="#6F42C1",
    ),
    PluginIcons.Refresh: IconDefinition(
        file="images/refresh-line.svg",
        dark_theme_color="#FFC107",
        light_theme_color="#FD7E14",
    ),
    PluginIcons.Add: IconDefinition(
        file="images/file-add-line.svg",
        dark_theme_color="#6EA8FE",
        light_theme_color="#0E6EFD",
    ),
    PluginIcons.Delete: IconDefinition(
        file="images/delete-bin-line.svg",
        dark_theme_color="#DC3545",
        light_theme_color="#DC3545",
    ),
    PluginIcons.AddMagazine: IconDefinition(
        file="images/heart-add-line.svg",
        dark_theme_color="#EA868E",
        light_theme_color="#D63284",
    ),
    PluginIcons.CancelMagazine: IconDefinition(
        file="images/dislike-line.svg",
        dark_theme_color="#DC3545",
        light_theme_color="#DC3545",
    ),
    PluginIcons.Edit: IconDefinition(
        file="images/pencil-line.svg",
        dark_theme_color="#FFFFFF",
        light_theme_color="#000000",
    ),
    PluginIcons.Cancel: IconDefinition(
        file="images/close-line.svg",
        dark_theme_color="#FFFFFF",
        light_theme_color="#000000",
    ),
    PluginIcons.Okay: IconDefinition(
        file="images/check-line.svg",
        dark_theme_color="#00D228",
        light_theme_color="#00BA28",
    ),
}


logger = logging.getLogger(__name__)
ch = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
ch.setLevel(logging.DEBUG)
ch.setFormatter(
    logging.Formatter(
        f'[{PLUGIN_NAME}/{".".join([str(d) for d in __version__])}] %(message)s'
    )
)
logger.addHandler(ch)
logger.setLevel(logging.INFO if not is_debugging() else logging.DEBUG)


class ActionLibby(InterfaceActionBase):
    """
    This class is a simple wrapper that provides information about the actual
    plugin class. The actual interface plugin class is called InterfacePlugin
    and is defined in the ui.py file, as specified in the actual_plugin field
    below.

    The reason for having two classes is that it allows the command line
    calibre utilities to run without needing to load the GUI libraries.
    """

    name = "OverDrive Libby"
    description = _("Import loans from your OverDrive Libby account")
    supported_platforms = ["windows", "osx", "linux"]
    author = "ping"
    version = __version__
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = f"calibre_plugins.{PLUGIN_NAME}.action:OverdriveLibbyAction"

    def is_customizable(self):
        """
        This method must return True to enable customization via
        Preferences->Plugins
        """
        return True

    def config_widget(self):
        """
        Implement this method and :meth:`save_settings` in your plugin to
        use a custom configuration dialog.

        This method, if implemented, must return a QWidget. The widget can have
        an optional method validate() that takes no arguments and is called
        immediately after the user clicks OK. Changes are applied if and only
        if the method returns True.

        If for some reason you cannot perform the configuration at this time,
        return a tuple of two strings (message, details), these will be
        displayed as a warning dialog to the user and the process will be
        aborted.

        The base class implementation of this method raises NotImplementedError
        so by default no user configuration is possible.
        """
        # It is important to put this import statement here rather than at the
        # top of the module as importing the config class will also cause the
        # GUI libraries to be loaded, which we do not want when using calibre
        # from the command line
        if self.actual_plugin_:
            from .config import ConfigWidget

            return ConfigWidget(self.actual_plugin_)

    def save_settings(self, config_widget):
        """
        Save the settings specified by the user with config_widget.

        :param config_widget: The widget returned by :meth:`config_widget`.
        """
        config_widget.save_settings()
