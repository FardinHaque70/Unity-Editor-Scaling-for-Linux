#!/usr/bin/env python3
"""Bounded download retries with immutable SHA-256 admission, for CI only."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('lock', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--extract', action='store_true')
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for name, entry in json.loads(args.lock.read_text()).items():
        target = args.destination / (name + '.tar.xz' if args.extract else name)
        temporary = target.with_name(target.name + '.partial')
        for attempt in range(4):
            try:
                sha = hashlib.sha256()
                count = 0
                request = urllib.request.Request(entry['url'], headers={'User-Agent': 'Unity-Editor-Scaling-CI'})
                with urllib.request.urlopen(request, timeout=30) as response, temporary.open('wb') as output:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > 512 * 1024 * 1024:
                            raise ValueError('Download size limit exceeded: ' + name)
                        sha.update(chunk)
                        output.write(chunk)
                if sha.hexdigest() != entry['sha256']:
                    raise ValueError('Pinned source/tool hash mismatch: ' + name)
                temporary.replace(target)
                break
            except (OSError, urllib.error.URLError):
                temporary.unlink(missing_ok=True)
                if attempt == 3:
                    raise
                print('Retrying pinned download:', name, flush=True)
                time.sleep(2 ** attempt)
        if args.extract:
            with tarfile.open(target) as archive:
                for member in archive.getmembers():
                    if member.name.startswith('/') or '..' in Path(member.name).parts:
                        raise ValueError('Unsafe pinned source archive')
                archive.extractall(args.destination)
        else:
            target.chmod(0o755)
        print('Verified pinned download:', name, flush=True)


if __name__ == '__main__':
    main()
