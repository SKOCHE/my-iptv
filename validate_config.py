import json,pathlib
p=pathlib.Path(__file__).parent
x=json.loads((p/"channels.json").read_text(encoding="utf-8"))
assert len(x)==41
assert len({c["name"] for c in x})==41
print("OK: 41 unique channel entries")
