import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from collector import http, sources
from collector.sources.base import CredentialError, SourceError, parse_iso_duration
from collector.sources.youtube_music import (YouTubeMusicSource, clean_video_title, parse_playlist_id,
                                             split_youtube_title)
from tests.fakes import Router, fixture, http_error

LINK = "https://music.youtube.com/playlist?list=PLtest123"
CREDS = {"api_key": "AIzaKEY"}


def api_error(code: int, reason: str, message: str = "") -> urllib.error.HTTPError:
    body = {"error": {"code": code, "message": message or reason, "errors": [{"reason": reason, "message": message}]}}
    return http_error(code, json.dumps(body))


class Links(unittest.TestCase):
    def test_parse_link_variants(self):
        for link in (LINK,
                     "https://www.youtube.com/playlist?list=PLtest123",
                     "https://youtube.com/watch?v=abc&list=PLtest123&index=2",
                     "https://music.youtube.com/browse/VLPLtest123",
                     "PLtest123"):
            self.assertEqual(parse_playlist_id(link), "PLtest123", link)
        self.assertEqual(parse_playlist_id("https://music.youtube.com/playlist?list=OLAK5uy_abc-DEF"), "OLAK5uy_abc-DEF")

    def test_other_service_link_refused(self):
        with self.assertRaises(SourceError):
            parse_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

    def test_mix_and_liked_refused_with_reason(self):
        with self.assertRaises(SourceError) as cm:
            parse_playlist_id("https://www.youtube.com/watch?v=abc&list=RDabc")
        self.assertIn("Mix", str(cm.exception))
        with self.assertRaises(SourceError) as cm:
            parse_playlist_id("https://music.youtube.com/playlist?list=LM")
        self.assertIn("Liked", str(cm.exception))

    def test_registered_and_detected(self):
        self.assertIsInstance(sources.get_source("youtube_music"), YouTubeMusicSource)
        self.assertEqual(sources.detect(LINK), "youtube_music")
        self.assertEqual(sources.detect("https://www.youtube.com/playlist?list=PLx"), "youtube_music")
        self.assertEqual(list(sources.REGISTRY)[:2], ["spotify", "youtube_music"])


class SetupSteps(unittest.TestCase):
    def test_every_real_service_explains_its_set_up(self):
        for source in (sources.get_source("spotify"), sources.get_source("youtube_music")):
            self.assertGreaterEqual(len(source.setup_steps), 4, source.id)
            self.assertTrue(any("https://" in step for step in source.setup_steps), source.id)
        self.assertTrue(any("{redirect_uri}" in step for step in sources.get_source("spotify").setup_steps))


