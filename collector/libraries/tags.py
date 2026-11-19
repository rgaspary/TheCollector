"""Read title, artist, album and duration from music files, with the standard library only.

Supported: MP3 (ID3v2.2/2.3/2.4, ID3v1), FLAC, MP4/M4A, Ogg Vorbis, Ogg Opus, WMA/ASF.
The format is picked from the file's first bytes, not its extension. Anything unreadable gives
empty Tags; read_tags never raises.
"""
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

MAX_TAG_BYTES = 16 * 1024 * 1024   # tags bigger than this (huge cover art) are skipped
MAX_ATOM_BYTES = 64 * 1024 * 1024


@dataclass
class Tags:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    duration: int = 0  # seconds


def read_tags(path: Path) -> Tags:
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            f.seek(0)
            if head.startswith(b"ID3"):
                return _id3_file(f, path)
            if head.startswith(b"fLaC"):
                return _flac(f, 0)
            if head[4:8] == b"ftyp":
                return _mp4(f, path.stat().st_size)
            if head.startswith(b"OggS"):
                return _ogg(f, path.stat().st_size)
            if head == _ASF_HEADER:
                return _asf(f)
            if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
                return _mp3(f, path.stat().st_size, 0, Tags())
    except Exception:  # any broken file: no tags rather than a failed scan
        pass
    return Tags()


def _round(seconds: float) -> int:
    return max(0, int(seconds + 0.5))


def _join(values: list[str]) -> str:
    return ", ".join(v for v in (s.strip() for s in values) if v)


# ---- ID3 / MP3 -------------------------------------------------------------------------------
_ID3_KEYS = {
    "TIT2": "title", "TPE1": "artist", "TALB": "album", "TPE2": "album_artist", "TLEN": "length",
    "TT2": "title", "TP1": "artist", "TAL": "album", "TP2": "album_artist", "TLE": "length",
}


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _unsync(data: bytes) -> bytes:
    return data.replace(b"\xff\x00", b"\xff")


def _id3_text(data: bytes) -> str:
    if not data:
        return ""
    enc, raw = data[0], data[1:]
    if enc == 0:
        text = raw.decode("latin-1")
    elif enc == 1:
        text = raw.decode("utf-16")
    elif enc == 2:
        text = raw.decode("utf-16-be")
    else:
        text = raw.decode("utf-8", "replace")
    return _join(text.split("\0"))


def _parse_id3v2(tag: bytes) -> tuple[dict[str, str], int]:
    """Frames from a whole ID3v2 tag (header included) and the tag's total length."""
    major, flags = tag[3], tag[5]
    size = _syncsafe(tag[6:10])
    body = tag[10:10 + size]
    if flags & 0x80 and major < 4:
        body = _unsync(body)
    pos = 0
    if flags & 0x40:  # extended header
        ext = _syncsafe(body[0:4]) if major == 4 else int.from_bytes(body[0:4], "big") + 4
        pos = ext
    frames: dict[str, str] = {}
    id_len, head_len = (3, 6) if major == 2 else (4, 10)
    while pos + head_len <= len(body):
        fid = body[pos:pos + id_len]
        if not fid.strip(b"\0") or not fid.isalnum():
            break
        if major == 2:
            fsize = int.from_bytes(body[pos + 3:pos + 6], "big")
            fflags = 0
        elif major == 4:
            fsize = _syncsafe(body[pos + 4:pos + 8])
            fflags = body[pos + 9]
        else:
            fsize = int.from_bytes(body[pos + 4:pos + 8], "big")
            fflags = 0
        data = body[pos + head_len:pos + head_len + fsize]
        pos += head_len + fsize
        if major == 4:
            if fflags & 0x01:  # data length indicator
                data = data[4:]
            if fflags & 0x02 or flags & 0x80:
                data = _unsync(data)
        key = _ID3_KEYS.get(fid.decode("latin-1"))
        if key and key not in frames:
            frames[key] = _id3_text(data)
    footer = 10 if major == 4 and flags & 0x10 else 0
    return frames, 10 + size + footer


