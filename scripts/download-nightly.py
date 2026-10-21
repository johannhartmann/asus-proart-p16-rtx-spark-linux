#!/usr/bin/env python3
"""Download and verify the ARM64 Omarchy Nightly ISO."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request
root = Path(__file__).resolve().parents[1] / 'build/iso'
root.mkdir(parents=True, exist_ok=True)
manifest_url = 'https://nightly.omarchy.org/edge-aarch64/latest.json'
with urllib.request.urlopen(manifest_url) as response:
    manifest = json.load(response)
if not (manifest['arch'] == 'aarch64' and manifest['channel'] == 'edge-aarch64'):
    raise ValueError('Validierung fehlgeschlagen')
url = urllib.parse.urlsplit(manifest['url'])
if not (url.scheme == 'https' and url.netloc == 'nightly.omarchy.org'):
    raise ValueError('Validierung fehlgeschlagen')
if not (url.path.startswith('/edge-aarch64/') and url.path.endswith('-aarch64.iso')):
    raise ValueError('Validierung fehlgeschlagen')
name = Path(url.path).name
part = root / (name + '.part')
subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--continue-at', '-', '--output', str(part), manifest['url']], check=True)
if not part.stat().st_size == manifest['size']:
    raise ValueError('Falsche Downloadgröße')
with part.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if not actual == manifest['sha256']:
    raise ValueError('SHA-256 stimmt nicht')
part.rename(root / name)
(root / (name + '.json')).write_text(json.dumps(manifest, indent=2) + '\n')
print('ISO geprüft:', root / name)
