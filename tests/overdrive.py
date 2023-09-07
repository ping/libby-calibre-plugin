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
from functools import cmp_to_key

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

    def test_media_bulk(self):
        title_ids = ["9945849", "9954663", "9963571"]
        titles = self.client.media_bulk(title_ids=title_ids)
        self.assertEqual(len(titles), len(title_ids))

    def test_library_media(self):
        title = self.client.library_media("lapl", "9945849")
        for k in ("title", "isOwned", "isAvailable"):
            with self.subTest("library media response", k=k):
                self.assertTrue(title.get(k))

    def test_sort_availabilities(self):
        for a, b in [
            (
                {"id": "a", "isAvailable": True, "estimatedWaitDays": 1},
                {"id": "b", "isAvailable": False, "estimatedWaitDays": 7},
            ),
            (
                {
                    "id": "a",
                    "isAvailable": True,
                    "estimatedWaitDays": 1,
                    "ownedCopies": 10,
                },
                {
                    "id": "b",
                    "isAvailable": True,
                    "estimatedWaitDays": 1,
                    "ownedCopies": 1,
                },
            ),
            (
                {
                    "id": "a",
                    "isAvailable": False,
                    "estimatedWaitDays": 1,
                    "holdsRatio": 2,
                    "ownedCopies": 9,
                },
                {
                    "id": "b",
                    "isAvailable": False,
                    "estimatedWaitDays": 1,
                    "holdsRatio": 2,
                    "ownedCopies": 2,
                },
            ),
            (
                {"id": "a", "isAvailable": False, "estimatedWaitDays": 3},
                {"id": "b", "isAvailable": False, "estimatedWaitDays": 7},
            ),
            (
                {
                    "id": "a",
                    "isAvailable": False,
                    "luckyDayAvailableCopies": 1,
                    "estimatedWaitDays": 7,
                },
                {"id": "b", "isAvailable": False, "estimatedWaitDays": 3},
            ),
        ]:
            results = sorted(
                [a, b],
                key=cmp_to_key(OverDriveClient.sort_availabilities),
                reverse=True,
            )
            self.assertEqual(results[0]["id"], "a")

    def test_media_search(self):
        medias = self.client.media_search(
            library_keys=["lapl", "sno-isle"],
            query="harry potter chamber secrets",
            format=["ebook-epub-adobe"],
            maxItems=1,
        )
        for media in medias:
            sites = []
            for k, v in media.get("siteAvailabilities", {}).items():
                v["advantageKey"] = k
                sites.append(v)
            sites = sorted(
                sites, key=cmp_to_key(OverDriveClient.sort_availabilities), reverse=True
            )
            self.assertTrue(media["title"])
            self.assertTrue(sites[0]["advantageKey"])

    def test_extract_isbn(self):
        formats = [
            {
                "identifiers": [
                    {"value": "9980000000000", "type": "ISBN"},
                    {"value": "tantor_audio#9980000000000", "type": "8"},
                    {"value": "9980000000001", "type": "LibraryISBN"},
                ],
                "isbn": "9780000000001",
                "id": "ebook-kindle",
            },
            {
                "identifiers": [
                    {"value": "9780000000000", "type": "ISBN"},
                    {"value": "publisher#9780000000000", "type": "8"},
                    {"value": "9780000000001", "type": "LibraryISBN"},
                ],
                "isbn": "9780000000001",
                "id": "ebook-epub-adobe",
            },
        ]
        self.assertEqual(
            OverDriveClient.extract_isbn(formats, ["ebook-epub-adobe"]), "9780000000001"
        )
        formats = [
            {
                "identifiers": [
                    {"value": "9780000000000", "type": "ISBN"},
                    {"value": "9780000000001", "type": "LibraryISBN"},
                ],
                "id": "ebook-epub-adobe",
            }
        ]
        self.assertEqual(
            OverDriveClient.extract_isbn(formats, ["ebook-epub-adobe"]), "9780000000001"
        )
        formats = [
            {
                "identifiers": [
                    {"value": "9780000000000", "type": "ISBN"},
                    {"value": "9780000000001", "type": "X"},
                ],
                "id": "ebook-epub-adobe",
            }
        ]
        self.assertEqual(
            OverDriveClient.extract_isbn(formats, ["ebook-epub-adobe"]), "9780000000000"
        )
        self.assertEqual(OverDriveClient.extract_isbn(formats, []), "9780000000000")

    def test_extract_asin(self):
        formats = [
            {
                "identifiers": [
                    {"value": "9780000000000", "type": "ISBN"},
                    {"value": "9780000000001", "type": "LibraryISBN"},
                    {"value": "B123456789", "type": "ASIN"},
                ],
            }
        ]
        self.assertEqual(OverDriveClient.extract_asin(formats), "B123456789")

    def test_library_media_availability(self):
        item = self.client.library_media_availability("lapl", "784353")
        for k in (
            "id",
            "isAvailable",
            "availabilityType",
            "holdsCount",
            "formats",
        ):
            with self.subTest("item", k=k):
                self.assertIn(k, item, msg=f'"{k}" not found')
        if item["availabilityType"] == "normal":
            for k in (
                "ownedCopies",
                "availableCopies",
                "luckyDayOwnedCopies",
                "luckyDayAvailableCopies",
                "holdsRatio",
                "estimatedWaitDays",
            ):
                with self.subTest("item", k=k):
                    self.assertIn(k, item, msg=f'"{k}" not found')

    def test_library_media_availability_bulk(self):
        res = self.client.library_media_availability_bulk("lapl", ["784353", "36635"])
        self.assertTrue(res.get("items"))
        for item in res["items"] or []:
            if not item:
                continue
            for k in (
                "id",
                "isAvailable",
                "availabilityType",
                "holdsCount",
                "formats",
            ):
                with self.subTest("item", k=k):
                    self.assertIn(k, item, msg=f'"{k}" not found')
            if item["availabilityType"] == "normal":
                for k in (
                    "ownedCopies",
                    "availableCopies",
                    "luckyDayOwnedCopies",
                    "luckyDayAvailableCopies",
                    "holdsRatio",
                    "estimatedWaitDays",
                ):
                    with self.subTest("item", k=k):
                        self.assertIn(k, item, msg=f'"{k}" not found')
