#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Собирает избранные каналы из публичных M3U-плейлистов,
проверяет доступность потоков через GET и создаёт favorites.m3u.

Важно:
- Если источники недоступны, файл не перезаписывается.
- Если найдено слишком мало рабочих каналов, старый файл сохраняется.
- Проверка GET подтверждает доступность HTTP-ответа, но не гарантирует,
  что конкретный плеер сможет декодировать видео.
"""

import concurrent.futures
import difflib
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = [
    "https://iptv-org.github.io/iptv/countries/ru.m3u",
    "https://iptv-org.github.io/iptv/languages/rus.m3u",
]

OUTPUT_FILE = Path("favorites.m3u")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IPTVPlaylistUpdater/1.0"
SOURCE_TIMEOUT = 30
STREAM_TIMEOUT = 8
MAX_WORKERS = 20

# Защита от публикации почти пустого плейлиста при массовом сбое потоков.
MIN_WORKING_CHANNELS = 5

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

# Дополнительные варианты написания. Ключ и значения будут нормализованы.
ALIASES = {
    "Россия 1 HD": ["Россия 1", "Россия-1"],
    "Рен ТВ": ["РЕН ТВ", "REN TV"],
    "ТВЦ": ["ТВ Центр", "ТВЦ"],
    "ТВ3": ["ТВ-3", "TV3"],
    "МИР": ["МИР 24", "МИР"],
    "Че!": ["Че", "Че ТВ"],
    "Мосфильм. Золотая коллекция": ["Мосфильм Золотая коллекция", "Mosfilm Gold Collection"],
    "Смотрим 100% Любовь": ["100% Любовь", "Смотрим 100 Любовь"],
    "Премиальное HD": ["Премиальное", "Премиум HD"],
    "Наш кинопоказ HD": ["Наш Кинопоказ", "Кинопоказ HD"],
    "Дом кино Премиум HD": ["Дом кино Премиум", "Дом кино Premium"],
}

QUALITY_WORDS = {
    "hd", "fhd", "uhd", "4k", "hevc", "авторский", "резерв", "backup"
}


def normalize(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\+4\s*ч?|\+4h|красноярск", " ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    words = [w for w in value.split() if w not in QUALITY_WORDS]
    return " ".join(words).strip()


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=SOURCE_TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        data = response.read()
    text = data.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:500]:
        raise RuntimeError("ответ не похож на M3U-плейлист")
    return text


def parse_m3u(text: str, source: str):
    """Возвращает записи, учитывая комментарии и дополнительные строки между тегом и URL."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    current_extinf = None
    current_name = None
    records = []

    for line in lines:
        if line.startswith("#EXTINF"):
            current_extinf = line
            current_name = line.rsplit(",", 1)[-1].strip() if "," in line else ""

            # Если есть tvg-name, используем его как дополнительный вариант имени.
            tvg_match = re.search(r'tvg-name="([^"]+)"', line, flags=re.IGNORECASE)
            if tvg_match and not current_name:
                current_name = tvg_match.group(1).strip()

        elif current_extinf and not line.startswith("#"):
            if line.startswith(("http://", "https://")):
                records.append({
                    "extinf": current_extinf,
                    "name": current_name or "",
                    "url": line,
                    "source": source,
                })
                current_extinf = None
                current_name = None

    return records


def favorite_variants(favorite: str):
    variants = [favorite]
    variants.extend(ALIASES.get(favorite, []))
    return list(dict.fromkeys(normalize(v) for v in variants if normalize(v)))


def match_score(favorite: str, channel_name: str) -> float:
    wanted_variants = favorite_variants(favorite)
    candidate = normalize(channel_name)

    if not candidate:
        return 0.0

    best = 0.0
    for wanted in wanted_variants:
        if candidate == wanted:
            score = 1.0
        elif wanted in candidate or candidate in wanted:
            # Не считаем слишком короткие совпадения достаточными.
            shorter = min(len(wanted), len(candidate))
            score = 0.94 if shorter >= 5 else 0.0
        else:
            score = difflib.SequenceMatcher(None, wanted, candidate).ratio()

        # Не даём случайным коротким совпадениям пройти фильтр.
        if min(len(wanted), len(candidate)) < 5 and wanted != candidate:
            score = 0.0
        best = max(best, score)

    return best


