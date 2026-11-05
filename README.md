# SKOCHE IPTV — агрегатор 41 канала

Проект использует движок **Guovin/iptv-api** (AGPL-3.0), настроенный под список каналов SKOCHE. Движок собирает потоки из нескольких публичных M3U-источников, сопоставляет названия через `config/alias.txt`, проверяет кандидаты по скорости/задержке и формирует M3U.

## Целевой плейлист
После первого успешного запуска GitHub Actions публикует постоянную ссылку:

`https://skoche.github.io/my-iptv/favorites.m3u`

Эту ссылку нужно добавить в Televizo. Она обновляется при каждом успешном запуске workflow. Старая ссылка `raw.githubusercontent.com/.../favorites.m3u` больше не используется, потому что результат публикуется через GitHub Pages, а не коммитится в Git.

## Настройка 41 канала
- `config/demo.txt` — ровно 41 канал, в нужном порядке.
- `config/alias.txt` — русские/латинские варианты написания и EPG-псевдонимы.
- `channels.json` — контрольный список каналов и источников.
- `config/subscribe.txt` — публичные M3U-источники для поиска.
- `config/blacklist.txt` — фильтр известных нежелательных доменов, включая Wink/Zabava.
- `config/config.ini` — настройки сбора и проверки.

## Источники сбора

В `config/subscribe.txt` подключены несколько независимых каталогов:
- [iptv-org Russia](https://iptv-org.github.io/iptv/countries/ru.m3u) и [Russian language](https://iptv-org.github.io/iptv/languages/rus.m3u);
- [ngrch/iptv](https://github.com/ngrch/iptv);
- [dearbulut/iptv](https://github.com/dearbulut/iptv);
- [substanc1/iptv-russia](https://github.com/substanc1/iptv-russia);
- [denxvofficial/IPTV](https://github.com/denxvofficial/IPTV);
- [AdeelWajid/iptv_validated_list](https://github.com/AdeelWajid/iptv_validated_list);
- [MaximKiselev/iptv](https://github.com/MaximKiselev/iptv);
- [boxer180/RUSSIA_TV](https://github.com/boxer180/RUSSIA_TV);
- [swoldier-rus/IP_TV](https://github.com/swoldier-rus/IP_TV);
- [smolnp/IPTVru](https://github.com/smolnp/IPTVru).

Источники используются как каталоги кандидатов. Сами URL потоков не принадлежат этому агрегатору и могут перестать работать, требовать авторизацию или быть ограничены по региону.

## Как запускается
GitHub → **Actions** → **Generate playlist manually** → **Run workflow**.

В workflow:
1. Загружаются публичные M3U-источники.
2. Имена каналов сопоставляются с нашим каталогом из 41 канала.
3. Кандидаты проверяются движком Guovin.
4. Лучшие прошедшие проверку потоки попадают в `result.m3u`.
5. Копия `favorites.m3u` публикуется на GitHub Pages по постоянному адресу.

## Важно о проверке
Проверка выполняется на серверах GitHub, а не через Ростелеком. Успешный тест означает, что поток прошёл проверку на runner, но не гарантирует воспроизведение в Televizo у конкретного провайдера. Поэтому после запуска нужно проверить итоговый M3U на телевизоре. Исторические ссылки, которые раньше открывались, не считаются подтверждёнными автоматически.

Настройки намеренно не ограничивают потоки только HD и скоростью 0.5 MiB/s: иначе часть каналов с более низким битрейтом будет потеряна. В итог попадает до пяти лучших вариантов на канал.

## Однократная настройка GitHub Pages
В репозитории открой **Settings → Pages → Build and deployment → Source → GitHub Actions**. Это необходимо для первой публикации Pages.

## Лицензия и происхождение
Движок основан на [Guovin/iptv-api](https://github.com/Guovin/iptv-api), лицензия AGPL-3.0. Исходный README сохранён как `README_UPSTREAM.md`, исходная лицензия — `LICENSE`, уведомление о модификациях — `NOTICE`. Настройки каналов и интеграция SKOCHE добавлены отдельно.