class Titles(unittest.TestCase):
    def test_split_topic_channel(self):
        self.assertEqual(split_youtube_title("Creep", "Radiohead - Topic"), ("Creep", ["Radiohead"]))

    def test_split_dash_title(self):
        self.assertEqual(split_youtube_title("Radiohead - Creep (Official Video)", "Radiohead"), ("Creep", ["Radiohead"]))
        self.assertEqual(split_youtube_title("Björk – Jóga (Live)", "björk"), ("Jóga (Live)", ["Björk"]))
        self.assertEqual(split_youtube_title("A — B", "x"), ("B", ["A"]))

    def test_no_dash_uses_channel_without_vevo(self):
        self.assertEqual(split_youtube_title("Black Hole Sun", "SoundgardenVEVO"), ("Black Hole Sun", ["Soundgarden"]))

    def test_clean_keeps_version_words(self):
        self.assertEqual(clean_video_title("Song (Official Music Video) [HD]"), "Song")
        self.assertEqual(clean_video_title("Song (Lyrics)"), "Song")
        self.assertEqual(clean_video_title("Song (Official Lyric Video)"), "Song")
        self.assertEqual(clean_video_title("Song (Visualizer)"), "Song")
        self.assertEqual(clean_video_title("Song (Live at Wembley)"), "Song (Live at Wembley)")
        self.assertEqual(clean_video_title("Song (Acoustic) (Official Audio)"), "Song (Acoustic)")

    def test_real_world_titles(self):
        # Taken from a real public playlist read with a live key.
        cases = [
            ("Matchbox Twenty - 3AM (Official Video) [HD Remaster]", "Matchbox Twenty", ("3AM", ["Matchbox Twenty"])),
            ("Green Day - Basket Case [Official Music Video] (4K Upgrade)", "Green Day", ("Basket Case", ["Green Day"])),
            ("Red Hot Chili Peppers - Otherside (Official Music Video) [HD UPGRADE]", "Red Hot Chili Peppers",
             ("Otherside", ["Red Hot Chili Peppers"])),
            ("The Cranberries - Linger (4K Official Music Video)", "TheCranberriesVEVO", ("Linger", ["The Cranberries"])),
            ("No Doubt - Don't Speak (Official 4K Music Video)", "NoDoubtVEVO", ("Don't Speak", ["No Doubt"])),
            ("Filter - Take A Picture (Official HD Music Video)", "FILTER", ("Take A Picture", ["Filter"])),
            ("Tonic - Open Up Your Eyes (Closed-Captioned)", "TonicVEVO", ("Open Up Your Eyes", ["Tonic"])),
            ("Garbage - Special (w/Titles)", "GarbageVEVO", ("Special", ["Garbage"])),
            ("The Cranberries - Dreams (Dir: Peter Scammell) (Official Music Video)", "x", ("Dreams", ["The Cranberries"])),
            ("Fastball - Out Of My Head (Official video) www.fastballtheband.com", "fastball",
             ("Out Of My Head", ["Fastball"])),
            ('The Offspring - "Self Esteem"', "Epitaph Records", ("Self Esteem", ["The Offspring"])),
            ("Rancid - 'Ruby Soho' (Music Video)", "Rancid", ("Ruby Soho", ["Rancid"])),
            ('"Desperately Wanting" official music video', "Better Than Ezra", ("Desperately Wanting", ["Better Than Ezra"])),
            ("Vertical Horizon- You're A God", "x", ("You're A God", ["Vertical Horizon"])),
            ("Pearl Jam - Better Man (Live from Madison Square Garden)", "PearljamVEVO",
             ("Better Man (Live from Madison Square Garden)", ["Pearl Jam"])),
            ("Blur - Song 2 (2012 Remastered Version)", "x", ("Song 2 (2012 Remastered Version)", ["Blur"])),
            ("blink-182 - Dammit", "blink182VEVO", ("Dammit", ["blink-182"])),
            ("Eagle-Eye Cherry - Save Tonight", "x", ("Save Tonight", ["Eagle-Eye Cherry"])),
        ]
        for video_title, channel, expected in cases:
            self.assertEqual(split_youtube_title(video_title, channel), expected, video_title)

    def test_iso_duration(self):
        self.assertEqual(parse_iso_duration("PT3M59S"), 239)
        self.assertEqual(parse_iso_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_iso_duration("PT45S"), 45)
        self.assertEqual(parse_iso_duration("P1DT1S"), 86401)
        self.assertEqual(parse_iso_duration("garbage"), 0)
        self.assertEqual(parse_iso_duration(""), 0)


