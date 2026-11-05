#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
SOURCE_TIMEOUT = 35
STREAM_TIMEOUT = 7
MAX_WORKERS = 16

MY_FAVORITE_CHANNELS = [
    "Шансон ТВ", "Мосфильм. Золотая коллекция", "Победа", "Viasat History",
    "Viasat Nature", "TV1000 Русское кино", "Родное кино", "Киносерия",
    "Наше новое кино", "Россия 1 HD", "Россия 24", "ТНТ4",
    "Дом кино", "Смотрим 100% Любовь", "Звезда Плюс", "Первый канал",
    "НТВ", "Рен ТВ", "ТНТ", "Пятница!", "Пятый канал", "СТС", "ТВЦ",
    "ТВ3", "МИР", "Че!", "Домашний", "Звезда", "КиноСезон",
    "Феникс+ Кино", "Глазами туриста", "МУЗ ТВ",
    "Перец", "Живая планета", "Русский бестселлер", "Русская комедия",
    "Премиальное HD", "Наше любимое HD", "Наш кинопоказ HD", "Русский иллюзион",
    "Дом кино Премиум HD"
]

# Ручные варианты названий из международных M3U-баз.
ALIASES = {
    "Шансон ТВ": ["Shanson TV", "Chanson TV"],
    "Мосфильм. Золотая коллекция": ["Mosfilm Gold Collection", "Mosfilm Zolotaya Kollektsiya"],
    "Победа": ["Pobeda", "Victory TV"],
    "Viasat History": ["Viasat History"],
    "Viasat Nature": ["Viasat Nature"],
    "TV1000 Русское кино": ["TV1000 Russian Kino", "TV1000 Russkoe Kino"],
    "Родное кино": ["Rodnoe Kino"],
    "Киносерия": ["Kinoseriya", "Kino Seriya"],
    "Наше новое кино": ["Nashe Novoe Kino"],
    "Россия 1 HD": ["Russia 1", "Rossiya 1", "Russia 1 HD", "Rossiya 1 HD"],
    "Россия 24": ["Russia 24", "Rossiya 24"],
    "ТНТ4": ["TNT4", "TNT 4"],
    "Дом кино": ["Dom kino", "Dom Kino"],
    "Смотрим 100% Любовь": ["Smotrim 100% Lyubov", "100% Lyubov"],
    "Звезда Плюс": ["Zvezda Plus", "Star Plus"],
    "Первый канал": ["Channel One", "1TV", "First Channel", "Perviy Kanal"],
    "НТВ": ["NTV"],
    "Рен ТВ": ["REN TV", "Ren TV", "REN-TV"],
    "ТНТ": ["TNT"],
    "Пятница!": ["Friday!", "Friday", "Pyatnitsa"],
    "Пятый канал": ["Channel 5", "5 Channel", "Pyaty Kanal"],
    "СТС": ["STS", "CTC"],
    "ТВЦ": ["TV Center", "TV Centre", "TVC", "TV Tsentr"],
    "ТВ3": ["TV3", "TV-3"],
    "МИР": ["Mir", "Mir TV"],
    "Че!": ["Che", "Che TV"],
    "Домашний": ["Domashniy", "Domashny"],
    "Звезда": ["Zvezda"],
    "КиноСезон": ["KinoSezon", "Kino Sezon"],
    "Феникс+ Кино": ["Phoenix Kino", "Feniks Kino"],
    "Глазами туриста": ["Glazami Turista"],
    "МУЗ ТВ": ["Muz TV", "MUZ-TV", "MuzTV"],
    "Перец": ["Peretz", "Perets"],
    "Живая планета": ["Zhivaya Planeta", "Living Planet"],
    "Русский бестселлер": ["Russkiy Bestseller", "Russian Bestseller"],
    "Русская комедия": ["Russkaya Komediya", "Russian Comedy"],
    "Премиальное HD": ["Premialnoe HD", "Premium HD"],
    "Наше любимое HD": ["Nashe Lyubimoe HD"],
    "Наш кинопоказ HD": ["Nash Kinopokaz HD", "Kinopokaz"],
    "Русский иллюзион": ["Russkiy Illuzion", "Russian Illusion"],
    "Дом кино Премиум HD": ["Dom kino Premium", "Dom Kino Premium HD"],
}

