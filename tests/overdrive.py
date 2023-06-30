#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from overdrive.client import OverDriveClient

from .base import BaseTests


class OverDriveClientTests(BaseTests):
    def setUp(self):
        super().setUp()

        self.client = OverDriveClient(
            max_retries=0,
            timeout=15,
            logger=self.logger,
        )

    def test_media(self):
        item = self.client.media("284716")
        for k in (
            "id",
            "title",
            "sortTitle",
            "description",
            "fullDescription",
            "shortDescription",
            "publishDate",
            "type",
            "formats",
            "covers",
            "languages",
            "creators",
            "subjects",
            "starRating",
            "starRatingCount",
            "unitsSold",
            "popularity",
        ):
            with self.subTest("media response", k=k):
                self.assertIn(k, item, msg=f'"{k}" not found')
