import json, pathlib, shutil
p=pathlib.Path(__file__).parent
channels=json.loads((p/"channels.json").read_text(encoding="utf-8"))
assert len(channels)==41, f"Expected 41 channels, got {len(channels)}"
names=[x["name"] for x in channels]
assert len(set(names))==41, "Duplicate channel names"
assert all(x.get("aliases") for x in channels), "Missing aliases"
print(f"Manifest OK: {len(names)} unique channel names")
print("FFmpeg installed:", bool(shutil.which("ffmpeg")))