class GetPlaylist(unittest.TestCase):
    def route(self, override: dict | None = None) -> Router:
        routes = {
            ("GET", "/playlists?"): fixture("youtube_music", "playlist.json"),
            ("GET", "pageToken=P2"): fixture("youtube_music", "items_page2.json"),
            ("GET", "/playlistItems?"): fixture("youtube_music", "items_page1.json"),
            ("GET", "/videos?"): [fixture("youtube_music", "videos_page1.json"),
                                  fixture("youtube_music", "videos_page2.json")],
        }
        routes.update(override or {})
        router = Router(routes)
        for target, value in ((http, "opener"), (http, "sleep")):
            p = mock.patch.object(target, value, router if value == "opener" else (lambda s: None))
            p.start()
            self.addCleanup(p.stop)
        return router

    def test_maps_fixture_to_tracks(self):
        router = self.route()
        playlist = YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertEqual((playlist.source, playlist.id, playlist.name), ("youtube_music", "PLtest123", "Nineties Rock"))
        self.assertEqual(playlist.url, "https://music.youtube.com/playlist?list=PLtest123")
        first = playlist.tracks[0]
        self.assertEqual((first.id, first.title, first.artists, first.album, first.duration),
                         ("vid1", "Creep", ["Radiohead"], "", 239))
        self.assertEqual(first.url, "https://music.youtube.com/watch?v=vid1")
        self.assertIn("key=AIzaKEY", router.requests[0].full_url)

    def test_paging_and_skips_deleted(self):
        self.route()
        tracks = YouTubeMusicSource().get_playlist(LINK, dict(CREDS)).tracks
        self.assertEqual([(t.title, t.artist, t.duration) for t in tracks],
                         [("Creep", "Radiohead", 239), ("Black Hole Sun", "Soundgarden", 320), ("Jóga (Live)", "Björk", 3723)])

    def test_durations_requested_in_one_batch_per_page(self):
        router = self.route()
        YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        video_calls = [r for r in router.requests if "/videos?" in r.full_url]
        self.assertEqual(len(video_calls), 2)
        ids = urllib.parse.parse_qs(urllib.parse.urlparse(video_calls[0].full_url).query)["id"][0]
        self.assertEqual(ids, "vid1,vid3")

    def test_youtube_link_gives_youtube_urls(self):
        self.route()
        playlist = YouTubeMusicSource().get_playlist("https://www.youtube.com/playlist?list=PLtest123", dict(CREDS))
        self.assertEqual(playlist.tracks[0].url, "https://www.youtube.com/watch?v=vid1")
        self.assertEqual(playlist.url, "https://www.youtube.com/playlist?list=PLtest123")

    def test_auth_refused_is_credential_error(self):
        self.route({("GET", "/playlists?"): api_error(400, "badRequest", "API key not valid. Please pass a valid API key.")})
        with self.assertRaises(CredentialError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertIn("Credentials", cm.exception.fix)

    def test_api_not_enabled_is_credential_error(self):
        self.route({("GET", "/playlists?"): api_error(403, "accessNotConfigured", "YouTube Data API v3 has not been used")})
        with self.assertRaises(CredentialError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertIn("Enable", cm.exception.fix)

    def test_quota_is_source_error(self):
        self.route({("GET", "/playlists?"): api_error(403, "quotaExceeded")})
        with self.assertRaises(SourceError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertNotIsInstance(cm.exception, CredentialError)
        self.assertIn("tomorrow", str(cm.exception))

    def test_not_found_is_source_error(self):
        self.route({("GET", "/playlists?"): {"items": []}})
        with self.assertRaises(SourceError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertNotIsInstance(cm.exception, CredentialError)
        self.assertIn("YouTube", str(cm.exception))

    def test_items_404_is_source_error(self):
        self.route({("GET", "/playlistItems?"): api_error(404, "playlistNotFound")})
        with self.assertRaises(SourceError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertNotIsInstance(cm.exception, CredentialError)

    def test_missing_key(self):
        with self.assertRaises(CredentialError):
            YouTubeMusicSource().get_playlist(LINK, {})

    def test_network_error(self):
        self.route({("GET", "/playlists?"): urllib.error.URLError("down")})
        with self.assertRaises(SourceError) as cm:
            YouTubeMusicSource().get_playlist(LINK, dict(CREDS))
        self.assertIn("reach YouTube", str(cm.exception))

    def test_test_returns_ok_message(self):
        self.route({("GET", "/i18nLanguages?"): {"items": [{"id": "en"}]}})
        self.assertIn("YouTube", YouTubeMusicSource().test(dict(CREDS)))

    def test_test_bad_key(self):
        self.route({("GET", "/i18nLanguages?"): api_error(400, "badRequest", "API key not valid.")})
        with self.assertRaises(CredentialError):
            YouTubeMusicSource().test(dict(CREDS))


if __name__ == "__main__":
    unittest.main()
