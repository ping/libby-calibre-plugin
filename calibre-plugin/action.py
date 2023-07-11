#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from pathlib import Path

from calibre.gui2 import is_dark_theme
from calibre.gui2.actions import InterfaceAction
from qt.core import (
    QToolButton,
    QSize,
)

from . import logger, PLUGIN_NAME, PLUGIN_ICON, ICON_MAP
from .config import PREFS, PreferenceKeys
from .dialog import (
    BaseDialogMixin,
    LoansDialogMixin,
    HoldsDialogMixin,
    MagazinesDialogMixin,
)

load_translations()


class OverdriveLibbyAction(InterfaceAction):
    name = PLUGIN_NAME
    action_spec = (
        "OverDrive Libby",
        None,
        _("Run the OverDrive Libby client UI"),
        None,
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    action_add_menu = True
    dont_add_to = frozenset(["context-menu-device"])

    def genesis(self):
        # This method is called once per plugin, do initial setup here

        # extract icons
        theme_folder = Path("images").joinpath(
            "dark-theme" if is_dark_theme() else "light-theme"
        )
        icons_resources = get_icons(
            [str(theme_folder.joinpath(v)) for v in ICON_MAP.values()] + [PLUGIN_ICON]
        )
        self.icons = {}
        for k, v in ICON_MAP.items():
            self.icons[k] = icons_resources.pop(str(theme_folder.joinpath(v)))

        # action icon
        self.qaction.setIcon(icons_resources.pop(PLUGIN_ICON))
        self.qaction.triggered.connect(self.show_dialog)
        self.libby_menu = self.qaction.menu()
        self.create_menu_action(
            self.libby_menu,
            "overdrive-libby-config",
            _("Customize plugin"),
            "config.png",
            triggered=lambda: self.interface_action_base_plugin.do_user_config(
                self.gui
            ),
        )

    def show_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        d = OverdriveLibbyDialog(
            self.gui, self.qaction.icon(), do_user_config, self.icons
        )
        d.setModal(True)
        d.show()

    def apply_settings(self):
        pass


class OverdriveLibbyDialog(
    MagazinesDialogMixin, HoldsDialogMixin, LoansDialogMixin, BaseDialogMixin
):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)

        if (
            PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            and PREFS[PreferenceKeys.MAIN_UI_WIDTH] > 0
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT] > 0
        ):
            logger.debug(
                "Resizing window using saved preferences: (%d, %d)",
                PREFS[PreferenceKeys.MAIN_UI_WIDTH],
                PREFS[PreferenceKeys.MAIN_UI_HEIGHT],
            )
            self.resize(
                QSize(
                    PREFS[PreferenceKeys.MAIN_UI_WIDTH],
                    PREFS[PreferenceKeys.MAIN_UI_HEIGHT],
                )
            )
        else:
            self.resize(self.sizeHint())

        # for pseudo-debouncing resizeEvent
        self._curr_width = self.size().width()
        self._curr_height = self.size().height()

        self.sync()
