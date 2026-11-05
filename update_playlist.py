#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build favorites.m3u from public M3U catalogs without duplicate stream URLs."""
import concurrent.futures
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = [
    "https://iptv-org.github.io/iptv/countries/ru.m3u",
    "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ru.m3u",
]
OUTPUT_FILE = Path("favorites.m3u")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
SOURCE_TIMEOUT = 45
STREAM_TIMEOUT = 10
MAX_WORKERS = 16
MIN_CHANNELS = 8  # Never replace the existing playlist with a tiny/partial result.

# Canonical names retained from the user's 41-channel selection.
CHANNELS = [
    "Шансон ТВ", "Мосфильм. Золотая коллекция", "Победа", "Viasat History",
    "Viasat Nature", "TV1000 Русское кино", "Родное кино", "Киносерия",
    "Наше новое кино", "Россия 1 HD", "Россия 24", "ТНТ4", "Дом кино",
    "Смотрим 100% Любовь", "Звезда Плюс", "Первый канал", "НТВ", "Рен ТВ",
    "ТНТ", "Пятница!", "Пятый канал", "СТС", "ТВЦ", "ТВ3", "МИР",
    "Че!", "Домашний", "Звезда", "КиноСезон", "Феникс+ Кино",
    "Глазами туриста", "МУЗ ТВ", "Перец", "Живая планета",
    "Русский бестселлер", "Русская комедия", "Премиальное HD",
    "Наше любимое HD", "Наш кинопоказ HD", "Русский иллюзион",
    "Дом кино Премиум HD",
]

# Only explicit spelling variants. No fuzzy/substring matching: it can assign a
# similarly named but different TV channel to a favorite.
ALIASES = {
    "Шансон ТВ": ["Shanson TV", "Chanson TV"],
    "Мосфильм. Золотая коллекция": ["Mosfilm Gold Collection", "Mosfilm Zolotaya Kollektsiya"],
    "Победа": ["Pobeda", "Victory TV"],
    "TV1000 Русское кино": ["TV1000 Russian Kino", "TV1000 Russkoe Kino"],
    "Родное кино": ["Rodnoe Kino"], "Киносерия": ["Kinoseriya", "Kino Seriya"],
    "Наше новое кино": ["Nashe Novoe Kino"],
    "Россия 1 HD": ["Russia 1 HD", "Rossiya 1 HD", "Россия 1", "Russia 1", "Rossiya 1"],
    "Россия 24": ["Russia 24", "Rossiya 24"], "ТНТ4": ["TNT4", "TNT 4"],
    "Дом кино": ["Dom kino", "Dom Kino"],
    "Смотрим 100% Любовь": ["Smotrim 100% Lyubov", "100% Lyubov"],
    "Звезда Плюс": ["Zvezda Plus"], "Первый канал": ["Channel One", "1TV", "First Channel", "Perviy Kanal"],
    "НТВ": ["NTV"], "Рен ТВ": ["REN TV", "Ren TV", "REN-TV"], "ТНТ": ["TNT"],
    "Пятница!": ["Pyatnitsa", "Friday!"], "Пятый канал": ["Channel 5", "Pyaty Kanal"],
    "СТС": ["STS", "CTC"], "ТВЦ": ["TV Center", "TV Centre", "TVC", "TV Tsentr"],
    "ТВ3": ["TV3", "TV-3"], "МИР": ["Mir TV"], "Че!": ["Che TV"],
    "Домашний": ["Domashniy", "Domashny"], "Звезда": ["Zvezda TV"],
    "КиноСезон": ["KinoSezon", "Kino Sezon"], "Феникс+ Кино": ["Feniks Kino"],
    "Глазами туриста": ["Glazami Turista"], "МУЗ ТВ": ["Muz TV", "MUZ-TV", "MuzTV"],
    "Перец": ["Peretz", "Perets"], "Живая планета": ["Zhivaya Planeta", "Living Planet"],
    "Русский бестселлер": ["Russkiy Bestseller", "Russian Bestseller"],
    "Русская комедия": ["Russkaya Komediya", "Russian Comedy"],
    "Премиальное HD": ["Premialnoe HD"], "Наше любимое HD": ["Nashe Lyubimoe HD"],
    "Наш кинопоказ HD": ["Nash Kinopokaz HD"], "Русский иллюзион": ["Russkiy Illuzion", "Russian Illusion"],
    "Дом кино Премиум HD": ["Dom Kino Premium HD", "Dom kino Premium"],
}
QUALITY = {"hd", "fhd", "uhd", "4k", "hevc", "576p", "576i", "720p", "1080p", "2160p", "sd"}


