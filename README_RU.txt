IPTV v6 — комплект замены для SKOCHE/my-iptv

ЧТО ВНУТРИ
- channels.json — список всех 41 каналов и псевдонимов.
- update_playlist.py — подбор потоков из iptv-org, проверка декодирования FFmpeg, отчёт.
- validate_config.py — проверка манифеста (ровно 41 канал).
- .github/workflows/auto_update.yml — установка FFmpeg/Pillow, запуск, публикация отчётов и коммит.

КАК УСТАНОВИТЬ
1. Распакуй архив на компьютере.
2. Открой репозиторий https://github.com/SKOCHE/my-iptv.
3. В корне замени channels.json, update_playlist.py, validate_config.py и README_RU.txt.
4. В папке .github/workflows замени auto_update.yml.
5. Не удаляй вручную favorites.m3u. Скрипт обновит его только если пройдут минимум 5 потоков; при неудаче старый файл сохранится.
6. Открой Actions → Build strict Android TV IPTV playlist → Run workflow.
7. После запуска проверь update_report.txt и скачай artifact iptv-diagnostics, если запуск завершился ошибкой.

ВАЖНЫЕ ОГРАНИЧЕНИЯ
- Источники берутся из каталога iptv-org. Это не полный интернет-каталог и он не гарантирует наличие всех 41 каналов.
- FFmpeg подтверждает, что видео декодируется, но НЕ определяет название канала по картинке. Поэтому статус DECODE OK не равен подтверждению, что это нужный канал.
- Исключены домены cinerama.uz, mcquack.net, linkintel.ru и thestream.cyou, на которые ранее поступали жалобы.
- Нельзя обещать 41 рабочий канал без отдельной проверки каждого потока в Televizo.
- Если найдено меньше 5 потоков, favorites.m3u не перезаписывается.

ССЫЛКА ДЛЯ TELEVIZO ОСТАЁТСЯ ПРЕЖНЕЙ:
https://raw.githubusercontent.com/SKOCHE/my-iptv/main/favorites.m3u
