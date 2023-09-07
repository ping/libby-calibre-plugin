#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#
import os
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from libby import LibbyClient, LibbyFormats
from libby.errors import (
    ClientBadRequestError,
    ClientConnectionError,
    ClientError,
    ClientForbiddenError,
    ClientNotFoundError,
    ClientThrottledError,
    ClientUnauthorisedError,
    InternalServerError,
)
from .base import BaseTests, MockHTTPError


class LibbyClientTests(BaseTests):
    def setUp(self):
        super().setUp()

        token = ""
        try:
            token = os.environ["LIBBY_TEST_TOKEN"]
        except KeyError:
            pass
        self.client = LibbyClient(
            identity_token=token,
            max_retries=0,
            timeout=15,
            logger=self.logger,
        )

    def test_get_chip(self):
        res = self.client.get_chip()
        for k in ("chip", "identity", "syncable", "primary"):
            with self.subTest("chip response", k=k):
                self.assertIn(k, res, msg=f"{k} not found in response")

    def test_setup_code(self):
        if self.client.identity_token:
            self.skipTest("Client already authorised")

        _ = self.client.get_chip()
        sync_code = "12345678"
        with self.assertRaises(ClientNotFoundError):
            self.client.clone_by_code(sync_code)

        # test for valid code
        # res = self.client.clone_by_code(sync_code)
        # for k in ("result", "chip"):
        #     with self.subTest("cloned response", k=k):
        #         self.assertIn(k, res, msg=f"{k} not found in response")
        # self.assertEqual(res.get("result"), "cloned")

    def test_sync(self):
        if self.client.identity_token:
            res = self.client.sync()
            for k in ("result", "cards", "holds", "summary", "identity"):
                with self.subTest("sync response", k=k):
                    self.assertIn(k, res, msg=f"{k} not found in response")
        else:
            with self.assertRaises(ClientForbiddenError):
                self.client.sync()

    def test_fulfillment(self):
        if not self.client.identity_token:
            self.skipTest("Client not authorised")

        loans = self.client.get_loans()
        tested_epub = False
        tested_magazine = False
        for loan in loans:
            if not (
                self.client.is_downloadable_magazine_loan(loan)
                or self.client.is_downloadable_ebook_loan(loan)
            ):
                continue
            format_id = self.client.get_loan_format(loan)
            file_ext = self.client.get_file_extension(format_id)
            if file_ext != "epub":
                continue
            if file_ext == "epub" and not tested_epub:
                self.logger.info(
                    "Fulfilling.. %s: %s %s", loan["title"], format_id, file_ext
                )
                tested_epub = True
                _, openbook, rosters = self.client.process_ebook(loan)
            elif file_ext == "acsm" and not tested_magazine:
                self.logger.info(
                    "Fulfilling.. %s: %s %s", loan["title"], format_id, file_ext
                )
                tested_magazine = True
                loan_res_content = self.client.fulfill_loan_file(
                    loan["id"], loan["cardId"], format_id
                )
                loan_file_path = Path(f'{loan["id"]}.{file_ext}')
                with loan_file_path.open("wb") as f:
                    f.write(loan_res_content)
                    self.logger.info('Downloaded "%s"', loan_file_path)
            if tested_magazine and tested_epub:
                break

    def test_get_loan_format(self):
        with self.assertRaises(ValueError) as context:
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": True},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": False},
                    ]
                }
            )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": True},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": False},
                    ]
                },
                raise_if_not_downloadable=False,
            ),
            LibbyFormats.EBookKindle,
        )
        self.assertEqual(
            str(context.exception),
            f'Loan is locked to a non-downloadable format "{LibbyFormats.EBookKindle}"',
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": False},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": True},
                        {"id": LibbyFormats.EBookEPubOpen, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookEPubAdobe,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": False},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookEPubAdobe,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": False},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubOpen, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookEPubOpen,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookKindle, "isLockedIn": False},
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubAdobe, "isLockedIn": False},
                        {"id": LibbyFormats.EBookEPubOpen, "isLockedIn": False},
                    ]
                },
                prefer_open_format=False,
            ),
            LibbyFormats.EBookEPubAdobe,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookPDFAdobe, "isLockedIn": False},
                        {"id": LibbyFormats.EBookPDFOpen, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookPDFOpen,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookPDFAdobe, "isLockedIn": False},
                        {"id": LibbyFormats.EBookPDFOpen, "isLockedIn": False},
                    ]
                },
                prefer_open_format=False,
            ),
            LibbyFormats.EBookPDFAdobe,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                        {"id": LibbyFormats.EBookPDFAdobe, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookPDFAdobe,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.AudioBookMP3, "isLockedIn": False},
                        {"id": LibbyFormats.AudioBookOverDrive, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.AudioBookMP3,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.MagazineOverDrive, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.MagazineOverDrive,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.AudioBookMP3, "isLockedIn": False},
                        {"id": LibbyFormats.AudioBookOverDrive, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.AudioBookMP3,
        )
        self.assertEqual(
            LibbyClient.get_loan_format(
                {
                    "formats": [
                        {"id": LibbyFormats.EBookOverdrive, "isLockedIn": False},
                    ]
                }
            ),
            LibbyFormats.EBookOverdrive,
        )

    def test_parse_datetime(self):
        for value in (
            "2017-06-06T04:00:00Z",  # estimatedReleaseDate, publishDate
            "2023-08-10T23:00:01.000Z",  # expireDate
            "2023-07-31T08:00:01.000+00:00",  # placedDate
            "2023-08-01T10:00:01.000Z",  # placedDate
            "05/30/2023",
        ):
            with self.subTest(value=value):
                LibbyClient.parse_datetime(value)

        with self.assertRaises(ValueError):
            LibbyClient.parse_datetime("2023/05/30 23:01:14")

    @patch("urllib.request.OpenerDirector.open")
    def test_client_error_handling(self, open_mock):
        client = LibbyClient(
            identity_token=".",
            max_retries=0,
            timeout=15,
            logger=self.logger,
        )

        open_mock.side_effect = [
            MockHTTPError(400, {}),
            MockHTTPError(401, {"result": "unauthorized"}),
            MockHTTPError(
                401,
                {
                    "result": "credentials_rejected",
                    "upstream": {
                        "errorCode": "UserDenied",
                        "errorMessage": 'Patron denied by their ILS with message "Your Library Card and PIN could not be validated at this time."',
                        "service": "X",
                        "httpStatus": 400,
                        "userExplanation": "Your Library Card and PIN could not be validated at this time.",
                    },
                },
            ),
            MockHTTPError(403, {"result": "missing_chip"}),
            MockHTTPError(404, {}),
            MockHTTPError(405, {}),
            MockHTTPError(429, {}),
            MockHTTPError(
                500,
                {
                    "result": "upstream_failure",
                    "upstream": {
                        "errorCode": "InternalError",
                        "service": "THUNDER",
                        "httpStatus": 500,
                        "userExplanation": "An unexpected error has occurred.",
                        "correlationId": "e3294b2a637e6139e388f360847bf239",
                    },
                },
            ),
            URLError("No route to host"),
        ]
        with self.assertRaises(ClientBadRequestError):
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(ClientUnauthorisedError):
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(ClientUnauthorisedError) as context:
            client.verify_card(
                website_id="999", ils="default", username="x", password=""
            )
        self.assertEqual(
            context.exception.msg,
            "Your Library Card and PIN could not be validated at this time. [errorcode: UserDenied]",
        )

        with self.assertRaises(ClientForbiddenError) as context:
            client.sync()
        self.assertEqual(
            context.exception.msg,
            "HTTP Error 403",
        )

        with self.assertRaises(ClientNotFoundError):
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(ClientError):
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(ClientThrottledError):
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(InternalServerError) as context:
            client.borrow_title(title_id="123456", title_format="x", card_id="9")

        with self.assertRaises(ClientConnectionError):
            client.sync()

    def test_tags(self):
        if not self.client.identity_token:
            self.skipTest("Client not authorised")

        res = self.client.tags()
        for k in ("tags", "totalTags", "totalTaggings"):
            with self.subTest("response", k=k):
                self.assertIn(k, res, msg=f'"{k}" not found')
        for tag in res.get("tags"):
            for k in (
                "name",
                "uuid",
                "description",
                "behaviors",
                "createTime",
                "totalTaggings",
                "taggings",
            ):
                with self.subTest("tag", k=k):
                    self.assertIn(k, tag, msg=f'"{k}" not found')

    def test_tag(self):
        if not self.client.identity_token:
            self.skipTest("Client not authorised")

        res = self.client.tags()
        per_page = 12
        for tag in res.get("tags"):
            if tag.get("totalTaggings", 0) <= per_page:
                # get a tag that requires paging
                continue
            total_titles_expected = tag["totalTaggings"]
            curr_page = 0
            tagged_titles = []
            while True:
                res = self.client.tag_paged(
                    tag["uuid"], tag["name"], page=curr_page, per_page=per_page
                )
                curr_page += 1
                tag_found = res.get("tag")
                self.assertTrue(tag_found)
                for k2 in (
                    "name",
                    "uuid",
                    "description",
                    "behaviors",
                    "createTime",
                    "facetCounts",
                    "totalTaggings",
                    "taggings",
                ):
                    with self.subTest("tag_found", k2=k2):
                        self.assertIn(k2, tag_found, msg=f'"{k2}" not found')
                for title in tag_found["taggings"]:
                    for k3 in (
                        "titleId",
                        "websiteId",
                        "cardId",
                        "createTime",
                        "titleFormat",
                        "titleSubjects",
                        "sortTitle",
                        "sortAuthor",
                    ):
                        with self.subTest("title", k3=k3):
                            self.assertIn(k3, title, msg=f'"{k3}" not found')
                    self.assertNotIn(title["titleId"], tagged_titles)
                    tagged_titles.append(title["titleId"])

                if len(tag_found["taggings"]) < per_page:
                    # last page
                    break

            self.assertEqual(total_titles_expected, len(tagged_titles))
            break

    def test_taggings(self):
        if not self.client.identity_token:
            self.skipTest("Client not authorised")

        title_ids = ["784353", "36635"]
        res = self.client.taggings(title_ids)
        self.assertEqual(len(title_ids), len(res.items()))
        for title_id in title_ids:
            self.assertIn(title_id, res)
            if not res[title_id]:
                # title has not been tagged
                continue
            for tag in res[title_id]:
                for k in (
                    "titleId",
                    "websiteId",
                    "cardId",
                    "createTime",
                    "titleFormat",
                    "titleSubjects",
                    "sortTitle",
                    "sortAuthor",
                    "properties",
                    "tagUUID",
                    "tagName",
                ):
                    with self.subTest("title", k=k):
                        self.assertIn(k, tag, msg=f'"{k}" not found')
