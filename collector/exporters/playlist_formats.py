"""Playlist file formats. Each writer returns the file's text; export_playlist writes the files."""
import csv
import io
import json
import plistlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import __version__
from ..playlist import PathStyle, format_path, path_to_uri
from ..tracks import LocalTrack, Playlist, SourceTrack


@dataclass
class ExportItem:
    local: LocalTrack
    source: SourceTrack


Writer = Callable[[Playlist, list[ExportItem], Path, PathStyle], str]


@dataclass
class PlaylistFormat:
    key: str
    label: str
    ext: str
    write: Writer


def _label(t: LocalTrack) -> str:
    return f"{t.artist} - {t.title}"


def _length(t: LocalTrack) -> int:
    return t.duration or -1


def write_m3u8(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist.name}"]
    for it in items:
        lines.append(f"#EXTINF:{_length(it.local)},{_label(it.local)}")
        lines.append(format_path(it.local.path, folder, style))
    return "\n".join(lines) + "\n"


def write_pls(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    lines = ["[playlist]"]
    for n, it in enumerate(items, start=1):
        lines += [f"File{n}={format_path(it.local.path, folder, style)}",
                  f"Title{n}={_label(it.local)}",
                  f"Length{n}={_length(it.local)}"]
    lines += [f"NumberOfEntries={len(items)}", "Version=2"]
    return "\n".join(lines) + "\n"


def _xml(root: ET.Element) -> str:
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def write_xspf(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    root = ET.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
    ET.SubElement(root, "title").text = playlist.name
    if playlist.url:
        ET.SubElement(root, "info").text = playlist.url
    track_list = ET.SubElement(root, "trackList")
    for it in items:
        t = it.local
        track = ET.SubElement(track_list, "track")
        ET.SubElement(track, "location").text = path_to_uri(format_path(t.path, folder, style))
        ET.SubElement(track, "title").text = t.title
        ET.SubElement(track, "creator").text = t.artist
        if t.album:
            ET.SubElement(track, "album").text = t.album
        if t.duration:
            ET.SubElement(track, "duration").text = str(t.duration * 1000)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + _xml(root) + "\n"


def write_wpl(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    root = ET.Element("smil")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "meta", name="Generator", content=f"TheCollector {__version__}")
    ET.SubElement(head, "meta", name="ItemCount", content=str(len(items)))
    ET.SubElement(head, "title").text = playlist.name
    seq = ET.SubElement(ET.SubElement(root, "body"), "seq")
    for it in items:
        ET.SubElement(seq, "media", src=format_path(it.local.path, folder, style))
    return '<?wpl version="1.0"?>\n' + _xml(root) + "\n"


def write_itunes_xml(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    """An iTunes library XML holding one playlist. iTunes and the Music app only import absolute
    locations, so the path style is ignored here."""
    tracks, order = {}, []
    for n, it in enumerate(items, start=1):
        t = it.local
        entry = {"Track ID": n, "Name": t.title, "Artist": t.artist, "Track Type": "File",
                 "Location": path_to_uri(t.path)}
        if t.album:
            entry["Album"] = t.album
        if t.duration:
            entry["Total Time"] = t.duration * 1000
        tracks[str(n)] = entry
        order.append({"Track ID": n})
    plist = {
        "Major Version": 1, "Minor Version": 1, "Application Version": "12.0",
        "Date": datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None),
        "Features": 5, "Show Content Ratings": True,
        "Tracks": tracks,
        "Playlists": [{"Name": playlist.name, "Playlist ID": 1, "All Items": True, "Playlist Items": order}],
    }
    return plistlib.dumps(plist, sort_keys=False).decode("utf-8")


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def write_csv(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Title", "Artist", "Album", "Duration", "ISRC", "Path", "Source URL"])
    for it in items:
        t = it.local
        w.writerow([t.title, t.artist, t.album, _mmss(t.duration), it.source.isrc,
                    format_path(t.path, folder, style), it.source.url])
    return out.getvalue()


def write_json(playlist: Playlist, items: list[ExportItem], folder: Path, style: PathStyle) -> str:
    data = {
        "format": "thecollector-playlist", "version": 1,
        "name": playlist.name, "source": playlist.source, "source_url": playlist.url,
        "tracks": [{
            "title": it.local.title, "artist": it.local.artist, "album": it.local.album,
            "duration": it.local.duration, "path": format_path(it.local.path, folder, style),
            "isrc": it.source.isrc, "source_id": it.source.id, "source_url": it.source.url,
        } for it in items],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


PLAYLIST_FORMATS: dict[str, PlaylistFormat] = {f.key: f for f in (
    PlaylistFormat("m3u8", "M3U8 (UTF-8)", ".m3u8", write_m3u8),
    PlaylistFormat("m3u", "M3U", ".m3u", write_m3u8),
    PlaylistFormat("pls", "PLS", ".pls", write_pls),
    PlaylistFormat("xspf", "XSPF (XML)", ".xspf", write_xspf),
    PlaylistFormat("itunes_xml", "iTunes / Music XML", ".xml", write_itunes_xml),
    PlaylistFormat("wpl", "Windows Media Playlist", ".wpl", write_wpl),
    PlaylistFormat("csv", "CSV", ".csv", write_csv),
    PlaylistFormat("json", "JSON", ".json", write_json),
)}
