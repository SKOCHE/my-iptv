IPTV v5 — Android TV / Televizo

INSTALL
Replace these files in the repository root:
- update_playlist.py
- channels.json
- .github/workflows/auto_update.yml

Do NOT upload an empty favorites.m3u from this package. The existing playlist is preserved unless at least one stream passes the checks.

WHAT IS CHECKED
- Exact channel ID match from iptv-org channels.json.
- A Russian-language feed and Russian broadcast area (or RU channel record).
- HTTPS only.
- Excludes labels Geo-blocked and Not 24/7.
- Excludes domains the user reported as bad: cinerama.uz, mcquack.net, linkintel.ru, thestream.cyou.
- FFmpeg decodes up to 12 seconds and samples frames; obvious flat/black/green frames are rejected.
- No duplicate stream URL.
- Generates update_report.txt for all requested channels and epg_mapping.txt with available guide source references.
- On missing ffmpeg, bad manifest, API failure, or too few valid streams, workflow fails and old favorites.m3u is not overwritten.

IMPORTANT LIMITS
Video decoding and frame statistics cannot identify channel branding. A moving paywall slate or a different channel may pass. No automatic script can truthfully certify all channels by only probing HLS. Final channel identity requires comparing logo/programme/EPG or human visual inspection. Paid channels remain paid; this does not bypass subscriptions or geo restrictions.
The package deliberately does not restore old fallback URLs because the user reported them as wrong, paywalled, or broken.

TIMEZONE / EPG
Each selected feed's timezone is written to update_report.txt. Guide IDs and guide-source URLs (where listed by iptv-org) are written to epg_mapping.txt. This file is a mapping/report, not a guaranteed ready XMLTV feed. Televizo should use Android TV automatic date/time/timezone. Do not force a global EPG shift until the actual guide offset has been checked.

RUN
GitHub -> Actions -> IPTV Android TV - strict build -> Run workflow.
Download artifact iptv-v5-diagnostics even if the job fails.
Raw playlist URL remains:
https://raw.githubusercontent.com/SKOCHE/my-iptv/main/favorites.m3u

Data model documentation:
https://github.com/iptv-org/api