QUALITY = {"hd", "fhd", "uhd", "4k", "hevc", "576p", "576i", "720p", "1080p", "2160p", "sd"}


def norm(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\+4\s*ч?|\+4h|красноярск", " ", s)
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in QUALITY).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT) as r:
        data = r.read()
    text = data.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:500]:
        raise ValueError("ответ не является M3U")
    return text


def parse(text, source):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    records, extinf, name = [], None, ""
    for line in lines:
        if line.startswith("#EXTINF"):
            extinf = line
            name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            m = re.search(r'tvg-name="([^"]+)"', line, re.I)
            if m and not name:
                name = m.group(1).strip()
        elif extinf and not line.startswith("#"):
            if line.startswith(("http://", "https://")):
                records.append({"name": name, "extinf": extinf, "url": line, "source": source})
                extinf, name = None, ""
    return records


def variants(fav):
    values = [fav] + ALIASES.get(fav, [])
    return {norm(v) for v in values if norm(v)}


def score(fav, channel):
    c = norm(channel)
    if not c:
        return 0
    best = 0
    for v in variants(fav):
        if c == v:
            best = max(best, 1.0)
        elif len(v) >= 5 and (v in c or c in v):
            best = max(best, 0.94)
    return best


def plus4(rec):
    s = (rec["name"] + " " + rec["extinf"]).lower()
    return any(x in s for x in ("+4", "(+4)", "+4ч", "+4h", "красноярск"))


def probe(url):
    # Проверка только диагностическая: некоторые серверы блокируют IP GitHub Actions.
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=STREAM_TIMEOUT) as r:
            return r.status in (200, 206)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def main():
    all_records = []
    good_sources = 0
    for source in SOURCES:
        print(f"\nЗагружаем: {source}")
        try:
            records = parse(fetch(source), source)
            if not records:
                raise ValueError("в M3U нет записей")
            all_records.extend(records)
            good_sources += 1
            print(f"  Записей: {len(records)}")
        except Exception as e:
            print(f"  Источник пропущен: {e}")

    if not good_sources:
        print("\nВсе источники недоступны. Старый плейлист оставлен без изменений.")
        return 2

    selected = {}
    for fav in MY_FAVORITE_CHANNELS:
        matches = [(score(fav, r["name"]), plus4(r), r) for r in all_records]
        matches = [x for x in matches if x[0] >= 0.94]
        if matches:
            matches.sort(key=lambda x: (x[0], x[1]), reverse=True)
            selected[fav] = matches[0][2]

    print(f"\nНайдено каналов: {len(selected)} из {len(MY_FAVORITE_CHANNELS)}")
    if not selected:
        print("Совпадений нет. Старый плейлист оставлен без изменений.")
        return 3

    # Проверка не является фильтром: GitHub Actions может быть заблокирован провайдером потока.
    urls = list(dict.fromkeys(r["url"] for r in selected.values()))
    statuses = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(probe, u): u for u in urls}
        for f in concurrent.futures.as_completed(futures):
            u = futures[f]
            try:
                statuses[u] = f.result()
            except Exception:
                statuses[u] = False

    confirmed = sum(statuses.values())
    print(f"Ответили на проверочный запрос с GitHub: {confirmed} из {len(urls)}")
    print("Неответившие не удаляются автоматически: сервер может блокировать GitHub Actions.")

    ordered = []
    for fav in MY_FAVORITE_CHANNELS:
        if fav in selected:
            rec = selected[fav]
            display = fav + (" (+4)" if plus4(rec) else "")
            ordered.append((not statuses.get(rec["url"], False), display, rec["url"]))

    # Подтверждённые потоки идут первыми, остальные сохраняются после них.
    ordered.sort(key=lambda x: (x[0], next(i for i, f in enumerate(MY_FAVORITE_CHANNELS) if f in x[1])))

    tmp = OUTPUT_FILE.with_suffix(".m3u.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        for _, name, url in ordered:
            f.write(f"#EXTINF:-1,{name}\n{url}\n")
    tmp.replace(OUTPUT_FILE)

    print(f"\nГОТОВО: записано {len(ordered)} каналов в {OUTPUT_FILE}.")
    print("Проверка GitHub не является гарантией воспроизведения в плеере.")
    return 0


if __name__ == "__main__":
    sys.exit(main())







