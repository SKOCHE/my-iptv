import urllib.request
import re
import socket

# 1. Ссылки на открытые плейлисты-источники (РФ и СНГ базы)
SOURCES = [
    "https://github.io",
    "https://githubusercontent.com"
]

# 2. Ваш список из 42 каналов
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

def check_link_is_alive(url):
    """Проверяет доступность потока с таймаутом."""
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status in:
                return True
    except Exception:
        return False
    return False

def clean_name(name):
    """Очищает имена каналов для точного сопоставления баз."""
    name = re.sub(r'\(Dimonovich\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\+4|\(\+4\)|\+4ч|\+4h', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip().lower()

def main():
    collected_channels = {}
    favorites_map = {clean_name(ch): ch for ch in MY_FAVORITE_CHANNELS}

    for url in SOURCES:
        try:
            print(f"Сканируем источник: {url}")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode('utf-8', errors='ignore')
                matches = re.findall(r'(#EXTINF:.*?,(.*?)\n(http.*?))(?=\n#EXTINF|\n$|$)', content, re.DOTALL)
                
                for full_extinf, channel_name, stream_url in matches:
                    cleaned_src_name = clean_name(channel_name)
                    
                    if cleaned_src_name in favorites_map:
                        is_plus_four = any(marker in channel_name for marker in ["+4", "(+4)", "+4h", "Красноярск"])
                        
                        if cleaned_src_name not in collected_channels or (is_plus_four and not collected_channels[cleaned_src_name][3]):
                            beautiful_name = favorites_map[cleaned_src_name]
                            if is_plus_four:
                                beautiful_name += " (+4)"
                                
                            clean_extinf = f'#EXTINF:-1,{beautiful_name}'
                            collected_channels[cleaned_src_name] = (clean_extinf, stream_url.strip(), beautiful_name, is_plus_four)
        except Exception as e:
            print(f"Ошибка источника {url}: {e}")

    working_channels = {}
    print(f"\nНайдено совпадений: {len(collected_channels)}. Проверяем ссылки...")
    
    for cleaned_id, (extinf, stream_url, beautiful_name, is_plus_four) in collected_channels.items():
        print(f"Проверяем: {beautiful_name}...", end="", flush=True)
        if check_link_is_alive(stream_url):
            print(" РАБОТАЕТ")
            working_channels[beautiful_name] = (extinf, stream_url)
        else:
            print(" МЕРТВ (пропускаем)")

    with open("favorites.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for display_name, (extinf, stream_url) in working_channels.items():
            f.write(f"{extinf}\n{stream_url}\n")
            
    print(f"\nЗавершено! Рабочих каналов сохранено: {len(working_channels)}")

if __name__ == "__main__":
    socket.setdefaulttimeout(4)
    main()
