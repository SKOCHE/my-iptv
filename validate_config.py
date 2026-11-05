import json
from pathlib import Path
p = Path(__file__).with_name('channels.json')
data = json.loads(p.read_text(encoding='utf-8'))
assert len(data) == 41, f'Expected 41 channels, got {len(data)}'
assert len({x['name'] for x in data}) == 41, 'Duplicate channel names'
for x in data:
    assert x.get('name') and isinstance(x.get('aliases', []), list)
print('OK: 41 unique channels in channels.json')
