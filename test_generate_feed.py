import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from pathlib import Path

from generate_feed import Episode, Show, audio_metadata, build_rss, episode_from_api, merge_episodes


UTC = dt.timezone.utc


class FeedTests(unittest.TestCase):
    show = Show("primjer", "Primjer emisije", Path("primjer.xml"))

    def test_null_audio_metadata_is_ignored(self):
        self.assertIsNone(audio_metadata({"audio": {"metadata": [None]}}))

    def test_same_audio_is_emitted_once(self):
        rss_item = Episode("Stari naslov", "", "https://api.hrt.hr/a.mp3?x=1", dt.datetime(2026, 1, 2, tzinfo=UTC), length=123, source="SLUŽBENI RSS")
        emission = Episode("Pravi naslov", "Opis", "https://api.hrt.hr/a.mp3", dt.datetime(2026, 1, 1, tzinfo=UTC), audio_id="42", source="EMISIJE")
        merged = merge_episodes([[rss_item], [emission]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Pravi naslov")
        self.assertEqual(merged[0].length, 123)
        self.assertEqual(merged[0].guid, "urn:open-feed:audio:42")

    def podcast_record(self, path, published):
        return {
            "caption": "Beatrica Kurbel: SPAVAŠ LI MIRNO?",
            "intro": "Opis",
            "originalPublishedUtc": published,
            "audio": {"metadata": [{"path": path, "id": 1414450}]},
            "thumbnail": {"metadata": [{"path": "https://api.hrt.hr/t.webp"}]},
        }

    def emission_record(self, path, broadcast_start):
        return {
            "caption": "Beatrica Kurbel: SPAVAŠ LI MIRNO?",
            "intro": "Opis",
            "bag": {"contentItems": [{"broadcastStart": broadcast_start}]},
            "audio": {"metadata": [{"path": path, "id": 1414450}]},
            "thumbnail": {"metadata": []},
        }

    def test_podcast_date_comes_from_audio_filename(self):
        # HRT podcast kanal zna cijeloj grupi epizoda prepisati isti datum objave.
        record = self.podcast_record(
            "https://api.hrt.hr/media/4f/21/20261030-krik-37697894-20260918085137.mp3",
            "2026-10-16T21:55:00Z",
        )
        episode = episode_from_api(record, "PODCAST", self.show)
        self.assertEqual(episode.published.date(), dt.date(2026, 10, 30))

    def test_republished_old_episode_keeps_original_date(self):
        record = self.podcast_record(
            "https://api.hrt.hr/media/60/cb/20250117-krik-35915105-20241211131045.mp3",
            "2026-10-16T21:50:00Z",
        )
        episode = episode_from_api(record, "PODCAST", self.show)
        self.assertEqual(episode.published.date(), dt.date(2025, 1, 17))

    def test_emission_date_is_not_overridden_by_filename(self):
        record = self.emission_record(
            "https://api.hrt.hr/media/4f/21/20261016-krik-1-20261016120000.mp3",
            "2026-10-30T22:05:00Z",
        )
        episode = episode_from_api(record, "EMISIJE", self.show)
        self.assertEqual(episode.published.date(), dt.date(2026, 10, 30))

    def test_podcast_duplicate_of_emission_is_dropped(self):
        emission = Episode("Ista epizoda", "", "https://api.hrt.hr/a.mp3", dt.datetime(2026, 10, 23, 21, 5, tzinfo=UTC), audio_id="2", source="EMISIJE")
        podcast = Episode("Ista epizoda", "", "https://api.hrt.hr/b.mp3", dt.datetime(2026, 10, 23, 21, 55, tzinfo=UTC), audio_id="1", source="PODCAST")
        merged = merge_episodes([[podcast], [emission]])
        self.assertEqual([item.audio_url for item in merged], ["https://api.hrt.hr/a.mp3"])

    def test_feed_has_valid_enclosure_and_stable_guid(self):
        episode = Episode("Naslov", "Opis", "https://api.hrt.hr/a.mp3", dt.datetime(2026, 1, 1, tzinfo=UTC), audio_id="42", length=123)
        root = ET.fromstring(build_rss([episode], "https://example.test/primjer.xml", self.show))
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("guid"), "urn:open-feed:audio:42")
        self.assertEqual(item.find("enclosure").get("length"), "123")
        self.assertEqual(item.findtext("description"), "Opis")
        self.assertEqual(root.findtext("./channel/title"), "Primjer emisije")


if __name__ == "__main__":
    unittest.main()