def norm(value):
    value = value.lower().replace("ё", "е")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\+4\s*ч?|\+4h|красноярск", " ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(w for w in value.split() if w not in QUALITY).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT) as response:
        body = response.read()
    text = body.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:500]:
        raise ValueError("ответ не является M3U")
    return text


def parse(text, source):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records, extinf, name = [], None, ""
    for line in lines:
        if line.startswith("#EXTINF"):
            extinf = line
            name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            if not name:
                match = re.search(r'tvg-name="([^"]+)"', line, re.I)
                name = match.group(1).strip() if match else ""
        elif extinf and not line.startswith("#"):
            if line.startswith(("http://", "https://")):
                records.append({"name": name, "extinf": extinf, "url": line, "source": source})
            extinf, name = None, ""
    return records


def aliases_for(channel):
    return {norm(x) for x in [channel, *ALIASES.get(channel, [])] if norm(x)}


def exact_match(channel, record):
    candidate = norm(record["name"])
    return bool(candidate) and candidate in aliases_for(channel)


def is_plus4(record):
    value = (record["name"] + " " + record["extinf"]).lower()
    return any(token in value for token in ("+4", "+4ч", "+4h", "красноярск"))


def probe(url):
    # GET with a small byte range: many HLS servers reject HEAD requests.
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=STREAM_TIMEOUT) as response:
            data = response.read(1024)
            content_type = response.headers.get("Content-Type", "").lower()
            return response.status in (200, 206) and bool(data) and ("mpegurl" in content_type or b"#EXTM3U" in data or url.lower().endswith(".m3u8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def main():
    all_records = []
    for source in SOURCES:
        print(f"\nЗагружаем: {source}")
        try:
            records = parse(fetch(source), source)
            if not records:
                raise ValueError("в M3U нет записей")
            all_records.extend(records)
            print(f"  Записей: {len(records)}")
        except Exception as error:
            print(f"  Источник пропущен: {error}")

    if not all_records:
        print("Источники недоступны. Старый favorites.m3u не изменён.")
        return 2

    # For each favorite, accept only exact canonical/alias name matches.
    selected, used_urls = {}, set()
    for channel in CHANNELS:
        candidates = [r for r in all_records if exact_match(channel, r)]
        # Prefer non-regional streams and HTTPS. Never reuse a URL for another channel.
        candidates.sort(key=lambda r: (is_plus4(r), not r["url"].lower().startswith("https://")))
        for record in candidates:
            if record["url"] not in used_urls:
                selected[channel] = record
                used_urls.add(record["url"])
                break

    print(f"\nУникальных совпадений по названию: {len(selected)} из {len(CHANNELS)}")
    if len(selected) < MIN_CHANNELS:
        print(f"Найдено меньше {MIN_CHANNELS}; старый favorites.m3u сохранён.")
        return 3

    # Probe streams, but do not treat GitHub's network restrictions as definitive
    # proof that a stream is dead. Keep only candidates whose GET probe succeeds
    # when enough streams pass; otherwise preserve the old playlist.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        checks = dict(zip(selected, pool.map(probe, [r["url"] for r in selected.values()])))
    working = [channel for channel in CHANNELS if channel in selected and checks.get(channel)]
    print(f"GET-проверку прошли: {len(working)}")
    if len(working) < MIN_CHANNELS:
        print("Слишком мало проверенных потоков; старый favorites.m3u сохранён.")
        return 4

    tmp = OUTPUT_FILE.with_suffix(".m3u.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as output:
        output.write("#EXTM3U\n")
        for channel in CHANNELS:
            if channel in selected and checks.get(channel):
                record = selected[channel]
                display = channel + (" (+4)" if is_plus4(record) else "")
                output.write(f"#EXTINF:-1,{display}\n{record['url']}\n")
    tmp.replace(OUTPUT_FILE)
    print(f"Готово: записано {len(working)} уникальных каналов.")
    return 0


if __name__ == "__main__":
    sys.exit(main())