def _id3_file(f: BinaryIO, path: Path) -> Tags:
    header = f.read(10)
    size = _syncsafe(header[6:10])
    if size > MAX_TAG_BYTES:
        frames, tag_len = {}, 10 + size
    else:
        frames, tag_len = _parse_id3v2(header + f.read(size + 10))
    f.seek(tag_len)
    if f.read(4) == b"fLaC":
        return _flac(f, tag_len)
    length = frames.get("length", "")
    tags = Tags(frames.get("title", ""), frames.get("artist", ""), frames.get("album", ""),
                frames.get("album_artist", ""),
                _round(int(length) / 1000) if length.isdigit() else 0)
    return _mp3(f, path.stat().st_size, tag_len, tags)


_BITRATES = {
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_SAMPLE_RATES = {1: [44100, 48000, 32000], 2: [22050, 24000, 16000], 25: [11025, 12000, 8000]}


def _mpeg_header(b: bytes) -> tuple[int, int, int, int, bool] | None:
    """(version, layer, bitrate kbps, sample rate, mono) for a valid MPEG audio frame header."""
    if len(b) < 4 or b[0] != 0xFF or b[1] & 0xE0 != 0xE0:
        return None
    version = {3: 1, 2: 2, 0: 25}.get((b[1] >> 3) & 3)
    layer = {3: 1, 2: 2, 1: 3}.get((b[1] >> 1) & 3)
    bitrate_index, rate_index = b[2] >> 4, (b[2] >> 2) & 3
    if not version or not layer or bitrate_index in (0, 15) or rate_index == 3:
        return None
    bitrate = _BITRATES[(1 if version == 1 else 2, layer)][bitrate_index]
    return version, layer, bitrate, _SAMPLE_RATES[version][rate_index], (b[3] >> 6) == 3


def _mp3(f: BinaryIO, file_size: int, audio_start: int, tags: Tags) -> Tags:
    v1 = _id3v1(f, file_size)
    audio_end = file_size - (128 if v1 else 0)
    f.seek(audio_start)
    window = f.read(64 * 1024)
    for i in range(len(window) - 4):
        if window[i] != 0xFF:
            continue
        header = _mpeg_header(window[i:i + 4])
        if not header:
            continue
        version, layer, bitrate, rate, mono = header
        samples = 384 if layer == 1 else (1152 if layer == 2 or version == 1 else 576)
        side = (17 if mono else 32) if version == 1 else (9 if mono else 17)
        frame = window[i:i + 200]
        frames = 0
        xing = frame[4 + side:4 + side + 12]
        if xing[:4] in (b"Xing", b"Info") and int.from_bytes(xing[4:8], "big") & 1:
            frames = int.from_bytes(xing[8:12], "big")
        elif frame[36:40] == b"VBRI":
            frames = int.from_bytes(frame[50:54], "big")
        if not tags.duration:
            if frames:
                tags.duration = _round(frames * samples / rate)
            else:  # constant bit rate: size ÷ rate
                tags.duration = _round((audio_end - (audio_start + i)) * 8 / (bitrate * 1000))
        break
    if v1:
        tags.title = tags.title or v1.title
        tags.artist = tags.artist or v1.artist
        tags.album = tags.album or v1.album
    return tags


def _id3v1(f: BinaryIO, file_size: int) -> Tags | None:
    if file_size < 128:
        return None
    f.seek(file_size - 128)
    block = f.read(128)
    if not block.startswith(b"TAG"):
        return None

    def text(raw: bytes) -> str:
        return raw.split(b"\0")[0].decode("latin-1").strip()
    return Tags(text(block[3:33]), text(block[33:63]), text(block[63:93]))


# ---- Vorbis comments (FLAC, Ogg) -------------------------------------------------------------
def _vorbis_comments(data: bytes) -> dict[str, list[str]]:
    pos = 4 + int.from_bytes(data[0:4], "little")
    count = int.from_bytes(data[pos:pos + 4], "little")
    pos += 4
    out: dict[str, list[str]] = {}
    for _ in range(count):
        n = int.from_bytes(data[pos:pos + 4], "little")
        entry = data[pos + 4:pos + 4 + n].decode("utf-8", "replace")
        pos += 4 + n
        key, _, value = entry.partition("=")
        out.setdefault(key.upper(), []).append(value)
    return out


def _from_comments(c: dict[str, list[str]], duration: int) -> Tags:
    return Tags(_join(c.get("TITLE", [])), _join(c.get("ARTIST", [])), _join(c.get("ALBUM", [])),
                _join(c.get("ALBUMARTIST", []) or c.get("ALBUM ARTIST", [])), duration)


def _flac(f: BinaryIO, start: int) -> Tags:
    f.seek(start + 4)
    comments: dict[str, list[str]] = {}
    duration = 0
    while True:
        header = f.read(4)
        if len(header) < 4:
            break
        last, kind, size = header[0] & 0x80, header[0] & 0x7F, int.from_bytes(header[1:4], "big")
        if kind == 0:
            info = f.read(size)
            packed = int.from_bytes(info[10:18], "big")
            rate, total = packed >> 44, packed & 0xFFFFFFFFF
            duration = _round(total / rate) if rate else 0
        elif kind == 4:
            comments = _vorbis_comments(f.read(size))
        else:
            f.seek(size, 1)
        if last:
            break
    return _from_comments(comments, duration)


def _ogg_packets(f: BinaryIO, wanted: int) -> list[bytes]:
    """The first `wanted` packets of the first logical stream."""
    packets, current = [], b""
    while len(packets) < wanted:
        header = f.read(27)
        if len(header) < 27 or not header.startswith(b"OggS"):
            break
        lacing = f.read(header[26])
        for seg in lacing:
            current += f.read(seg)
            if seg < 255:
                packets.append(current)
                current = b""
                if len(packets) >= wanted:
                    break
        if len(current) > MAX_TAG_BYTES:
            break
    return packets


def _ogg_last_granule(f: BinaryIO, file_size: int) -> int:
    f.seek(max(0, file_size - 65536))
    tail = f.read()
    at = tail.rfind(b"OggS")
    if at < 0 or len(tail) < at + 14:
        return 0
    return int.from_bytes(tail[at + 6:at + 14], "little", signed=True)


def _ogg(f: BinaryIO, file_size: int) -> Tags:
    packets = _ogg_packets(f, 2)
    if len(packets) < 2:
        return Tags()
    first, second = packets
    granule = _ogg_last_granule(f, file_size)
    if first.startswith(b"\x01vorbis") and second.startswith(b"\x03vorbis"):
        rate = int.from_bytes(first[12:16], "little")
        return _from_comments(_vorbis_comments(second[7:]), _round(granule / rate) if rate and granule > 0 else 0)
    if first.startswith(b"OpusHead") and second.startswith(b"OpusTags"):
        pre_skip = int.from_bytes(first[10:12], "little")
        return _from_comments(_vorbis_comments(second[8:]), _round((granule - pre_skip) / 48000) if granule > 0 else 0)
    return Tags()


# ---- MP4 / M4A -------------------------------------------------------------------------------
def _atoms(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
        head = 8
        if size == 1:
            size, head = int.from_bytes(data[pos + 8:pos + 16], "big"), 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield kind, pos + head, pos + size
        pos += size


def _mp4(f: BinaryIO, file_size: int) -> Tags:
    pos, moov = 0, b""
    while pos + 8 <= file_size:  # top-level atoms; mdat can be huge, so seek past it
        f.seek(pos)
        header = f.read(16)
        size, kind = int.from_bytes(header[0:4], "big"), header[4:8]
        if size == 1:
            size = int.from_bytes(header[8:16], "big")
        elif size == 0:
            size = file_size - pos
        if size < 8:
            return Tags()
        if kind == b"moov":
            if size > MAX_ATOM_BYTES:
                return Tags()
            f.seek(pos)
            moov = f.read(size)
            break
        pos += size
    if not moov:
        return Tags()
    tags = Tags()
    for kind, start, end in _atoms(moov, 8):
        if kind == b"mvhd":
            version = moov[start]
            if version == 1:
                scale = int.from_bytes(moov[start + 20:start + 24], "big")
                length = int.from_bytes(moov[start + 24:start + 32], "big")
            else:
                scale = int.from_bytes(moov[start + 12:start + 16], "big")
                length = int.from_bytes(moov[start + 16:start + 20], "big")
            tags.duration = _round(length / scale) if scale else 0
        elif kind == b"udta":
            for k2, s2, e2 in _atoms(moov, start, end):
                if k2 != b"meta":
                    continue
                inner = s2 if moov[s2 + 4:s2 + 8] == b"hdlr" else s2 + 4  # QuickTime meta has no version field
                for k3, s3, e3 in _atoms(moov, inner, e2):
                    if k3 == b"ilst":
                        _ilst(moov, s3, e3, tags)
    return tags


_ILST_KEYS = {b"\xa9nam": "title", b"\xa9ART": "artist", b"\xa9alb": "album", b"aART": "album_artist"}


def _ilst(data: bytes, start: int, end: int, tags: Tags) -> None:
    for kind, s, e in _atoms(data, start, end):
        field = _ILST_KEYS.get(kind)
        if not field:
            continue
        for k2, s2, e2 in _atoms(data, s, e):
            if k2 == b"data" and int.from_bytes(data[s2:s2 + 4], "big") & 0xFFFFFF == 1:
                setattr(tags, field, data[s2 + 8:e2].decode("utf-8", "replace").strip())
                break


# ---- ASF / WMA -------------------------------------------------------------------------------
def _guid(text: str) -> bytes:
    return uuid.UUID(text).bytes_le


_ASF_HEADER = _guid("75B22630-668E-11CF-A6D9-00AA0062CE6C")
_ASF_FILE_PROPERTIES = _guid("8CABDCA1-A947-11CF-8EE4-00C00C205365")
_ASF_CONTENT = _guid("75B22633-668E-11CF-A6D9-00AA0062CE6C")
_ASF_EXTENDED = _guid("D2D0A440-E307-11D2-97F0-00A0C95EA850")


def _utf16(raw: bytes) -> str:
    return raw.decode("utf-16-le", "replace").split("\0")[0].strip()


def _asf(f: BinaryIO) -> Tags:
    header = f.read(30)
    size = int.from_bytes(header[16:24], "little")
    if size > MAX_TAG_BYTES or size < 30:
        return Tags()
    data = f.read(size - 30)
    tags, pos = Tags(), 0
    while pos + 24 <= len(data):
        guid, osize = data[pos:pos + 16], int.from_bytes(data[pos + 16:pos + 24], "little")
        if osize < 24:
            break
        body = data[pos + 24:pos + osize]
        if guid == _ASF_FILE_PROPERTIES and len(body) >= 80:
            play = int.from_bytes(body[40:48], "little")
            preroll = int.from_bytes(body[56:64], "little")
            tags.duration = _round(play / 10_000_000 - preroll / 1000)
        elif guid == _ASF_CONTENT:
            lengths = struct.unpack("<5H", body[:10])
            at = 10
            tags.title = _utf16(body[at:at + lengths[0]])
            at += lengths[0]
            tags.artist = _utf16(body[at:at + lengths[1]])
        elif guid == _ASF_EXTENDED:
            count, at = int.from_bytes(body[:2], "little"), 2
            for _ in range(count):
                nlen = int.from_bytes(body[at:at + 2], "little")
                name = _utf16(body[at + 2:at + 2 + nlen])
                at += 2 + nlen
                vtype, vlen = struct.unpack("<HH", body[at:at + 4])
                value = body[at + 4:at + 4 + vlen]
                at += 4 + vlen
                if vtype == 0 and name == "WM/AlbumTitle":
                    tags.album = _utf16(value)
                elif vtype == 0 and name == "WM/AlbumArtist":
                    tags.album_artist = _utf16(value)
        pos += osize
    return tags
