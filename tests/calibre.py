import logging
import sys
import unittest

from calibre.gui2 import ensure_app, destroy_app


class CalibreTests(unittest.TestCase):
    def test_rating_to_stars(self):
        from calibre_plugins.overdrive_libby.utils import rating_to_stars

        self.assertEqual("★★★", rating_to_stars(3))
        self.assertEqual("★★★", rating_to_stars(3.2))
        self.assertEqual("★★★⯨", rating_to_stars(3.4))
        self.assertEqual("★★★⯨", rating_to_stars(3.6))

    def test_generate_od_identifier(self):
        from calibre_plugins.overdrive_libby.utils import generate_od_identifier

        self.assertEqual(
            "1234@abc.overdrive.com",
            generate_od_identifier({"id": "1234"}, {"preferredKey": "abc"}),
        )

    def test_simplecache(self):
        from calibre_plugins.overdrive_libby.utils import SimpleCache

        cache = SimpleCache(capacity=2)
        a = {"a": 1}
        b = {"b": 1}
        c = {"c": 1}
        cache.put("a", a)
        self.assertEqual(cache.count(), 1)
        self.assertEqual(cache.get("a"), a)
        cache.put("b", b)
        self.assertEqual(cache.count(), 2)
        self.assertEqual(cache.get("b"), b)
        cache.put("c", c)
        self.assertEqual(cache.count(), 2)
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("b"))
        self.assertIsNotNone(cache.get("c"))
        cache.clear()
        self.assertEqual(cache.count(), 0)

    def test_truncate_for_display(self):
        from calibre_plugins.overdrive_libby.models import truncate_for_display

        self.assertEqual(
            "Ipsum debitis dignissimo…",
            truncate_for_display("Ipsum debitis dignissimos aspernatur."),
        )
        self.assertEqual(
            "Ipsum debitis dignissimo…",
            truncate_for_display("Ipsum debitis dignissimos aspernatur.", width=-100),
        )
        self.assertEqual(
            "Ipsum debitis dignissimo…",
            truncate_for_display(
                "Ipsum debitis dignissimos aspernatur.", text_length=-1
            ),
        )
        self.assertEqual(
            "Ipsum debitis d…",
            truncate_for_display(
                "Ipsum debitis dignissimos aspernatur.", text_length=20
            ),
        )

    def test_log_handler(self):
        from calibre.utils.logging import Log, DEBUG
        from calibre_plugins.overdrive_libby.utils import create_job_logger

        logger: logging.Logger = create_job_logger(Log(DEBUG))
        msg = "Level %s"
        logger.debug(msg, logging.DEBUG)
        logger.info(msg, logging.INFO)
        logger.warning(msg, logging.WARNING)
        logger.error(msg, logging.ERROR)
        logger.critical(msg, logging.CRITICAL)
        try:
            1 / 0
        except:  # noqa
            logger.exception("Test Exception")


# Run with:
# calibre-customize -b calibre-plugin && calibre-debug -e tests/calibre.py
if __name__ == "__main__":
    try:
        ensure_app()
        suite = unittest.TestSuite(unittest.makeSuite(CalibreTests))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            sys.exit(1)
    finally:
        destroy_app()
