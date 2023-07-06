#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import json
import math

from overdrive import OverDriveClient

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

    def test_libraries(self):
        all_library_keys = [
            "lapl",
            "sno-isle",
            "nlb",
            "livebrary",
            "kcls",
            "clevnet",
            "melsa",
            "auckland",
            "toronto",
            "metrolibrary",
            "ppld",
            "nypl",
            "brooklyn",
            "ocln",
            "indypl",
            "ohdbks",
            "idl",
            "lasvegas",
            "multcolib",
            "cincinnatilibrary",
            "saclibrary",
            "hcpl",
            "hcplc",
            "spl",
            "nashville",
            "austinlibrary",
            "clc",
            "sfpl",
            "sails",
            "arapahoe",
            "piercecounty",
            "mcpl",
            "riezone",
            "ocls",
            "ccpl",
            "phoenix",
            "calgary",
            "bpl",
            "lacountylibrary",
            "wccls",
            "dayton",
            "ebr",
            "midcolumbialibraries",
            "aclib",
            "sdcl",
            "neworleans",
            "lcls",
            "scld",
            "lfpl",
            "reads",
            "acla",
            "minuteman",
            "epl",
            "timberland",
            "toledo",
            "pueblolibrary",
            "queenslibrary",
            "dallaslibrary",
            "slco",
            "wplc",
            "kyunbound",
            "markham",
            "slcl",
            "beehive",
            "evpl",
            "saskatchewan",
            "santaclara",
            "surreyca",
            "sanantonio",
            "ocpl",
            "cwmars",
            "voebb",
            "hpl",
            "pioneerok",
            "kdl",
            "houstonlibrary",
            "jpl",
            "inglewoodpl",
            "christchurch",
            "fresno",
            "sonoma",
            "ncdigital",
            "cals",
            "ccc",
            "bridges",
            "lakecounty",
            "dlil",
            "hawaii",
            "goldcoast",
            "westchester",
            "adlc",
            "sanjose",
            "wvdeli",
            "odmc",
            "nmls",
            "lsw",
            "aclibrary",
            "virtuallibrary",
            "tlc",
            "fwpl",
        ]
        max_per_page = 24
        total_pages = math.ceil(len(all_library_keys) / max_per_page)
        libraries = []
        for page in range(1, 1 + total_pages):
            library_keys = all_library_keys[
                (page - 1) * max_per_page : page * max_per_page
            ]
            results = self.client.libraries(
                libraryKeys=",".join(library_keys), per_page=max_per_page
            )
            items = results.get("items", [])
            for item in items:
                self.assertIn(item["preferredKey"], library_keys)
                self.assertNotIn(item["preferredKey"], libraries)
                libraries.append(item["preferredKey"])

        self.assertEqual(len(all_library_keys), len(libraries))
