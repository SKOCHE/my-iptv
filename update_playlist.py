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
        return r.status,r.headers, r.read()
def normalize(s):
    s=s.lower().replace("ё","е")
    s=re.sub(r"\([^)]*\)|\+\s*4\s*ч?|\+4h|красноярск"," ",s)
    s=re.sub(r"[^a-zа-я0-9]+"," ",s)
    return " ".join(s.split())
ALIASES={
 "Рен ТВ":["РЕН ТВ","REN TV"],"ТВЦ":["ТВ Центр","ТВЦ"],"ТВ3":["ТВ-3","TV3"],
 "Че!":["Че","Че ТВ"],"Мосфильм. Золотая коллекция":["Мосфильм Золотая коллекция","Mosfilm"],
 "Наш кинопоказ HD":["Наш кинопоказ","Кинопоказ HD"],"Россия 24":["Россия24"],
 "Viasat History":["Viju History","Viasat History HD"],"Viasat Nature":["Viju Nature","Viasat Nature HD"],
 "МУЗ ТВ":["МУЗ-ТВ","Muz TV","MuzTV"],"Родное кино":["РодноеКино"],
 "Наше новое кино":["НашеНовоеКино"],"Русский бестселлер":["РусскийБестселлер"]
}
def names_for(ch):
    return {normalize(ch),*(normalize(x) for x in ALIASES.get(ch,[]))}
def match_channel(name):
    n=normalize(name)
    if not n: return None
    matches=[]
    for ch in CHANNELS:
        variants=names_for(ch)
        # strict token-aware substring; fuzzy matching intentionally avoided
        if n in variants or any(len(v)>=6 and (v in n or n in v) for v in variants):
            matches.append(ch)
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
                out.append({"name":name,"url":line,"extinf":ext,"source":source})
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
    for rec in records:
        ch=match_channel(rec["name"])
        if ch: candidates.setdefault((ch,rec["url"]),rec)
    # User-confirmed links are pinned and never auto-removed by a remote probe.
    pinned={(x["channel"],x["url"]):{"source":"USER_CONFIRMED"} for x in CFG["confirmed_streams"]}
    for k,v in pinned.items(): candidates[k]=v
    log(f"MATCHED UNIQUE CANDIDATES: {len(candidates)}")
    items=list(candidates.items())
    results={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(SET["workers"])) as ex:
        fut={ex.submit(probe_manifest,k[1]):k for k,_ in items if k not in pinned}
        for f in concurrent.futures.as_completed(fut):
            k=fut[f]
            try: results[k]=f.result()
            except Exception as e: results[k]=(False,str(e)[:100])
    test=[]; main_entries=[]; summary={c:[] for c in CHANNELS}
    for (ch,url),rec in items:
        if (ch,url) in pinned:
            status="USER_CONFIRMED"; ok=True; src="user-confirmed"
        else:
            ok,detail=results.get((ch,url),(False,"not checked"))
            status="HTTP_OK" if ok else "HTTP_FAIL"; src=rec["source"]
            if ok:
                # Decode check is stronger than a manifest response; still not identity proof.
                dec,why=decode(url)
                status="FFMPEG_OK" if dec else "HTTP_ONLY"
                detail=why
            log(f"CANDIDATE | {ch} | {status} | {src} | {url}")
        summary[ch].append(status)
        if ok:
            test.append((ch,url,src,status))
            # Main is safe: pinned or FFmpeg-decoded only. HTTP-only entries stay test-only.
            if status in ("USER_CONFIRMED","FFMPEG_OK"): main_entries.append((ch,url,src,status))
    # Sort by configured channel order, keep all good variants in test file.
    order={c:i for i,c in enumerate(CHANNELS)}
    test.sort(key=lambda x:(order[x[0]],x[3],x[2]))
    main_entries.sort(key=lambda x:(order[x[0]],x[3]))
    write_m3u(ROOT/"test_candidates.m3u",test)
    # Never replace a healthy previous main playlist with an empty/short result.
    if len(main_entries)>=int(SET["min_main_entries"]):
        write_m3u(ROOT/"favorites.m3u",main_entries)
        log(f"MAIN UPDATED: {len(main_entries)} entries")
    else:
        log(f"MAIN PRESERVED: only {len(main_entries)} safe entries")
    missing=[c for c in CHANNELS if not summary[c]]
    http_only=[c for c,vals in summary.items() if "HTTP_ONLY" in vals and "FFMPEG_OK" not in vals]
    log(f"CHANNELS WITH CANDIDATES: {len(CHANNELS)-len(missing)}/{len(CHANNELS)}")
    log("NO CANDIDATE: "+", ".join(missing))
    log("HTTP-ONLY (needs Televizo check): "+", ".join(http_only))
    (ROOT/"update_report.txt").write_text("\n".join(REPORT)+"\n",encoding="utf-8")
    return 0
if __name__=="__main__": sys.exit(main())
