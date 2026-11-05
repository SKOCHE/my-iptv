#!/usr/bin/env python3
# Validate SKOCHE-specific configuration without importing third-party dependencies.
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cfg = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
channels = cfg["channels"]
assert len(channels) == 46, f"Expected 46 channels, got {len(channels)}"
assert len(set(channels)) == 46, "Duplicate channel names in channels.json"

demo_lines = (ROOT / "config/demo.txt").read_text(encoding="utf-8").splitlines()
template = [line.strip() for line in demo_lines if line.strip() and "#genre#" not in line and not line.lstrip().startswith("#")]
assert template == channels, "config/demo.txt must contain exactly the 46 channels in channels.json order"

sources = [line.strip() for line in (ROOT / "config/subscribe.txt").read_text(encoding="utf-8").splitlines()
           if line.strip() and not line.lstrip().startswith("#")]
assert len(sources) >= 8, f"Expected at least 8 source playlists, got {len(sources)}"
assert all(url.startswith(("http://", "https://")) for url in sources), "Invalid subscription URL"

alias_path = ROOT / "config/alias.txt"
alias_rows = [line.strip() for line in alias_path.read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
primary_names = set()
owner_by_alias = {}
normalizer = re.compile(r"-|_|\\((.*?)\\)|пј€(.*?)пј‰|\\[(.*?)]|гЂЊ(.*?)гЂЌ| |пЅњ|йў‘йЃ“|ж™®жё…|ж ‡жё…|й«жё…|HD|hd|и¶…жё…|и¶…й«|и¶…й«жё…|4K|4k|дё­е¤®|е¤®и§†|з”µи§†еЏ°|еЏ°|з”µдїЎ|иЃ”йЂљ|з§»еЉЁ")
def normalize_alias(value):
    return normalizer.sub("", value).replace("plus", "+").replace("PLUS", "+").replace("пј‹", "+").lower()
for row in alias_rows:
    parts = [part.strip() for part in row.split(",")]
    primary = parts[0]
    assert primary in channels, f"Alias primary not in 46-channel catalog: {primary}"
    assert primary not in primary_names, f"Duplicate alias primary: {primary}"
    primary_names.add(primary)
    primary_key = normalize_alias(primary)
    previous = owner_by_alias.get(primary_key)
    assert previous in (None, primary), f"Primary alias collision {primary_key}: {previous} / {primary}"
    owner_by_alias[primary_key] = primary
    for alias in parts[1:]:
        if not alias:
            continue
        assert alias == alias.lower() and not any(ch in alias for ch in " -_()[]"), f"Alias must be normalized for Guovin: {alias}"
        previous = owner_by_alias.get(alias)
        assert previous in (None, primary), f"Alias collision {alias}: {previous} / {primary}"
        owner_by_alias[alias] = primary
assert primary_names == set(channels), f"Missing aliases for: {sorted(set(channels)-primary_names)}"

def upstream_format_name(value):
    value = re.sub(r"[пј€(]\s*\+(\d+)\s*[пј‰)]", r"+\1", value)
    value = normalizer.sub("", value)
    for old, new in (("plus", "+"), ("PLUS", "+"), ("пј‹", "+")):
        value = value.replace(old, new)
    return value.lower()

alias_map = {}
for row in alias_rows:
    parts = [part.strip() for part in row.split(",")]
    primary = parts[0]
    for key in [upstream_format_name(primary), *parts[1:]]:
        alias_map[key] = primary

for source_label, expected in (
    ("НТВ (+4)", "НТВ +4"),
    ("МИР (+4)", "МИР +4"),
    ("Россия 1 HD (+4)", "Россия 1 HD +4"),
):
    assert alias_map.get(upstream_format_name(source_label)) == expected, (
        f"Regional suffix mapping failed: {source_label}"
    )
blacklist = (ROOT / "config/blacklist.txt").read_text(encoding="utf-8").lower()
assert "zabava-htlive.cdn.ngenix.net" in blacklist, "Wink/Zabava blocked host missing from blacklist"
assert "zabava.cdn.ngenix.net" in blacklist, "Zabava blocked host missing from blacklist"

assert (ROOT / "utils/tools.py").is_file(), "Guovin utility package is incomplete"

cfg_text = (ROOT / "config/config.ini").read_text(encoding="utf-8")
for required in ("open_subscribe = True", "open_speed_test = True",
                 "open_filter_resolution = False", "open_filter_speed = False",
                 "open_auto_disable_source = False", "open_rtmp = False"):
    assert required in cfg_text, f"Required engine setting missing: {required}"

print(f"OK: {len(channels)} channels, {len(sources)} sources, {len(alias_rows)} alias rows.")


