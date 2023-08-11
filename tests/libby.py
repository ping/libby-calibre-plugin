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

from libby import LibbyClient, LibbyFormats
from libby.errors import ClientNotFoundError, ClientForbiddenError

from .base import BaseTests


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
