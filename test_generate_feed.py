import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from generate_feed import Episode, audio_metadata, build_rss, merge_episodes


UTC = dt.timezone.utc


class FeedTests(unittest.TestCase):
    def test_null_audio_metadata_is_ignored(self):
        self.assertIsNone(audio_metadata({"audio": {"metadata": [None]}}))

    def test_same_audio_is_emitted_once(self):
        rss_item = Episode("Stari naslov", "", "https://api.hrt.hr/a.mp3?x=1", dt.datetime(2026, 1, 2, tzinfo=UTC), length=123, source="SLUŽBENI RSS")
        emission = Episode("Pravi naslov", "Opis", "https://api.hrt.hr/a.mp3", dt.datetime(2026, 1, 1, tzinfo=UTC), audio_id="42", source="EMISIJE")
        merged = merge_episodes([[rss_item], [emission]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Pravi naslov")
        self.assertEqual(merged[0].length, 123)
        self.assertEqual(merged[0].guid, "urn:krik:audio:42")

    def test_feed_has_valid_enclosure_and_stable_guid(self):
        episode = Episode("Naslov", "Opis", "https://api.hrt.hr/a.mp3", dt.datetime(2026, 1, 1, tzinfo=UTC), audio_id="42", length=123)
        root = ET.fromstring(build_rss([episode], "https://example.test/krik.xml"))
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("guid"), "urn:krik:audio:42")
        self.assertEqual(item.find("enclosure").get("length"), "123")


if __name__ == "__main__":
    unittest.main()