def is_plus_four(record) -> bool:
    text = (record["name"] + " " + record["extinf"]).lower()
    return any(marker in text for marker in ("+4", "(+4)", "+4ч", "+4h", "красноярск"))


def check_stream(url: str) -> bool:
    """GET с Range вместо HEAD: многие IPTV-серверы не поддерживают HEAD."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Range": "bytes=0-2047",
            "Accept": "*/*",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=STREAM_TIMEOUT) as response:
            status_ok = response.status in (200, 206)
            # Читаем небольшой фрагмент и закрываем соединение.
            chunk = response.read(2048)
            return status_ok and bool(chunk)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def choose_candidates(records):
    """Для каждого избранного канала выбирает лучшее совпадение."""
    selected = {}
    for favorite in MY_FAVORITE_CHANNELS:
        candidates = []
        for record in records:
            score = match_score(favorite, record["name"])
            if score >= 0.82:
                # При равном совпадении предпочитаем вариант +4.
                candidates.append((score, is_plus_four(record), record))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            selected[favorite] = candidates[0][2]

    return selected


def make_output_name(favorite: str, record) -> str:
    return favorite + (" (+4)" if is_plus_four(record) else "")


def main():
    all_records = []
    successful_sources = 0

    for source in SOURCES:
        print(f"\nЗагружаем источник: {source}")
        try:
            playlist_text = fetch_text(source)
            records = parse_m3u(playlist_text, source)
            if not records:
                raise RuntimeError("в источнике не найдено ни одной M3U-записи")
            all_records.extend(records)
            successful_sources += 1
            print(f"  Получено записей: {len(records)}")
        except Exception as exc:
            print(f"  ОШИБКА: {exc}")

    if successful_sources == 0 or not all_records:
        print("\nОШИБКА: ни один источник не загружен. Старый favorites.m3u не изменён.")
        return 2

    selected = choose_candidates(all_records)
    print(f"\nСовпадений с избранным: {len(selected)} из {len(MY_FAVORITE_CHANNELS)}")

    # Убираем повторные URL и проверяем кандидатов параллельно.
    unique = {}
    for favorite, record in selected.items():
        unique.setdefault(record["url"], (favorite, record))

    print(f"Проверяем потоков: {len(unique)}")
    working = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(check_stream, url): (favorite, record)
            for url, (favorite, record) in unique.items()
        }

        for future in concurrent.futures.as_completed(future_map):
            favorite, record = future_map[future]
            try:
                alive = future.result()
            except Exception:
                alive = False

            display_name = make_output_name(favorite, record)
            if alive:
                print(f"  РАБОТАЕТ: {display_name}")
                working.append((favorite, display_name, record))
            else:
                print(f"  НЕТ ОТВЕТА: {display_name}")

    working.sort(key=lambda item: MY_FAVORITE_CHANNELS.index(item[0]))

    if len(working) < MIN_WORKING_CHANNELS:
        print(
            f"\nОШИБКА: найдено только {len(working)} рабочих каналов "
            f"(минимум для публикации: {MIN_WORKING_CHANNELS})."
        )
        print("Старый favorites.m3u не изменён.")
        return 3

    # Сначала пишем во временный файл, затем атомарно заменяем основной.
    temp_file = OUTPUT_FILE.with_suffix(".m3u.tmp")
    with temp_file.open("w", encoding="utf-8", newline="\n") as playlist:
        playlist.write("#EXTM3U\n")
        for favorite, display_name, record in working:
            playlist.write(f'#EXTINF:-1,{display_name}\n')
            playlist.write(record["url"] + "\n")

    temp_file.replace(OUTPUT_FILE)

    print(
        f"\nГОТОВО: записано {len(working)} рабочих каналов "
        f"из {len(MY_FAVORITE_CHANNELS)}."
    )
    print(f"Файл: {OUTPUT_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())






