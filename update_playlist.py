#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build IPTV playlist with explicit Barnaul (+4) regional overrides.
A successful FFmpeg decode is NOT proof of channel identity.
"""
import concurrent.futures, json, os, re, shutil, subprocess, sys, time, io
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'channels.json'
OUT = ROOT / 'favorites.m3u'
REPORT = ROOT / 'update_report.txt'
EPG = ROOT / 'epg_mapping.txt'
API = 'https://iptv-org.github.io/api'
UA = 'Mozilla/5.0 (compatible; SKOCHE-IPTV-check/9.0)'
BLOCKED = {'cinerama.uz', 'mcquack.net', 'linkintel.ru', 'thestream.cyou'}

# Regional feeds explicitly identified as +4 relative to Moscow (Barnaul time).
# These are candidates from published IPTV stream catalogs; FFmpeg tests availability,
# but visual inspection in Televizo is still required to confirm channel identity.
BARNAUL_PLUS4 = {
    'НТВ (+4)': 'https://cdn.ntv.ru/ntv4/playlist.m3u8',
    'Россия 1 HD (+4)': 'https://vgtrkregion-reg.cdnvideo.ru/vgtrk/4/russia1-hd/index.m3u8',
}

def norm(s):
    s = (s or '').casefold().replace('ё', 'е')
    s = re.sub(r'\([^)]*\)', ' ', s)
    s = re.sub(r'[^a-zа-я0-9]+', ' ', s)
    return ' '.join(s.split())

def fetch_json(name):
    req = Request(f'{API}/{name}.json', headers={'User-Agent': UA})
    with urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode('utf-8'))
    if not isinstance(data, list):
        raise RuntimeError(f'{name}.json returned unexpected data')
    return data

def is_blocked(url):
    host = (urlsplit(url).hostname or '').lower()
    return any(host == d or host.endswith('.' + d) for d in BLOCKED)

def resolve_channel(item, channels, name_index):
    explicit = item.get('channel_id')
    if explicit and any(c.get('id') == explicit for c in channels):
        return explicit, 'explicit channel_id'
    canonical = norm(item['name'])
    direct = name_index.get(canonical, set())
    if len(direct) == 1:
        return next(iter(direct)), 'canonical exact'
    hits = set()
    for alias in item.get('aliases', []):
        hits |= name_index.get(norm(alias), set())
    if len(hits) == 1:
        return next(iter(hits)), 'unique alias'
    return None, 'ambiguous/no exact ID: ' + ','.join(sorted(hits or direct))

def decode_test(stream):
    try:
        from PIL import Image, ImageStat
        headers = [f"User-Agent: {stream.get('user_agent') or UA}"]
        if stream.get('referrer'):
            headers.append('Referer: ' + stream['referrer'])
        cmd = ['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-rw_timeout','18000000',
               '-headers','\r\n'.join(headers)+'\r\n','-i',stream['url'],'-t','10',
               '-vf','fps=1,scale=160:90','-frames:v','6','-f','image2pipe','-vcodec','mjpeg','-']
        p = subprocess.run(cmd, capture_output=True, timeout=28)
        if p.returncode or not p.stdout:
            return False, 'FFmpeg could not decode video'
        b, pos, frames = p.stdout, 0, []
        while True:
            a = b.find(b'\xff\xd8', pos)
            if a < 0: break
            z = b.find(b'\xff\xd9', a + 2)
            if z < 0: break
            try:
                im = Image.open(io.BytesIO(b[a:z+2])).convert('RGB')
                st = ImageStat.Stat(im)
                mean = st.mean
                green = mean[1] > mean[0]*1.35 and mean[1] > mean[2]*1.25
                variance = sum(st.var)/3
                frames.append((variance, green))
            except Exception:
                pass
            pos = z + 2
        good = [x for x in frames if x[0] > 18 and not x[1]]
        if len(good) < 2:
            return False, f'flat/black/green or insufficient frames ({len(frames)} frames)'
        return True, f'{len(frames)} frames decoded; {len(good)} non-flat'
    except subprocess.TimeoutExpired:
        return False, 'decode timeout'
    except Exception as e:
        return False, str(e)[:160]

def main():
    if not MANIFEST.is_file():
        raise RuntimeError('channels.json is missing')
    if not shutil.which('ffmpeg'):
        raise RuntimeError('FFmpeg is missing')
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        raise RuntimeError('Pillow is missing')

    wanted = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if len(wanted) != 41:
        raise RuntimeError(f'Expected 41 manifest entries, got {len(wanted)}')

    channels = fetch_json('channels')
    feeds = fetch_json('feeds')
    streams = fetch_json('streams')
    guides = fetch_json('guides')
    byid = {c['id']: c for c in channels}
    feedmap = {(f.get('channel'), f.get('id')): f for f in feeds}
    name_index = {}
    for c in channels:
        for n in [c.get('name', '')] + (c.get('alt_names') or []):
            if n:
                name_index.setdefault(norm(n), set()).add(c['id'])

    report = [
        'IPTV v10 diagnostic report',
        'UTC: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()),
        'IMPORTANT: FFmpeg decode confirms video availability, NOT channel identity.',
        'Regional target: Barnaul, Moscow time +4.',
        'NTV +4 and Russia 1 HD +4 are handled as explicit regional candidates.',
        'MIR +4 is NOT substituted with a generic/Moscow stream.',
        'Previously reported bad domains excluded: ' + ', '.join(sorted(BLOCKED)), ''
    ]
    epg_lines = ['# name | tvg-id | XMLTV source URLs (if listed)']
    output = ['#EXTM3U']
    used = set()
    passed = 0

    for item in wanted:
        name = item['name']
        is_regional = name in BARNAUL_PLUS4

        # CRITICAL FIX: regional channels are processed BEFORE catalog ID lookup.
        # This fixes Russia 1 HD (+4), which has no channel_id in channels.json.
        if is_regional:
            regional_url = BARNAUL_PLUS4[name]
            candidates = []
            if regional_url not in used:
                candidates = [(100, {'url': regional_url, 'user_agent': UA}, {})]
            else:
                report.append(f'DUPLICATE REGIONAL URL | {name} | {regional_url}')
                epg_lines.append(f'{name} | | regional URL duplicated')
                continue
            cid, match, ch = item.get('channel_id'), 'explicit Barnaul +4 URL', {}
        else:
            cid, match = resolve_channel(item, channels, name_index)
            if not cid:
                report.append(f'NO CHANNEL ID | {name} | {match}')
                epg_lines.append(f'{name} | | no channel ID')
                continue
            ch = byid[cid]
            candidates = []
            for st in streams:
                if st.get('channel') != cid:
                    continue
                url = (st.get('url') or '').strip()
                if not url.startswith(('https://', 'http://')) or url in used or is_blocked(url):
                    continue
                labels = set(st.get('labels') or [])
                if labels & {'Geo-blocked', 'Not 24/7'}:
                    continue
                feed = feedmap.get((cid, st.get('feed')), {})
                langs = set(feed.get('languages') or [])
                areas = set(feed.get('broadcast_area') or [])
                if langs and 'rus' not in langs and ch.get('country') != 'RU':
                    continue
                score = (8 if 'rus' in langs else 0) + (5 if {'c/RU', 'r/RU'} & areas else 0)
                score += 2 if feed.get('is_main') else 0
                score += 1 if url.startswith('https://') else 0
                candidates.append((score, st, feed))

        candidates.sort(key=lambda x: x[0], reverse=True)
        reasons = []
        accepted = None
        for _, st, feed in candidates[:12]:
            ok, reason = decode_test(st)
            if ok:
                accepted = (st, feed, reason)
                break
            reasons.append(reason)

        if not accepted:
            report.append(
                f'NO DECODED STREAM | {name} | id={cid or "regional override"} | '
                f'match={match} | candidates={len(candidates)} | '
                f'{"; ".join(reasons[:4]) or "no eligible stream"}'
            )
            epg_lines.append(f'{name} | {cid or ""} | guide not verified')
            continue

        st, feed, reason = accepted
        url = st['url']
        used.add(url)
        passed += 1
        tvg_id = cid or ''
        output.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" group-title="IPTV",{name}')
        output.append(url)
        status = 'BARNAUL +4 CANDIDATE / IDENTITY UNCONFIRMED' if is_regional else 'DECODE OK / IDENTITY UNCONFIRMED'
        report.append(f'{status} | {name} | id={cid or "regional override"} | match={match} | {reason} | {url}')

        guide_urls = []
        if cid:
            for g in guides:
                if g.get('channel') == cid and (not g.get('feed') or g.get('feed') == feed.get('id')):
                    guide_urls += [s['url'] for s in (g.get('sources') or []) if s.get('url')]
        epg_lines.append(f'{name} | {tvg_id} | ' + ('; '.join(dict.fromkeys(guide_urls)) or 'EPG source not verified'))

    report += [
        '',
        f'SUMMARY: decoded={passed}/41; no decoded stream={41-passed}',
        'Regional +4 URLs are candidates; verify broadcast identity/time in Televizo.',
        'MIR (+4) is intentionally not mapped to a generic stream.',
        'Never treat DECODE OK as visual confirmation of the named channel.'
    ]
    REPORT.write_text('\n'.join(report) + '\n', encoding='utf-8')
    EPG.write_text('\n'.join(epg_lines) + '\n', encoding='utf-8')

    minimum = int(os.environ.get('MINIMUM_TO_PUBLISH', '5'))
    if passed < minimum:
        raise RuntimeError(
            f'Only {passed} channels decoded (< minimum {minimum}); '
            'existing favorites.m3u was NOT changed'
        )
    tmp = OUT.with_suffix('.m3u.tmp')
    tmp.write_text('\n'.join(output) + '\n', encoding='utf-8')
    tmp.replace(OUT)
    print(
        f'Updated favorites.m3u: {passed}/41 streams decoded. '
        'Channel identity and regional time still require visual confirmation.'
    )

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('FATAL:', e, file=sys.stderr)
        sys.exit(1)

