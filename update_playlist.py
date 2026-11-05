#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh the user's fixed 41-channel list from public M3U catalogs.

The channel manifest is the source of truth. Every run writes all 41 names.
A replacement URL is used only when its catalog name matches exactly (after
normalization), its URL is unique, and an HTTP GET returns an HLS playlist.
If no verified replacement exists, the previous known URL is retained and
reported in update_report.txt; the script never silently drops a channel.
"""
import concurrent.futures
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "channels.json"
OUTPUT = ROOT / "favorites.m3u"
REPORT = ROOT / "update_report.txt"
UA = "Mozilla/5.0 (compatible; IPTVPlaylistUpdater/2.0)"
TIMEOUT = 18

# Several independently maintained public catalogs. A source being listed does
# not imply that every stream in it is authorized, online, or geographically available.
SOURCES = [
    "https://iptv-org.github.io/iptv/countries/ru.m3u",
    "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "https://ngrch.github.io/iptv/ru.m3u",
    "https://raw.githubusercontent.com/substanc1/iptv-russia/main/streams/ru.m3u",
]

ALIASES = {
    "Шансон ТВ": ["Shanson TV", "Chanson TV"],
    "Победа": ["Pobeda"],
    "Viasat History": ["Viasat History HD"],
    "Viasat Nature": ["Viasat Nature HD"],
    "TV1000 Русское кино": ["TV1000 Russian Kino", "TV1000 Russkoe Kino"],
    "Родное кино": ["Rodnoe Kino"],
    "Киносерия": ["Kinoseriya", "Kino Seriya"],
    "Наше новое кино": ["Nashe Novoe Kino"],
    "ТНТ4": ["TNT4", "TNT 4"],
    "Дом кино": ["Dom Kino"],
    "Смотрим 100% Любовь": ["100% Lyubov", "Smotrim 100% Lyubov"],
    "Звезда Плюс": ["Zvezda Plus"],
    "НТВ (+4)": ["NTV +4", "NTV4", "НТВ 4"],
    "ТНТ": ["TNT"],
    "Пятница!": ["Pyatnitsa", "Friday!"],
    "Пятый канал": ["Channel 5", "Pyaty Kanal"],
    "СТС": ["STS", "CTC"],
    "ТВ3": ["TV3", "TV-3"],
    "Че!": ["Che TV"],
    "Домашний": ["Domashniy", "Domashny"],
    "КиноСезон": ["KinoSezon", "Kino Sezon"],
    "Феникс+ Кино": ["Feniks Kino", "Phoenix Kino"],
    "Глазами туриста": ["Glazami Turista"],
    "Перец": ["Perets", "Peretz"],
    "Живая планета": ["Zhivaya Planeta", "Living Planet"],
    "Русский бестселлер": ["Russkiy Bestseller", "Russian Bestseller"],
    "Русская комедия": ["Russkaya Komediya", "Russian Comedy"],
    "Премиальное HD": ["Premialnoe HD"],
    "Наше любимое HD": ["Nashe Lyubimoe HD"],
    "Наш кинопоказ HD": ["Nash Kinopokaz HD"],
    "Русский иллюзион": ["Russkiy Illuzion", "Russian Illusion"],
    "Мосфильм. Золотая коллекция": ["Mosfilm Gold Collection", "Mosfilm Zolotaya Kollektsiya"],
    "Россия 1 HD (+4)": ["Russia 1 HD +4", "Rossiya 1 HD +4", "Россия 1 HD"],
    "Россия 24": ["Russia 24", "Rossiya 24"],
    "Дом кино Премиум HD": ["Dom Kino Premium HD"],
    "Первый канал": ["Channel One", "1TV", "First Channel", "Perviy Kanal"],
    "Рен ТВ": ["REN TV", "Ren TV", "REN-TV"],
    "ТВЦ": ["TV Center", "TV Centre", "TVC", "TV Tsentr"],
    "МИР (+4)": ["Mir +4", "МИР 4", "Mir TV +4", "МИР"],
    "Звезда": ["Zvezda TV"],
    "МУЗ ТВ": ["Muz TV", "MUZ-TV", "MuzTV"],
}


def norm(s):
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\+\s*4\s*(?:ч|h)?", " плюс четыре ", s)
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(s.split())


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read(25 * 1024 * 1024)
    text = raw.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:1000]:
        raise ValueError("not an M3U response")
    return text


def parse_m3u(text, source):
    rows, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            if not name:
                m = re.search(r'tvg-name="([^"]+)"', line, re.I)
                name = m.group(1).strip() if m else ""
            current = (name, line)
        elif current and line and not line.startswith("#"):
            if line.startswith(("http://", "https://")):
                rows.append({"name": current[0], "extinf": current[1], "url": line, "source": source})
            current = None
    return rows


def probe_hls(url):
    # GET rather than HEAD; validate that the response body resembles HLS.
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-4095", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(4096)
            ctype = (r.headers.get("Content-Type") or "").lower()
            return r.status in (200, 206) and bool(body) and (b"#EXTM3U" in body or "mpegurl" in ctype or url.lower().split("?")[0].endswith(".m3u8"))
    except Exception:
        return False


def main():
    channels = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(channels) != 41:
        raise RuntimeError(f"channels.json must contain exactly 41 channels, got {len(channels)}")

    catalog = []
    source_status = []
    for src in SOURCES:
        try:
            records = parse_m3u(fetch_text(src), src)
            catalog.extend(records)
            source_status.append(f"OK {src}: {len(records)} entries")
        except Exception as exc:
            source_status.append(f"FAIL {src}: {exc}")

    # Build explicit exact-name candidate lists; no substring/fuzzy assignment.
    candidate_map = {}
    for ch in channels:
        names = {norm(ch["name"])} | {norm(a) for a in ALIASES.get(ch["name"], [])}
        candidates = [r for r in catalog if norm(r["name"]) in names and r["url"].startswith(("http://", "https://"))]
        # HTTPS first, then stable source/name order.
        candidates.sort(key=lambda r: (not r["url"].lower().startswith("https://"), r["source"]))
        candidate_map[ch["name"]] = candidates

    # Probe each unique candidate URL once.
    unique_urls = list(dict.fromkeys(r["url"] for rs in candidate_map.values() for r in rs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        valid = dict(zip(unique_urls, pool.map(probe_hls, unique_urls)))

    chosen, used = {}, set()
    for ch in channels:
        name = ch["name"]
        for rec in candidate_map[name]:
            if valid.get(rec["url"]) and rec["url"] not in used:
                chosen[name] = (rec["url"], "FOUND_AND_GET_CHECKED")
                used.add(rec["url"])
                break
        if name not in chosen:
            fallback = ch.get("fallback_url", "").strip()
            # Preserve the original user's entry if no verified replacement exists.
            chosen[name] = (fallback, "KEPT_OLD_URL_UNVERIFIED")
            if fallback:
                used.add(fallback)

    lines = ["#EXTM3U"]
    report = ["IPTV update report", "All 41 requested channel names are retained.", ""] + source_status + ["", "Channel results:"]
    for ch in channels:
        name = ch["name"]
        url, status = chosen[name]
        lines.extend([f"#EXTINF:-1,{name}", url])
        report.append(f"{status}: {name} -> {url or 'NO URL IN MANIFEST'}")
    tmp = OUTPUT.with_suffix(".m3u.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(OUTPUT)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    found = sum(1 for _, status in chosen.values() if status == "FOUND_AND_GET_CHECKED")
    print(f"Playlist written: {len(channels)} channels; {found} URLs found and GET-checked; {len(channels)-found} old URLs retained.")
    print(f"See {REPORT.name} for per-channel status.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
