#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conservative IPTV playlist builder for the user's 41 requested channels.

Source of truth: iptv-org structured API (channels, feeds, streams).
A stream is published only if:
  1) the requested name/explicit alias resolves to exactly one channel ID;
  2) the stream record is attached to that channel ID;
  3) feed metadata supports Russian-language/Russian-area viewing;
  4) stream is not tagged Geo-blocked or Not 24/7;
  5) ffmpeg can decode a short video sample (not just HTTP 200 / HEAD);
  6) the URL is unique in the final playlist.

This still cannot prove editorial identity (e.g. distinguish a paywall slate
from the intended channel) without visual/EPG review. The report says so.
"""
from __future__ import annotations
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "channels.json"
OUT = ROOT / "favorites.m3u"
REPORT = ROOT / "update_report.txt"
API = "https://iptv-org.github.io/api"
UA = "Mozilla/5.0 (compatible; SKOCHE-IPTV-builder/4.0)"
TIMEOUT = 18
DECODE_SECONDS = 8
MINIMUM_TO_PUBLISH = int(os.environ.get("MINIMUM_TO_PUBLISH", "1"))
MAX_CANDIDATES_PER_CHANNEL = 8

def norm(value: str) -> str:
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(value.split())

def fetch_json(name: str):
    req = Request(f"{API}/{name}.json", headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"{name}.json returned unexpected data")
    return data

def is_ru_feed(channel: dict, feed: dict) -> bool:
    langs = set(feed.get("languages") or [])
    areas = set(feed.get("broadcast_area") or [])
    # Prefer Russian audio and a feed intended for Russia. A channel may be
    # internationally registered (e.g. Viasat) but still have a RU feed.
    return "rus" in langs and (
        "c/RU" in areas or "r/RU" in areas or channel.get("country") == "RU"
    )

def make_ffmpeg_command(stream: dict):
    headers = []
    if stream.get("user_agent"):
        headers.append(f"User-Agent: {stream['user_agent']}")
    else:
        headers.append(f"User-Agent: {UA}")
    if stream.get("referrer"):
        headers.append(f"Referer: {stream['referrer']}")
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-rw_timeout", str(TIMEOUT * 1_000_000),
        "-headers", "\r\n".join(headers) + "\r\n",
        "-i", stream["url"],
        "-t", str(DECODE_SECONDS),
        "-map", "0:v:0", "-an", "-sn",
        "-f", "null", "-"
    ]
    return cmd

def decode_video(stream: dict) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            make_ffmpeg_command(stream),
            capture_output=True, text=True, timeout=TIMEOUT + DECODE_SECONDS + 8
        )
        if proc.returncode == 0:
            return True, "decoded video sample"
        detail = (proc.stderr or "").strip().splitlines()
        return False, (detail[-1][:240] if detail else f"ffmpeg exit {proc.returncode}")
    except subprocess.TimeoutExpired:
        return False, "decode timeout"
    except Exception as exc:
        return False, str(exc)[:240]

def main() -> int:
    if not MANIFEST.exists():
        raise RuntimeError("channels.json is missing from repository root")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed; refusing to create an empty playlist")
    wanted = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(wanted) != 41:
        raise RuntimeError(f"Expected 41 channels in channels.json; found {len(wanted)}")

    print("Downloading iptv-org metadata...")
    channels = fetch_json("channels")
    feeds = fetch_json("feeds")
    streams = fetch_json("streams")
    by_id = {c["id"]: c for c in channels}
    feed_map = {(f.get("channel"), f.get("id")): f for f in feeds}

    name_index: dict[str, set[str]] = {}
    for channel in channels:
        for label in [channel.get("name", "")] + (channel.get("alt_names") or []):
            if label:
                name_index.setdefault(norm(label), set()).add(channel["id"])

    report = [
        "SKOCHE IPTV verification report",
        f"Generated UTC: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}",
        f"Requested channels: {len(wanted)}",
        "Stream test: ffmpeg decodes up to 8 seconds of video; this is stronger than HTTP/HEAD.",
        "LIMIT: successful decoding does NOT prove the picture is the requested channel or bypass a paid subscription.",
        "Timezone: feed timezone metadata is recorded per stream. EPG times should be converted by Televizo using the device timezone; M3U cannot safely force one timezone for every regional feed.",
        "",
    ]
    chosen = []
    used_urls = set()
    counters = {"mapped": 0, "decoded": 0, "unavailable": 0, "ambiguous": 0}

    for item in wanted:
        name = item["name"]
        aliases = [name] + item.get("aliases", [])
        ids = set()
        for alias in aliases:
            ids.update(name_index.get(norm(alias), set()))
        if len(ids) != 1:
            counters["ambiguous"] += 1
            report.append(f"NOT MAPPED/AMBIGUOUS | {name} | channel IDs: {','.join(sorted(ids)) or 'none'}")
            continue

        channel_id = next(iter(ids))
        channel = by_id[channel_id]
        counters["mapped"] += 1
        candidates = []
        for stream in streams:
            if stream.get("channel") != channel_id:
                continue
            url = (stream.get("url") or "").strip()
            if not url.startswith(("http://", "https://")) or url in used_urls:
                continue
            labels = set(stream.get("labels") or [])
            if labels.intersection({"Geo-blocked", "Not 24/7"}):
                continue
            feed = feed_map.get((channel_id, stream.get("feed")), {})
            if not is_ru_feed(channel, feed):
                continue
            # Ranking: Russian feed area, main feed, HTTPS, quality metadata.
            areas = set(feed.get("broadcast_area") or [])
            score = (
                4 * ("c/RU" in areas or "r/RU" in areas)
                + 2 * bool(feed.get("is_main"))
                + 1 * url.startswith("https://")
                + 1 * bool(stream.get("quality"))
            )
            candidates.append((score, stream, feed))
        candidates.sort(key=lambda x: x[0], reverse=True)

        selected = None
        failures = []
        for _, stream, feed in candidates[:MAX_CANDIDATES_PER_CHANNEL]:
            success, reason = decode_video(stream)
            if success:
                selected = (stream, feed)
                break
            failures.append(reason)
        if not selected:
            counters["unavailable"] += 1
            report.append(
                f"NO VERIFIED VIDEO | {name} | id={channel_id} | "
                f"RU-feed candidates={len(candidates)} | test={'; '.join(failures[:3]) or 'no eligible candidates'}"
            )
            continue

        stream, feed = selected
        url = stream["url"]
        if url in used_urls:
            counters["unavailable"] += 1
            report.append(f"DUPLICATE URL REJECTED | {name} | {url}")
            continue
        used_urls.add(url)
        counters["decoded"] += 1
        feed_id = stream.get("feed") or ""
        timezones = feed.get("timezones") or []
        quality = stream.get("quality") or feed.get("format") or "unspecified"
        chosen.append((name, channel_id, feed_id, timezones, quality, stream))
        report.append(
            f"VIDEO DECODE OK | {name} | channel={channel_id} | feed={feed_id or '-'} | "
            f"timezones={','.join(timezones) or 'not specified'} | quality={quality} | url={url}"
        )

    report += [
        "",
        "SUMMARY",
        f"Mapped IDs: {counters['mapped']}/41",
        f"Video samples decoded: {counters['decoded']}/41",
        f"Unmapped or ambiguous: {counters['ambiguous']}",
        f"No eligible/decodeable stream: {counters['unavailable']}",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    if len(chosen) < MINIMUM_TO_PUBLISH:
        raise RuntimeError(
            f"Only {len(chosen)} streams passed validation; minimum is {MINIMUM_TO_PUBLISH}. "
            "Existing favorites.m3u was NOT overwritten. See update_report.txt."
        )

    lines = ["#EXTM3U"]
    for name, channel_id, feed_id, timezones, quality, stream in chosen:
        # tvg-id remains the canonical channel ID for EPG matching.
        attrs = [f'tvg-id="{channel_id}"', f'tvg-name="{name}"', 'group-title="Россия"']
        lines.append("#EXTINF:-1 " + " ".join(attrs) + f",{name}")
        if stream.get("referrer"):
            lines.append(f'#EXTVLCOPT:http-referrer={stream["referrer"]}')
        if stream.get("user_agent"):
            lines.append(f'#EXTVLCOPT:http-user-agent={stream["user_agent"]}')
        lines.append(stream["url"])

    tmp = OUT.with_suffix(".m3u.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"Playlist updated: {len(chosen)}/41 streams passed video decode.")
    print("Open update_report.txt for each channel's status and feed timezone.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"FATAL: {error}", file=sys.stderr)
        sys.exit(1)
