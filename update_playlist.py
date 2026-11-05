#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a conservative 41-channel M3U from iptv-org's structured database.

Important: HTTP/HLS checks prove that a stream responds, not that its pictures
are the requested channel. Therefore this script uses database channel IDs,
Russian broadcast metadata and unique URLs; ambiguous/unmapped channels are
written to the report and omitted from the playable list rather than assigned
a random/old stream.
"""
import concurrent.futures, json, re, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "channels.json"
OUT = ROOT / "favorites.m3u"
REPORT = ROOT / "update_report.txt"
API = "https://iptv-org.github.io/api"
TZ = "Asia/Barnaul"  # EPG times are UTC; Televizo should display device-local time.
UA = "Mozilla/5.0 (X11; Linux x86_64) IPTV-Playlist-Builder/3.0"
TIMEOUT = 15

def get_json(name):
    req = Request(f"{API}/{name}.json", headers={"User-Agent": UA})
    with urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))

def norm(s):
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(s.split())

def is_ru_channel(ch):
    return ch.get("country") == "RU" or any(x in ch.get("broadcast_area", []) for x in ("c/RU", "r/RU"))

def probe(url, referrer=None, user_agent=None):
    # ffprobe reads the HLS manifest and a short media sample. This is stronger
    # than HEAD/HTTP status, but cannot semantically identify the TV program.
    headers = [f"User-Agent: {user_agent or UA}"]
    if referrer:
        headers.append(f"Referer: {referrer}")
    cmd = ["ffprobe", "-v", "error", "-rw_timeout", str(TIMEOUT*1000000),
           "-headers", "\r\n".join(headers)+"\r\n",
           "-select_streams", "v:0", "-show_entries", "stream=codec_type",
           "-of", "default=nw=1", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT+8)
        return p.returncode == 0 and "codec_type=video" in p.stdout
    except Exception:
        return False

def main():
    wanted = json.loads(MANIFEST.read_text(encoding="utf-8"))
    channels = get_json("channels")
    streams = get_json("streams")
    feeds = get_json("feeds")
    by_id = {c["id"]: c for c in channels}
    feed_map = {(f.get("channel"), f.get("id")): f for f in feeds}
    names_to_ids = {}
    for c in channels:
        names = [c.get("name","")] + c.get("alt_names", [])
        for n in names:
            names_to_ids.setdefault(norm(n), set()).add(c["id"])

    lines = ["#EXTM3U"]
    report = [f"IPTV automatic audit | preferred viewer timezone: {TZ}",
              "EPG programme times are UTC-based; Televizo should use the device's automatic local timezone.",
              "A successful ffprobe confirms a video stream exists, not the channel's editorial identity.",
              ""]
    used_urls = set()
    ok = 0
    for item in wanted:
        name = item["name"]
        names = [name] + item.get("aliases", [])
        ids = set()
        for alias in names:
            ids |= names_to_ids.get(norm(alias), set())
        # Only uniquely resolved channel IDs are eligible. Never fuzzy-match.
        if len(ids) != 1:
            report.append(f"NOT MAPPED (0 or ambiguous database IDs): {name} | IDs={sorted(ids)}")
            continue
        cid = next(iter(ids))
        ch = by_id[cid]
        if ch.get("country") != "RU":
            report.append(f"NOT RUSSIAN CHANNEL RECORD: {name} | {cid} | country={ch.get('country')}")
            continue
        candidates = []
        for s in streams:
            if s.get("channel") != cid:
                continue
            url = s.get("url","")
            if not url.startswith("https://") or url in used_urls:
                continue
            feed = feed_map.get((cid, s.get("feed")), {})
            # Prefer Russian-language feed, then feed explicitly broadcast in RU.
            langs = feed.get("languages", [])
            areas = feed.get("broadcast_area", [])
            score = (2 if "rus" in langs else 0) + (2 if "c/RU" in areas or "r/RU" in areas else 0) + (1 if feed.get("is_main") else 0)
            candidates.append((score, s, feed))
        candidates.sort(key=lambda x: x[0], reverse=True)
        selected = None
        for score, s, feed in candidates[:5]:
            if probe(s["url"], s.get("referrer"), s.get("user_agent")):
                selected = (s, feed, score)
                break
        if not selected:
            report.append(f"NO VERIFIED VIDEO STREAM: {name} | {cid} | candidates={len(candidates)}")
            continue
        s, feed, score = selected
        used_urls.add(s["url"])
        feed_id = s.get("feed") or ""
        tvg_id = f"{cid}@{feed_id}" if feed_id else cid
        feed_tz = ",".join(feed.get("timezones", [])) or "not specified"
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="Россия",{name}')
        # Preserve required headers for players that honor VLC options.
        if s.get("referrer"):
            lines.append(f'#EXTVLCOPT:http-referrer={s["referrer"]}')
        if s.get("user_agent"):
            lines.append(f'#EXTVLCOPT:http-user-agent={s["user_agent"]}')
        lines.append(s["url"])
        ok += 1
        report.append(f"VIDEO STREAM OK: {name} | {cid} | feed={feed_id or '-'} | feed_timezone={feed_tz} | url={s['url']}")
    tmp = OUT.with_suffix(".m3u.tmp")
    tmp.write_text("\n".join(lines)+"\n", encoding="utf-8")
    tmp.replace(OUT)
    REPORT.write_text("\n".join(report)+"\n", encoding="utf-8")
    print(f"Published {ok}/{len(wanted)} streams with a verified video track. See update_report.txt.")
    print("Unverified channels are deliberately excluded, never filled with another channel's stream.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
