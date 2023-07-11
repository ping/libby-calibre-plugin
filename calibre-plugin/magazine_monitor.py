from typing import Dict

from .overdrive import OverDriveClient

load_translations()


class OverdriveGetLibraryMedia:
    def __call__(
        self,
        gui,
        overdrive_client: OverDriveClient,
        card: Dict,
        title_id: str,
        log=None,
        abort=None,
        notifications=None,
    ):
        logger = log
        notifications.put(
            (
                0.5,
                _("Getting magazine (id: {id}) information from {library}").format(
                    id=title_id, library=card["advantageKey"]
                ),
            )
        )
        media = overdrive_client.library_media(card["advantageKey"], title_id)
        logger.info("Found magazine %s successfully" % media["title"])
        return media, card
