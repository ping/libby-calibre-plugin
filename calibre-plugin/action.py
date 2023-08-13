#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from calibre.gui2.actions import InterfaceAction
from qt.core import (
    QDesktopServices,
    QIcon,
    QSize,
    QToolButton,
    QUrl,
    QPixmap,
)

from . import PLUGIN_ICON, PLUGIN_NAME, logger
from .compat import QColor_fromString, _c
from .config import PREFS, PreferenceKeys
from .dialog import (
    BaseDialogMixin,
    CardsDialogMixin,
    HoldsDialogMixin,
    LoansDialogMixin,
    MagazinesDialogMixin,
    SearchDialogMixin,
)
from .utils import CARD_ICON, ICON_MAP, PluginImages, svg_to_qicon, COVER_PLACEHOLDER

# noinspection PyUnreachableCode
if False:
    load_translations = _ = get_resources = lambda x=None: x

load_translations()


class OverdriveLibbyAction(InterfaceAction):
    name = PLUGIN_NAME
    action_spec = (
        "OverDrive Libby",
        None,
        _("Import loans from your OverDrive Libby account"),
        (),
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    action_add_menu = True
    action_menu_clone_qaction = _("Libby")
    dont_add_to = frozenset(["context-menu-device"])
    main_dialog = None

    def genesis(self):
        # This method is called once per plugin, do initial setup here

        # extract icons
        image_resources = get_resources(
            [v.file for v in ICON_MAP.values()]
            + [PLUGIN_ICON, CARD_ICON, COVER_PLACEHOLDER]
        )
        self.resources = {}
        for k, v in ICON_MAP.items():
            self.resources[k] = svg_to_qicon(
                image_resources.pop(v.file), QColor_fromString(v.color)
            )

        # card icon
        self.resources[PluginImages.Card] = image_resources.pop(CARD_ICON)

        # book cover placeholder
        cover_pixmap = QPixmap(150, 200)
        cover_pixmap.loadFromData(image_resources.pop(COVER_PLACEHOLDER))
        cover_pixmap.setDevicePixelRatio(self.gui.devicePixelRatio())
        self.resources[PluginImages.CoverPlaceholder] = cover_pixmap

        # action icon
        plugin_icon = svg_to_qicon(image_resources.pop(PLUGIN_ICON), size=(300, 300))
        self.qaction.setIcon(plugin_icon)
        # set the cloned menu icon
        mini_plugin_icon = QIcon(
            plugin_icon.pixmap(QSize(32, 32), self.gui.devicePixelRatio())
        )
        self.menuless_qaction.setIcon(mini_plugin_icon)
        self.qaction.triggered.connect(self.show_dialog)
        qaction_menu = self.qaction.menu()

        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-config",
            _c("&Customize plugin"),
            "config.png",
            triggered=lambda: self.interface_action_base_plugin.do_user_config(
                self.gui
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-help",
            _c("Help"),
            "help.png",
            triggered=lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/ping/libby-calibre-plugin#setup")
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-changelog",
            _("What's New"),
            self.resources[PluginImages.Information],
            triggered=lambda: QDesktopServices.openUrl(
                QUrl(
                    "https://github.com/ping/libby-calibre-plugin/blob/main/CHANGELOG.md"
                )
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-mr",
            _("MobileRead"),
            self.resources[PluginImages.ExternalLink],
            triggered=lambda: QDesktopServices.openUrl(
                QUrl("https://www.mobileread.com/forums/showthread.php?t=354816")
            ),
        )

    def main_dialog_finished(self):
        self.main_dialog = None

    def show_dialog(self):
        base_plugin_object = self.interface_action_base_plugin
        do_user_config = base_plugin_object.do_user_config
        if not self.main_dialog:
            self.main_dialog = OverdriveLibbyDialog(
                self.gui, self.qaction.icon(), do_user_config, self.resources
            )
            self.main_dialog.finished.connect(self.main_dialog_finished)
        self.main_dialog.show()
        self.main_dialog.raise_()
        self.main_dialog.activateWindow()

    def apply_settings(self):
        if self.main_dialog:
            # close off main UI to make sure everything is consistent
            self.main_dialog.close()


class OverdriveLibbyDialog(
    SearchDialogMixin,
    CardsDialogMixin,
    MagazinesDialogMixin,
    HoldsDialogMixin,
    LoansDialogMixin,
    BaseDialogMixin,
):
    def __init__(self, gui, icon, do_user_config, icons):
        super().__init__(gui, icon, do_user_config, icons)

        # this non-intuitive code is because Windows
        size_hint = self.sizeHint()
        w = size_hint.width()
        h = size_hint.height()
        if (
            PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            and PREFS[PreferenceKeys.MAIN_UI_WIDTH] > 0
        ):
            w = PREFS[PreferenceKeys.MAIN_UI_WIDTH]
            logger.debug("Using saved window width: %d", w)
        if (
            PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            and PREFS[PreferenceKeys.MAIN_UI_HEIGHT] > 0
        ):
            h = PREFS[PreferenceKeys.MAIN_UI_HEIGHT]
            logger.debug("Using saved windows height: %d", h)

        logger.debug("Resizing window to: (%d, %d)", w, h)
        self.resize(QSize(w, h))

        if (
            PREFS[PreferenceKeys.LAST_SELECTED_TAB]
            and self.tabs.count() > PREFS[PreferenceKeys.LAST_SELECTED_TAB]
        ):
            self.tabs.setCurrentIndex(PREFS[PreferenceKeys.LAST_SELECTED_TAB])

        self.sync()
