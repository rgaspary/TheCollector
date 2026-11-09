"""Tag reader tests. Every sample file is built byte by byte here, a few hundred bytes each."""
import struct
import tempfile
import unittest
import uuid
from pathlib import Path

from collector.libraries.tags import Tags, read_tags


# ---- builders -------------------------------------------------------------------------------
def syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def id3_text(enc: int, text: str) -> bytes:
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[enc]
    return bytes([enc]) + text.encode(codec)


def id3v2(major: int, frames: list[tuple[str, bytes]], flags: int = 0) -> bytes:
    body = b""
    for fid, data in frames:
        if major == 2:
            body += fid.encode() + len(data).to_bytes(3, "big") + data
        else:
            size = syncsafe(len(data)) if major == 4 else len(data).to_bytes(4, "big")
            body += fid.encode() + size + b"\0\0" + data
    return b"ID3" + bytes([major, 0, flags]) + syncsafe(len(body)) + body


def mpeg1_l3_frame(xing_frames: int | None = None, bitrate_index: int = 9) -> bytes:
    """One 44.1 kHz stereo MPEG-1 Layer III frame (128 kbps by default), optionally carrying a Xing header."""
    header = bytes([0xFF, 0xFB, (bitrate_index << 4) | (0 << 2), 0x00])
    bitrate = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320][bitrate_index]
    size = 144 * bitrate * 1000 // 44100
    body = bytearray(size - 4)
    if xing_frames is not None:
        body[32:32 + 12] = b"Xing" + (1).to_bytes(4, "big") + xing_frames.to_bytes(4, "big")
    return header + bytes(body)


def id3v1(title: str, artist: str, album: str) -> bytes:
    def field(s: str, n: int = 30) -> bytes:
        return s.encode("latin-1")[:n].ljust(n, b"\0")
    return b"TAG" + field(title) + field(artist) + field(album) + b"2001" + field("", 30) + b"\xff"


def vorbis_comment(fields: list[tuple[str, str]]) -> bytes:
    vendor = b"test"
    out = len(vendor).to_bytes(4, "little") + vendor + len(fields).to_bytes(4, "little")
    for k, v in fields:
        entry = f"{k}={v}".encode()
        out += len(entry).to_bytes(4, "little") + entry
    return out


def flac(sample_rate: int, total_samples: int, fields: list[tuple[str, str]]) -> bytes:
    packed = (sample_rate << 44) | (1 << 41) | (15 << 36) | total_samples
    streaminfo = b"\0\x10\0\x10" + b"\0\0\0" + b"\0\0\0" + packed.to_bytes(8, "big") + bytes(16)
    comment = vorbis_comment(fields)
    return (b"fLaC" + bytes([0]) + len(streaminfo).to_bytes(3, "big") + streaminfo
            + bytes([0x80 | 4]) + len(comment).to_bytes(3, "big") + comment)


