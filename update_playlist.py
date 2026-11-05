#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub IPTV aggregator: discover M3U files, collect all matching variants,
probe manifests and decode a short sample with FFmpeg. Never discard user-confirmed
streams merely because a GitHub-hosted runner cannot reach them.
"""
import concurrent.futures, json, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CFG=json.loads((ROOT/"channels.json").read_text(encoding="utf-8"))
CHANNELS=CFG["channels"]
SET=CFG["settings"]
UA="Mozilla/5.0 (compatible; SKOCHE-IPTV-Aggregator/2.0)"
TIMEOUT=int(SET.get("request_timeout",20))
FFMPEG_SECONDS=int(SET.get("ffmpeg_seconds",8))
REPORT=[]
def log(s): REPORT.append(s); print(s,flush=True)
def req(url,timeout=TIMEOUT,headers=None):
    h={"User-Agent":UA,"Accept":"*/*"}
    if headers: h.update(headers)
    q=urllib.request.Request(url,headers=h)
    with urllib.request.urlopen(q,timeout=timeout) as r:
        # Bound memory/time: some IPTV servers ignore Range and stream indefinitely.
        body = r.read(4096)
        return r.status, r.headers, body
def normalize(s):
    # Keep regional suffixes such as +4: stripping them caused NTV and NTV+4
    # (and MIR / MIR+4) to collapse into the same channel name.
    s=s.lower().replace("ё","е")
    s=s.replace("+"," plus ")
    s=re.sub(r"[^a-zа-я0-9]+"," ",s)
    return " ".join(s.split())

ALIASES={
 "Рен ТВ":["РЕН ТВ","REN TV"],
 "ТВЦ":["ТВ Центр","ТВЦ","TVC"],
 "ТВ3":["ТВ-3","TV3"],
 "Че!":["ЧЕ!","CHE TV"],
 "Перец":["Перец ТВ","Перец"],
 "Мосфильм. Золотая коллекция":["Мосфильм Золотая коллекция","Mosfilm Gold Collection"],
 "Наш кинопоказ HD":["Наш кинопоказ","Кинопоказ HD"],
 "Россия 24":["Россия24","Russia 24"],
 "Viasat History":["Viju History","Viasat History HD"],
 "Viasat Nature":["Viju Nature","Viasat Nature HD"],
 "МУЗ ТВ":["МУЗ-ТВ","Muz TV","MuzTV"],
 "Родное кино":["РодноеКино"],
 "Наше новое кино":["НашеНовоеКино"],
 "Русский бестселлер":["РусскийБестселлер"],
 "НТВ (+4)":["НТВ плюс 4","НТВ 4","NTV +4","NTV plus 4"],
 "МИР (+4)":["МИР плюс 4","МИР 4","MIR +4","MIR plus 4"],
 "Россия 1 HD (+4)":["Россия 1 HD плюс 4","Россия 1 плюс 4","Russia 1 HD +4"]
}
# Names that are too generic to be safe as aliases are deliberately omitted.
def names_for(ch):
    return {normalize(ch),*(normalize(x) for x in ALIASES.get(ch,[]))}

def match_channel(name):
    n=normalize(name)
    if not n: return None
    matches=[ch for ch in CHANNELS if n in names_for(ch)]
    return matches[0] if len(matches)==1 else None

def parse_m3u(text,source):
    lines=[x.strip() for x in text.replace("\ufeff","").splitlines()]
    ext=None; out=[]
    for line in lines:
        if line.startswith("#EXTINF"):
            ext=line
        elif ext and line and not line.startswith("#"):
            if line.startswith(("http://","https://")):
                name=ext.rsplit(",",1)[-1].strip() if "," in ext else ""
                tvg=re.search(r'tvg-name="([^"]+)"',ext,re.I)
                if tvg and (not name or name.lower() in ("channel","")): name=tvg.group(1)
                tvgid=re.search(r'tvg-id="([^"]+)"',ext,re.I)
                out.append({"name":name,"tvg_id":tvgid.group(1) if tvgid else "",
                            "url":line,"extinf":ext,"source":source})
            ext=None
    return out
def github_tree(repo):
    for branch in ("HEAD","main","master"):
        url=f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
        try:
            status,headers,data=req(url,headers={"Accept":"application/vnd.github+json"})
            obj=json.loads(data)
            if "tree" in obj: return obj["tree"], branch
        except Exception: pass
    raise RuntimeError("GitHub tree недоступен")
def discover_sources():
    records=[]; stats=[]
    # Stable curated M3U sources first
    for u in ("https://iptv-org.github.io/iptv/countries/ru.m3u",
              "https://iptv-org.github.io/iptv/languages/rus.m3u"):
        try:
            _,_,b=req(u); rec=parse_m3u(b.decode("utf-8-sig","replace"),u)
            records.extend(rec); stats.append((u,len(rec),"OK"))
        except Exception as e: stats.append((u,0,str(e)[:160]))
    for source in CFG["github_sources"]:
        repo=source["repo"]
        try:
            tree,branch=github_tree(repo)
            files=[x["path"] for x in tree if x.get("type")=="blob" and
                   x["path"].lower().endswith((".m3u",".m3u8",".txt")) and
                   not any(k in x["path"].lower() for k in ("readme","license","changelog"))]
            # Prefer likely playlist names, then smaller path depth. Keep scan bounded.
            files.sort(key=lambda p:(0 if any(k in p.lower() for k in ("ru","russia","iptv","playlist","tv")) else 1,p.count("/"),len(p)))
            count=0
            for path in files[:int(SET["max_playlist_files_per_repo"])]:
                raw=f"https://raw.githubusercontent.com/{repo}/{branch}/{urllib.parse.quote(path)}"
                try:
                    _,_,b=req(raw)
                    if len(b)>int(SET["max_file_bytes"]) or b"\x00" in b[:1000]: continue
                    txt=b.decode("utf-8-sig","replace")
                    if "#EXTM3U" not in txt[:500]: continue
                    rec=parse_m3u(txt,f"{repo}/{path}")
                    if rec: records.extend(rec); count+=len(rec)
                except Exception: continue
            stats.append((repo,count,"OK" if count else "no M3U read"))
        except Exception as e: stats.append((repo,0,str(e)[:160]))
    return records,stats
def probe_manifest(url):
    try:
        status,headers,b=req(url,timeout=int(SET["stream_timeout"]),headers={"Range":"bytes=0-4095"})
        if status not in (200,206) or not b: return False,"HTTP/empty"
        # HLS manifest is text; TS/fMP4 streams can be binary and still valid
        if b.lstrip().startswith(b"#EXTM3U"): return True,"HLS manifest"
        c=(headers.get("Content-Type") or "").lower()
        if any(x in c for x in ("video/","octet-stream","mpegurl")): return True,"media response"
        return False,"not HLS/media"
    except Exception as e: return False,str(e)[:100]
def decode(url):
    if not shutil_which("ffmpeg"): return False,"FFmpeg отсутствует"
    cmd=["ffmpeg","-nostdin","-v","error","-rw_timeout","12000000","-i",url,"-t",str(FFMPEG_SECONDS),"-map","0:v:0?","-frames:v","3","-f","null","-"]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=int(SET["stream_timeout"])+FFMPEG_SECONDS+5)
        if p.returncode==0: return True,"FFmpeg decode OK"
        return False,(p.stderr.strip().splitlines()[-1][:160] if p.stderr.strip() else "decode failed")
    except Exception as e: return False,str(e)[:140]
def shutil_which(x):
    import shutil
    return shutil.which(x)
def write_m3u(path,items):
    with path.open("w",encoding="utf-8",newline="\n") as f:
        f.write("#EXTM3U\n")
        for ch,url,src,status in items:
            f.write(f'#EXTINF:-1 tvg-name="{ch}" group-title="IPTV",{ch} [{status}]\n{url}\n')
def main():
    log("=== SKOCHE IPTV Aggregator v2 ===")
    records,stats=discover_sources()
    for u,n,s in stats: log(f"SOURCE | {u} | records={n} | {s}")
    log(f"TOTAL SOURCE RECORDS: {len(records)}")
    # Keep all exact name matches and every variant URL, not just one per channel.
    candidates={}
    rejected_wink=0
    for rec in records:
        host=(urllib.parse.urlparse(rec["url"]).hostname or "").lower()
        # User already reported these streams resolve to a territory-blocked Wink screen.
        if host == "zabava-htlive.cdn.ngenix.net" or host.endswith(".zabava.cdn.ngenix.net"):
            rejected_wink += 1
            continue
        ch=match_channel(rec["name"])
        if ch:
            candidates.setdefault((ch,rec["url"]),rec)
    log(f"REJECTED WINK/ZABAVA CANDIDATES: {rejected_wink}")
    # User-confirmed links are pinned and never auto-removed by a remote probe.
    pinned={(x["channel"],x["url"]):{"source":"USER_CONFIRMED"} for x in CFG["confirmed_streams"]}
    for k,v in pinned.items(): candidates[k]=v
    log(f"MATCHED UNIQUE CANDIDATES: {len(candidates)}")
    items=list(candidates.items())
    pinned={(x["channel"],x["url"]):{"source":"USER_CONFIRMED"} for x in CFG["confirmed_streams"]}
    # Stage 1: fast parallel HTTP manifest checks for every non-pinned candidate.
    http_results={}
    workers=max(4,min(int(SET.get("workers",16)),24))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        fut={ex.submit(probe_manifest,k[1]):k for k,_ in items if k not in pinned}
        for f in concurrent.futures.as_completed(fut):
            k=fut[f]
            try: http_results[k]=f.result()
            except Exception as e: http_results[k]=(False,str(e)[:100])

    # Stage 2: FFmpeg is expensive. Decode at most 3 HTTP-reachable variants
    # per channel in parallel. All HTTP-reachable candidates still go to the
    # Televizo test playlist, even if they are not selected for FFmpeg.
    by_channel={}
    for (ch,url),rec in items:
        if (ch,url) in pinned: continue
        ok,detail=http_results.get((ch,url),(False,"not checked"))
        if ok: by_channel.setdefault(ch,[]).append(((ch,url),rec))
    decode_targets=[]
    for ch,group in by_channel.items():
        # Preserve deterministic source order, but cap the costly decode stage.
        decode_targets.extend(group[:3])

    decode_results={}
    decode_workers=max(2,min(8,workers//2))
    with concurrent.futures.ThreadPoolExecutor(max_workers=decode_workers) as ex:
        fut={ex.submit(decode,k[1]):k for k,_ in decode_targets}
        for f in concurrent.futures.as_completed(fut):
            k=fut[f]
            try: decode_results[k]=f.result()
            except Exception as e: decode_results[k]=(False,str(e)[:140])

    test=[]; main_entries=[]; summary={c:[] for c in CHANNELS}
    decoded_per_channel={}
    for (ch,url),rec in items:
        if (ch,url) in pinned:
            status="USER_CONFIRMED"; ok=True; src="user-confirmed"; detail="confirmed by user"
        else:
            http_ok,detail=http_results.get((ch,url),(False,"not checked"))
            src=rec["source"]
            if not http_ok:
                status="HTTP_FAIL"; ok=False
            else:
                ok=True
                if (ch,url) in decode_results:
                    dec,why=decode_results[(ch,url)]
                    status="FFMPEG_OK" if dec else "HTTP_ONLY"
                    detail=why
                    if dec: decoded_per_channel[ch]=decoded_per_channel.get(ch,0)+1
                else:
                    status="HTTP_OK_NOT_DECODED"
                    detail="HTTP manifest OK; FFmpeg cap reached for this channel"
        summary[ch].append(status)
        log(f"CANDIDATE | {ch} | {status} | {src} | {detail} | {url}")
        if ok:
            test.append((ch,url,src,status))
            if status in ("USER_CONFIRMED","FFMPEG_OK"):
                main_entries.append((ch,url,src,status))

    order={c:i for i,c in enumerate(CHANNELS)}
    test.sort(key=lambda x:(order[x[0]],x[3],x[2],x[1]))
    main_entries.sort(key=lambda x:(order[x[0]],x[3]))
    write_m3u(ROOT/"test_candidates.m3u",test)
    if len(main_entries)>=int(SET["min_main_entries"]):
        write_m3u(ROOT/"favorites.m3u",main_entries)
        log(f"MAIN UPDATED: {len(main_entries)} entries")
    else:
        log(f"MAIN PRESERVED: only {len(main_entries)} safe entries")
    missing=[c for c in CHANNELS if not summary[c]]
    http_only=[c for c,vals in summary.items() if any(v in ("HTTP_ONLY","HTTP_OK_NOT_DECODED") for v in vals) and "FFMPEG_OK" not in vals]
    log(f"HTTP CANDIDATES: {len(test)}")
    log(f"FFMPEG DECODE TARGETS: {len(decode_targets)} (max 3 per channel)")
    log(f"FFMPEG DECODE OK: {sum(decoded_per_channel.values())}")
    log(f"CHANNELS WITH CANDIDATES: {len(CHANNELS)-len(missing)}/{len(CHANNELS)}")
    log("NO CANDIDATE: "+", ".join(missing))
    log("HTTP-ONLY / NOT DECODED (needs Televizo check): "+", ".join(http_only))
    (ROOT/"update_report.txt").write_text("\n".join(REPORT)+"\n",encoding="utf-8")
    return 0
if __name__=="__main__": sys.exit(main())
