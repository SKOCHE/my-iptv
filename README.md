# SKOCHE IPTV Aggregator

## Назначение
Автоматически собирает кандидаты IPTV-потоков для 41 канала, проверяет доступность HTTP/M3U и пытается декодировать короткий фрагмент через FFmpeg.

## Файлы
- `channels.json` — список 41 канала, источники поиска, настройки и вручную подтверждённые URL.
- `update_playlist.py` — поиск, проверка и генерация плейлистов и отчёта.
- `validate_config.py` — проверка конфигурации перед запуском.
- `.github/workflows/auto_update.yml` — запуск вручную, по расписанию и при изменении конфигурации/скриптов.
- `favorites.m3u` — основной плейлист; скрипт помещает сюда только URL из `confirmed_streams` в `channels.json`.
- `test_candidates.m3u` — кандидаты для ручной проверки в Televizo.
- `update_report.txt` — отчёт последнего запуска.

## Запуск локально
```bash
python3 validate_config.py
python3 update_playlist.py
```

## Важные ограничения
- Проверка из GitHub Actions выполняется не через сеть Ростелекома. Ошибка или успех проверки в Actions не гарантируют такой же результат в Televizo.
- `FFMPEG_OK` означает только, что FFmpeg смог декодировать видеопоток. Это не подтверждает название канала.
- В основной `favorites.m3u` автоматически не добавляются потоки только на основании HTTP- или FFmpeg-проверки. Их сначала нужно проверить в Televizo и внести в `confirmed_streams` в `channels.json`.
- Ссылки в `confirmed_streams` сохраняются даже при временной недоступности из GitHub Actions.

## Обновление
Изменения конфигурации и скриптов запускают GitHub Actions автоматически. Для ручного запуска: **Actions → IPTV Aggregator — collect, check and publish → Run workflow**.