def atom(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def mp4(title: str, artist: str, album: str, album_artist: str, timescale: int, duration: int) -> bytes:
    def item(kind: bytes, text: str) -> bytes:
        return atom(kind, atom(b"data", (1).to_bytes(4, "big") + bytes(4) + text.encode()))
    mvhd = atom(b"mvhd", bytes(4) + bytes(8) + timescale.to_bytes(4, "big") + duration.to_bytes(4, "big") + bytes(80))
    ilst = atom(b"ilst", item(b"\xa9nam", title) + item(b"\xa9ART", artist) + item(b"\xa9alb", album)
                + item(b"aART", album_artist))
    meta = atom(b"meta", bytes(4) + atom(b"hdlr", bytes(25)) + ilst)
    moov = atom(b"moov", mvhd + atom(b"udta", meta))
    return atom(b"ftyp", b"M4A " + bytes(4)) + atom(b"free", bytes(8)) + moov + atom(b"mdat", bytes(32))


def ogg_page(packet_data: bytes, granule: int, seq: int, flags: int = 0) -> bytes:
    segments, rest = [], len(packet_data)
    while rest >= 255:
        segments.append(255)
        rest -= 255
    segments.append(rest)
    return (b"OggS" + bytes([0, flags]) + granule.to_bytes(8, "little", signed=True) + (1).to_bytes(4, "little")
            + seq.to_bytes(4, "little") + bytes(4) + bytes([len(segments)]) + bytes(segments) + packet_data)


def ogg_vorbis(sample_rate: int, last_granule: int, fields: list[tuple[str, str]]) -> bytes:
    ident = b"\x01vorbis" + bytes(4) + bytes([2]) + sample_rate.to_bytes(4, "little") + bytes(12) + b"\xb8\x01"
    comment = b"\x03vorbis" + vorbis_comment(fields) + b"\x01"
    return (ogg_page(ident, 0, 0, flags=2) + ogg_page(comment, 0, 1)
            + ogg_page(bytes(20), last_granule // 2, 2) + ogg_page(bytes(20), last_granule, 3, flags=4))


def ogg_opus(pre_skip: int, last_granule: int, fields: list[tuple[str, str]]) -> bytes:
    head = b"OpusHead" + bytes([1, 2]) + pre_skip.to_bytes(2, "little") + (48000).to_bytes(4, "little") + bytes(3)
    tags = b"OpusTags" + vorbis_comment(fields)
    return ogg_page(head, 0, 0, flags=2) + ogg_page(tags, 0, 1) + ogg_page(bytes(20), last_granule, 2, flags=4)


def asf_object(guid: str, payload: bytes) -> bytes:
    return uuid.UUID(guid).bytes_le + (24 + len(payload)).to_bytes(8, "little") + payload


def asf(title: str, author: str, album: str, album_artist: str, seconds: int) -> bytes:
    def u16(s: str) -> bytes:
        return s.encode("utf-16-le") + b"\0\0"
    t, a = u16(title), u16(author)
    content = struct.pack("<5H", len(t), len(a), 0, 0, 0) + t + a
    ext_items = b""
    for name, value in (("WM/AlbumTitle", album), ("WM/AlbumArtist", album_artist)):
        n, v = u16(name), u16(value)
        ext_items += struct.pack("<H", len(n)) + n + struct.pack("<HH", 0, len(v)) + v
    ext = struct.pack("<H", 2) + ext_items
    play = (seconds * 10_000_000 + 3000 * 10_000)
    props = bytes(16) + bytes(8) + bytes(8) + bytes(8) + play.to_bytes(8, "little") + bytes(8) + (3000).to_bytes(8, "little") + bytes(20)
    children = (asf_object("8CABDCA1-A947-11CF-8EE4-00C00C205365", props)
                + asf_object("75B22633-668E-11CF-A6D9-00AA0062CE6C", content)
                + asf_object("D2D0A440-E307-11D2-97F0-00A0C95EA850", ext))
    return asf_object("75B22630-668E-11CF-A6D9-00AA0062CE6C", (3).to_bytes(4, "little") + b"\x01\x02" + children)


# ---- tests ----------------------------------------------------------------------------------
class ReadTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name: str, data: bytes) -> Path:
        path = Path(self.tmp.name) / name
        path.write_bytes(data)
        return path

    def test_id3v24_utf8(self):
        tag = id3v2(4, [("TIT2", id3_text(3, "Jóga")), ("TPE1", id3_text(3, "Björk")),
                        ("TALB", id3_text(3, "Homogenic")), ("TPE2", id3_text(3, "Björk")),
                        ("TLEN", id3_text(3, "305000"))])
        tags = read_tags(self.file("a.mp3", tag))
        self.assertEqual(tags, Tags("Jóga", "Björk", "Homogenic", "Björk", 305))

    def test_id3v24_multiple_artists(self):
        tag = id3v2(4, [("TIT2", id3_text(3, "Song")), ("TPE1", id3_text(3, "A\0B"))])
        self.assertEqual(read_tags(self.file("a.mp3", tag)).artist, "A, B")

    def test_id3v23_utf16(self):
        tag = id3v2(3, [("TIT2", id3_text(1, "Café del Mar")), ("TPE1", id3_text(1, "Energy 52")),
                        ("TALB", id3_text(0, "Café del Mar"))])
        tags = read_tags(self.file("a.mp3", tag))
        self.assertEqual((tags.title, tags.artist, tags.album), ("Café del Mar", "Energy 52", "Café del Mar"))

    def test_id3v23_unsynchronised(self):
        # Unsynchronisation puts a 0x00 after every 0xFF inside the tag; ÿ is 0xFF in Latin-1.
        tag = id3v2(3, [("TIT2", id3_text(0, "ÿes"))])
        size = int.from_bytes(tag[6:10], "big")
        body = tag[10:].replace(b"\xff", b"\xff\x00")
        tag = b"ID3" + bytes([3, 0, 0x80]) + syncsafe(len(body)) + body
        self.assertEqual(read_tags(self.file("a.mp3", tag)).title, "ÿes")
        self.assertTrue(size)

    def test_id3v22(self):
        tag = id3v2(2, [("TT2", id3_text(0, "Old")), ("TP1", id3_text(0, "Format")), ("TAL", id3_text(0, "Tag"))])
        tags = read_tags(self.file("a.mp3", tag))
        self.assertEqual((tags.title, tags.artist, tags.album), ("Old", "Format", "Tag"))

    def test_id3v1_fallback(self):
        data = mpeg1_l3_frame() * 3 + id3v1("Creep", "Radiohead", "Pablo Honey")
        tags = read_tags(self.file("a.mp3", data))
        self.assertEqual((tags.title, tags.artist, tags.album), ("Creep", "Radiohead", "Pablo Honey"))

    def test_mp3_duration_from_xing(self):
        # 1000 frames × 1152 samples / 44100 Hz = 26.1 s
        data = id3v2(3, [("TIT2", id3_text(0, "x"))]) + mpeg1_l3_frame(xing_frames=1000) + mpeg1_l3_frame()
        self.assertEqual(read_tags(self.file("a.mp3", data)).duration, 26)

    def test_mp3_duration_cbr_estimate(self):
        # 128 kbps: 16,000 bytes a second. 40 frames of 417 bytes ≈ 1 s.
        data = mpeg1_l3_frame() * 40
        self.assertEqual(read_tags(self.file("a.mp3", data)).duration, 1)

    def test_flac_tags_and_duration(self):
        data = flac(44100, 441000, [("TITLE", "Paranoid Android"), ("ARTIST", "Radiohead"),
                                    ("album", "OK Computer"), ("ALBUMARTIST", "Radiohead")])
        self.assertEqual(read_tags(self.file("a.flac", data)),
                         Tags("Paranoid Android", "Radiohead", "OK Computer", "Radiohead", 10))

    def test_flac_after_id3(self):
        data = id3v2(3, []) + flac(48000, 96000, [("TITLE", "T")])
        self.assertEqual((read_tags(self.file("a.flac", data)).title, read_tags(self.file("b.flac", data)).duration),
                         ("T", 2))

    def test_mp4_tags_and_duration(self):
        data = mp4("Everlong", "Foo Fighters", "The Colour and the Shape", "Foo Fighters", 44100, 44100 * 250)
        self.assertEqual(read_tags(self.file("a.m4a", data)),
                         Tags("Everlong", "Foo Fighters", "The Colour and the Shape", "Foo Fighters", 250))

    def test_ogg_vorbis_comments(self):
        data = ogg_vorbis(44100, 44100 * 180, [("TITLE", "Glycerine"), ("ARTIST", "Bush"), ("ALBUM", "Sixteen Stone")])
        self.assertEqual(read_tags(self.file("a.ogg", data)), Tags("Glycerine", "Bush", "Sixteen Stone", "", 180))

    def test_ogg_comment_across_segments(self):
        long_album = "x" * 600  # longer than one 255-byte segment
        data = ogg_vorbis(44100, 44100, [("TITLE", "T"), ("ALBUM", long_album)])
        self.assertEqual(read_tags(self.file("a.ogg", data)).album, long_album)

    def test_opus(self):
        data = ogg_opus(312, 312 + 48000 * 61, [("TITLE", "Opus Song"), ("ARTIST", "A")])
        self.assertEqual(read_tags(self.file("a.opus", data)), Tags("Opus Song", "A", "", "", 61))

    def test_asf_title_author(self):
        data = asf("Hey Jealousy", "Gin Blossoms", "New Miserable Experience", "Gin Blossoms", 236)
        self.assertEqual(read_tags(self.file("a.wma", data)),
                         Tags("Hey Jealousy", "Gin Blossoms", "New Miserable Experience", "Gin Blossoms", 236))

    def test_garbage_file_returns_empty_tags(self):
        for name, data in (("a.mp3", b"\0" * 50), ("b.flac", b"fLaC\x00\xff\xff"), ("c.m4a", b"\0\0\0\x08ftyp\xff"),
                           ("d.mp3", b"ID3\x04\0\0\x7f\x7f\x7f\x7f"), ("e.ogg", b"OggS" + b"\xff" * 40),
                           ("f.wma", uuid.UUID("75B22630-668E-11CF-A6D9-00AA0062CE6C").bytes_le + b"\xff" * 30),
                           ("g.mp3", b"")):
            self.assertEqual(read_tags(self.file(name, data)), Tags(), name)

    def test_missing_file_returns_empty_tags(self):
        self.assertEqual(read_tags(Path(self.tmp.name) / "none.mp3"), Tags())


if __name__ == "__main__":
    unittest.main()
