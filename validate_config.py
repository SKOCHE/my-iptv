#!/usr/bin/env python3
import json,sys
from pathlib import Path
p=Path("channels.json")
d=json.loads(p.read_text(encoding="utf-8"))
assert len(d["channels"])==41, f"Ожидалось 41 канал, найдено {len(d['channels'])}"
assert len(set(d["channels"]))==41, "Повторяются названия каналов"
assert d["confirmed_streams"], "Нет списка подтверждённых потоков"
for x in d["confirmed_streams"]:
    assert x["channel"] in d["channels"], f"Неизвестный канал: {x['channel']}"
    assert x["url"].startswith(("http://","https://")), f"Неверный URL: {x['url']}"
assert d["github_sources"], "Не заданы GitHub-источники"
print(f"OK: {len(d['channels'])} каналов, {len(d['confirmed_streams'])} подтверждённых ссылок, {len(d['github_sources'])} GitHub-репозиториев")
