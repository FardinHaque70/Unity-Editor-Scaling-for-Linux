#!/usr/bin/env python3
"""Private production-update worker; invoked only by check_production_update.py.

Imports the application shipped inside the extracted release, never source-tree
code. No production signing key or fabricated public release is used.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

if (not os.environ.get('UNITY_SCALE_QA_SESSION') or
        not os.environ.get('QA_UPDATE_ROOT', '').startswith('/tmp/unity-production-update-')):
    raise SystemExit('Use qa/check_production_update.py')
sys.path.insert(0, os.environ['QA_APP_ROOT'])
from unity_scale import core, updates
from unity_scale.private_store import atomic_json


def main():
    root = Path(os.environ['QA_UPDATE_ROOT'])
    output = Path(os.environ['QA_UPDATE_RESULT'])
    record = {'status': 'FAIL', 'mode': os.environ['QA_UPDATE_MODE'],
              'source': 'anonymous GitHub release API and pinned production signing key',
              'starting_version': 'simulated previous prerelease; current artifact plus inert trailer'}
    try:
        store = core.Store()
        with store.locked():
            pass
        if core.discover_editors(store=store):
            raise RuntimeError('Private HOME unexpectedly discovers an installed Editor; refusing any native integration')
        target = store.data_dir / 'application.AppImage'
        shutil.copyfile(os.environ['QA_UPDATE_IMAGE'], target)
        with target.open('ab') as stream:
            stream.write(b'\nQA simulated previous managed image; disposable only\n')
        target.chmod(0o700)
        old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        atomic_json(store.state_dir / 'installation.json', dict(schema=2, version='0.3.0-rc.1',
            image=str(target), image_sha256=old_hash))
        selection_transport = None
        if os.environ.get('QA_UPDATE_RELEASE_CACHE'):
            metadata = Path(os.environ['QA_UPDATE_RELEASE_CACHE']).read_bytes()
            releases = json.loads(metadata)
            if not isinstance(releases, list):
                raise RuntimeError('Cached public release-list metadata must be an array')
            browser_assets = {asset['url']: asset['browser_download_url']
                for item in releases for asset in item.get('assets', [])}
            class PublicMetadataCache:
                def open(self, url):
                    if url == updates.API + '?per_page=100&page=1':
                        return io.BytesIO(metadata)
                    if url not in browser_assets:
                        raise RuntimeError('Unexpected URL in qualified public metadata test')
                    return updates.GitHubTransport().open(browser_assets[url])
            selection_transport = PublicMetadataCache()
            record.update(source='qualified public metadata snapshot and anonymous browser assets',
                metadata_acquisition='authenticated gh public release-list snapshot',
                metadata_sha256=hashlib.sha256(metadata).hexdigest(),
                anonymous_release_API_selection='NOT PASSED: live API returned HTTP403, quota exhausted',
                public_asset_transport='shipped GitHubTransport, API URLs mapped to public browser URLs from metadata',
                production_verification='unmodified signature, hash, staging, helper, GUI health and rollback paths')
        # Stable users must not be offered this release candidate.
        stable = updates.check(current='0.3.0', transport=selection_transport)
        if stable is not None and '-rc.' in stable.version:
            raise RuntimeError('Stable client was offered a prerelease')
        release = updates.check(current='0.3.0-rc.1', transport=selection_transport)
        if release is None or release.version != core.VERSION:
            raise RuntimeError('The expected public prerelease is not available')
        record.update(version=release.version, url=release.url,
                      stable_selection=stable.version if stable else None,
                      previous_sha256=old_hash, expected_sha256=release.sha256,
                      expected_size=release.size)
        progress = []
        cache = root / 'verified-public-download.AppImage'
        if record['mode'] == 'rollback':
            class VerifiedCache:
                def open(self, url):
                    if url != release.url:
                        raise RuntimeError('Unexpected cached payload URL')
                    return cache.open('rb')
            transport = VerifiedCache()
            record['payload_download'] = 'reuse verified public payload from successful case'
        else:
            transport = selection_transport
            record['payload_download'] = 'anonymous GitHub HTTPS browser asset' if selection_transport else 'anonymous GitHub HTTPS download'
        prepared = updates.prepare(release, target=target, transport=transport,
            progress=lambda got,total: progress.append((got,total)))
        if not cache.exists():
            shutil.copyfile(prepared.staged, cache)
        record.update(downloaded=progress[-1][0] if progress else 0,
                      target=str(target), stage=str(prepared.directory),
                      state_dir=str(store.state_dir), data_dir=str(store.data_dir))
        os.environ['APPIMAGE'] = str(target)
        if record['mode'] == 'rollback':
            # A controlled GUI startup failure tests the actual helper rollback;
            # no driver or desktop configuration is touched.
            os.environ['GDK_BACKEND'] = 'nonexistent-unity-scale-qa-backend'
        helper_pid = updates.restart(prepared)
        record.update(status='HELPER_STARTED', helper_pid=helper_pid)
        output.write_text(json.dumps(record, indent=2) + '\n')
        return 0
    except Exception as exc:
        record['error'] = str(exc)
        output.write_text(json.dumps(record, indent=2) + '\n')
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
