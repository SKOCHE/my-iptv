#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPTV playlist builder v5: strict channel/feed matching, real video decode, audit.
Never treats a reachable URL as proof of channel identity. No legacy fallback URLs.
"""
import concurrent.futures, json, os, re, shutil, subprocess, sys, time, io
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/"channels.json"
OUT=ROOT/"favorites.m3u"
REPORT=ROOT/"update_report.txt"
EPG_MAP=ROOT/"epg_mapping.txt"
API="https://iptv-org.github.io/api"
UA="Mozilla/5.0 (Android TV; IPTV playlist builder/5.0)"
TIMEOUT=18
SAMPLE_SECONDS=12
# User reported these domains as wrong/paywalled. Exclude them from automatic reuse.
BLOCKED_DOMAINS={"cinerama.uz","mcquack.net","linkintel.ru","thestream.cyou"}
def norm(x):
    x=(x or "").casefold().replace("ё","е")
    x=re.sub(r"\([^)]*\)"," ",x)
    x=re.sub(r"[^a-zа-я0-9]+"," ",x)
    return " ".join(x.split())
def get_json(name):
    req=Request(f"{API}/{name}.json",headers={"User-Agent":UA})
    with urlopen(req,timeout=60) as r: data=json.loads(r.read().decode("utf-8"))
    if not isinstance(data,list): raise RuntimeError(f"Invalid {name}.json")
    return data
def blocked(url):
    from urllib.parse import urlsplit
    host=(urlsplit(url).hostname or "").lower()
    return any(host==d or host.endswith("."+d) for d in BLOCKED_DOMAINS)
def ru_feed(ch,feed):
    langs=set(feed.get("languages") or [])
    areas=set(feed.get("broadcast_area") or [])
    return "rus" in langs and bool({"c/RU","r/RU"} & areas or ch.get("country")=="RU")
def sample(stream):
    # Decode up to 12s, extract multiple frames; reject obvious flat/black/green slates.
    try:
        from PIL import Image, ImageStat
        headers=[f"User-Agent: {stream.get('user_agent') or UA}"]
        if stream.get("referrer"): headers.append(f"Referer: {stream['referrer']}")
        cmd=["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-rw_timeout",str(TIMEOUT*1000000),
             "-headers","\r\n".join(headers)+"\r\n","-i",stream["url"],"-t",str(SAMPLE_SECONDS),
             "-vf","fps=1,scale=160:90","-frames:v","8","-f","image2pipe","-vcodec","mjpeg","-"]
        p=subprocess.run(cmd,capture_output=True,timeout=TIMEOUT+20)
        if p.returncode or not p.stdout: return False,"no decoded video frames"
        b=p.stdout; pos=0; frames=[]
        while True:
            a=b.find(b"\xff\xd8",pos)
            if a<0: break
            z=b.find(b"\xff\xd9",a+2)
            if z<0: break
            try:
                im=Image.open(io.BytesIO(b[a:z+2])).convert("RGB")
                st=ImageStat.Stat(im); var=sum(st.var)/3; m=st.mean
                green=(m[1]>m[0]*1.35 and m[1]>m[2]*1.25)
                frames.append((var,green))
            except Exception: pass
            pos=z+2
        if len(frames)<2: return False,"fewer than two decodable frames"
        useful=[f for f in frames if f[0]>18 and not f[1]]
        if len(useful)<2: return False,"black/green/flat placeholder-like frames"
        return True,f"{len(frames)} frames; {len(useful)} non-flat non-green"
    except subprocess.TimeoutExpired: return False,"video decode timeout"
    except Exception as e: return False,str(e)[:180]
def main():
    if not MANIFEST.exists(): raise RuntimeError("channels.json missing")
    if not shutil.which("ffmpeg"): raise RuntimeError("ffmpeg missing; refusing to build")
    wanted=json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(wanted)!=41: raise RuntimeError(f"Expected 41 channels, got {len(wanted)}")
    print("Fetching channel/feed/stream/guide catalogues...")
    channels=get_json("channels"); feeds=get_json("feeds"); streams=get_json("streams"); guides=get_json("guides")
    byid={c["id"]:c for c in channels}
    feedmap={(f.get("channel"),f.get("id")):f for f in feeds}
    nameindex={}
    for c in channels:
        for n in [c.get("name","")]+(c.get("alt_names") or []):
            if n: nameindex.setdefault(norm(n),set()).add(c["id"])
    report=["IPTV v5 audit",f"UTC: {time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime())}",
            "Video test = FFmpeg decode of up to 12 seconds + rejection of obvious flat/black/green frames.",
            "IMPORTANT: this cannot identify the channel logo/content or detect every moving paywall slate.",
            "Reported-bad domains excluded: "+", ".join(sorted(BLOCKED_DOMAINS)),""]
    epg_lines=["# EPG mapping: channel name | tvg-id | guide sources"]
    out=["#EXTM3U"]; used=set(); passed=0
    for item in wanted:
        name=item["name"]; ids=set()
        for alias in [name]+item.get("aliases",[]): ids |= nameindex.get(norm(alias),set())
        if len(ids)!=1:
            report.append(f"UNRESOLVED CHANNEL ID | {name} | {','.join(sorted(ids)) or 'none'}")
            continue
        cid=next(iter(ids)); ch=byid[cid]
        cands=[]
        for st in streams:
            if st.get("channel")!=cid: continue
            url=(st.get("url") or "").strip()
            if not url.startswith("https://") or url in used or blocked(url): continue
            labels=set(st.get("labels") or [])
            if labels & {"Geo-blocked","Not 24/7"}: continue
            feed=feedmap.get((cid,st.get("feed")),{})
            if not ru_feed(ch,feed): continue
            score=(4 if {"c/RU","r/RU"} & set(feed.get("broadcast_area") or []) else 0)+(2 if feed.get("is_main") else 0)+(1 if url.startswith("https://") else 0)
            cands.append((score,st,feed))
        cands.sort(key=lambda x:x[0],reverse=True)
        accepted=None; failures=[]
        for _,st,feed in cands[:8]:
            ok,why=sample(st)
            if ok: accepted=(st,feed,why); break
            failures.append(why)
        if not accepted:
            report.append(f"NO VERIFIED STREAM | {name} | channel_id={cid} | RU candidates={len(cands)} | {('; '.join(failures[:3]) or 'no eligible streams')}")
            continue
        st,feed,why=accepted; url=st["url"]; used.add(url); passed+=1
        out.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-name="{name}" group-title="Россия",{name}')
        if st.get("referrer"): out.append(f'#EXTVLCOPT:http-referrer={st["referrer"]}')
        if st.get("user_agent"): out.append(f'#EXTVLCOPT:http-user-agent={st["user_agent"]}')
        out.append(url)
        tz=",".join(feed.get("timezones") or []) or "not specified"
        report.append(f"VIDEO DECODE OK (identity not visually confirmed) | {name} | {cid} | feed={feed.get('id','')} | timezone={tz} | {why} | {url}")
        guide_matches=[g for g in guides if g.get("channel")==cid and (not g.get("feed") or g.get("feed")==feed.get("id"))]
        guide_urls=[]
        for g in guide_matches:
            for src in g.get("sources") or []:
                if src.get("url"): guide_urls.append(src["url"])
        epg_lines.append(f"{name} | {cid} | "+("; ".join(dict.fromkeys(guide_urls)) or "EPG source not listed"))
    report += ["",f"SUMMARY: decoded={passed}/41; unresolved/no verified stream={41-passed}",
               "This count is NOT a guarantee of channel identity; visual/EPG confirmation is still required."]
    REPORT.write_text("\n".join(report)+"\n",encoding="utf-8")
    EPG_MAP.write_text("\n".join(epg_lines)+"\n",encoding="utf-8")
    # Never replace existing playlist with a one-line/empty result.
    minimum=int(os.environ.get("MINIMUM_TO_PUBLISH","1"))
    if passed<minimum: raise RuntimeError(f"Only {passed} streams passed; existing favorites.m3u preserved. See report.")
    tmp=OUT.with_suffix(".m3u.tmp"); tmp.write_text("\n".join(out)+"\n",encoding="utf-8"); tmp.replace(OUT)
    print(f"Published {passed} streams; audit report lists all 41 channels.")
if __name__=="__main__":
    try: main()
    except Exception as e:
        print("FATAL:",e,file=sys.stderr); sys.exit(1)
