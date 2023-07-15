#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
from typing import Optional

from calibre.gui2 import is_dark_theme
from calibre.gui2.actions import InterfaceAction
from qt.core import (
    QToolButton,
    QSize,
    QIcon,
    QColor,
    Qt,
    QPainter,
    QXmlStreamReader,
    QSvgRenderer,
    QPixmap,
    QUrl,
    QDesktopServices,
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
        _("Import loans from your OverDrive Libby account"),
        None,
    )
    popup_type = QToolButton.MenuButtonPopup
    action_type = "current"
    action_add_menu = True
    action_menu_clone_qaction = _("Libby")
    dont_add_to = frozenset(["context-menu-device"])

    @staticmethod
    def svg_to_qicon(data: bytes, color: Optional[QColor] = None, size=(64, 64)):
        renderer = QSvgRenderer(QXmlStreamReader(data))
        pixmap = QPixmap(*size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.setCompositionMode(painter.CompositionMode.CompositionMode_SourceIn)
        if color:
            painter.fillRect(pixmap.rect(), color)
        painter.end()
        return QIcon(pixmap)

    def genesis(self):
        # This method is called once per plugin, do initial setup here

        # extract icons
        image_resources = get_resources(
            [v.file for v in ICON_MAP.values()] + [PLUGIN_ICON]
        )
        self.icons = {}
        for k, v in ICON_MAP.items():
            self.icons[k] = self.svg_to_qicon(
                image_resources.pop(v.file),
                QColor.fromString(
                    v.dark_theme_color if is_dark_theme() else v.light_theme_color
                ),
            )

        # action icon
        plugin_icon = self.svg_to_qicon(
            image_resources.pop(PLUGIN_ICON), size=(300, 300)
        )
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
            _("Customize plugin"),
            "config.png",
            triggered=lambda: self.interface_action_base_plugin.do_user_config(
                self.gui
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-help",
            _("Help"),
            "help.png",
            triggered=lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/ping/libby-calibre-plugin#setup")
            ),
        )
        self.create_menu_action(
            qaction_menu,
            "overdrive-libby-mr",
            _("MobileRead"),
            "external-link.png",
            triggered=lambda: QDesktopServices.openUrl(
                QUrl("https://www.mobileread.com/forums/showthread.php?t=354816")
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
