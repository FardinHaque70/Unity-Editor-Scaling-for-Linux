#!/usr/bin/env python3
"""Collect redistribution notices in an ephemeral Ubuntu AppImage builder.

Usage: collect_licenses.py APPDIR EXTRACTED_SOURCES PROJECT
Run after collect_runtime.py and before stripping/removing development files.
No system files are changed. Unknown ELF provenance is a build failure.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

APP_ROOT = Path('usr/share/unity-editor-scaling')
STATIC_PACKAGES = ('libssl-dev', 'libjson-c-dev', 'libc6-dev', 'zlib1g-dev')
PYTHON_PACKAGES = ('python3.10-minimal', 'libpython3.10-minimal', 'libpython3.10-stdlib', 'python3-cairo', 'ca-certificates')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def elf(path):
    try:
        with path.open('rb') as stream:
            return stream.read(4) == b'\x7fELF'
    except OSError:
        return False


def copy_notice(source, destination):
    if not source.is_file():
        raise RuntimeError('Required notice missing: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def installed_sources(sources, source_lock):
    result = {}
    for name in source_lock:
        info = sources.parent / ('build-' + name) / 'meson-info/intro-installed.json'
        if not info.is_file():
            raise RuntimeError('Meson installation inventory missing: ' + str(info))
        for target in json.loads(info.read_text()).values():
            for item in target if isinstance(target, list) else [target]:
                if isinstance(item, str):
                    result[str(Path(item).absolute())] = name
    return result


def package_owner(path):
    found = subprocess.run(['dpkg-query', '--search', str(path)], text=True, capture_output=True)
    for line in found.stdout.splitlines():
        if ': ' in line:
            package, owned = line.rsplit(': ', 1)
            if owned == str(path):
                return package
    raise RuntimeError('No Ubuntu package owns copied runtime: ' + str(path))


def host_candidates(relative):
    # collect_runtime flattens the architecture-specific library directory.
    values = [Path('/') / relative]
    if relative.parts[:2] == ('usr', 'lib'):
        values += [Path('/usr/lib/x86_64-linux-gnu') / relative.name,
                   Path('/lib/x86_64-linux-gnu') / relative.name]
    if 'site-packages' in relative.parts:
        index = relative.parts.index('site-packages')
        values.append(Path('/usr/lib/python3/dist-packages').joinpath(*relative.parts[index + 1:]))
    return list(dict.fromkeys(values))


def collect_elf_provenance(appdir, source_owners):
    inventory = []
    packages = set(STATIC_PACKAGES + PYTHON_PACKAGES)
    for path in sorted(appdir.rglob('*')):
        if not path.is_file() or not elf(path):
            continue
        relative = path.relative_to(appdir)
        if str(path.absolute()) in source_owners:
            origin = {'source_build': source_owners[str(path.absolute())]}
        elif relative.is_relative_to(APP_ROOT / 'native') or relative.is_relative_to(APP_ROOT / 'libexec'):
            origin = {'source_build': 'unity-editor-scaling', 'static_dependency_packages': list(STATIC_PACKAGES)}
        else:
            expected = digest(path)
            host = next((item for item in host_candidates(relative) if item.is_file() and digest(item) == expected), None)
            if host is None:
                raise RuntimeError('Unknown ELF provenance: ' + str(relative))
            package = package_owner(host)
            packages.add(package)
            origin = {'ubuntu_package': package, 'source_path': str(host)}
        inventory.append(dict(path=str(relative), sha256=digest(path), **origin))
    # Copied GSettings schemas also require their package notices.
    schemas = appdir / 'usr/share/glib-2.0/schemas'
    for path in sorted(schemas.glob('*.xml')):
        host = Path('/usr/share/glib-2.0/schemas') / path.name
        if host.is_file() and digest(path) == digest(host):
            packages.add(package_owner(host))
        elif str(path.absolute()) not in source_owners:
            raise RuntimeError('Unknown schema provenance: ' + path.name)
    return inventory, packages


def collect_package_notices(packages, output):
    records = []
    for package in sorted(packages):
        row = subprocess.check_output(['dpkg-query', '--show', '--showformat=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n', package], text=True).strip().split('\t')
        if len(row) != 4:
            raise RuntimeError('Invalid package metadata: ' + package)
        binary, version, source, source_version = row
        source = source or binary.split(':')[0]
        source_version = source_version or version
        copyright_file = Path('/usr/share/doc') / binary.split(':')[0] / 'copyright'
        copy_notice(copyright_file, output / 'ubuntu' / binary.replace(':', '_') / 'copyright')
        records.append(dict(package=binary, version=version, source_package=source, source_version=source_version,
                            source_url='https://launchpad.net/ubuntu/+source/' + source + '/' + source_version))
    common = Path('/usr/share/common-licenses')
    if not common.is_dir():
        raise RuntimeError('Ubuntu common license texts missing')
    shutil.copytree(common, output / 'common-licenses', dirs_exist_ok=True)
    return records


def collect_source_notices(sources, source_lock, output):
    records = []
    for name, entry in source_lock.items():
        tree = sources / (name + '-' + entry['version'])
        if not tree.is_dir():
            raise RuntimeError('Pinned source tree missing: ' + str(tree))
        found = 0
        for path in sorted(tree.rglob('*')):
            upper = path.name.upper()
            notice_name = any(upper == stem or upper.startswith(stem + '.')
                              for stem in ('COPYING', 'LICENSE', 'LICENCE', 'NOTICE', 'AUTHORS'))
            in_license_directory = any(part.upper() == 'LICENSES' for part in path.relative_to(tree).parts[:-1])
            if not path.is_file() or not (notice_name or in_license_directory):
                continue
            # Follow COPYING links only inside the already verified source tree.
            if not path.resolve().is_relative_to(tree.resolve()):
                raise RuntimeError('Notice symlink leaves source tree: ' + str(path))
            copy_notice(path, output / 'upstream' / name / path.relative_to(tree))
            found += 1
        if found == 0:
            raise RuntimeError('Pinned source has no notices: ' + name)
        records.append(dict(component=name, notices=found, **entry))
    return records


def collect_remote_notices(project, output, fetch=urllib.request.urlopen):
    lock = json.loads((project / 'packaging/notices.lock.json').read_text())
    for name, entry in lock.items():
        with fetch(entry['url'], timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise RuntimeError('Pinned license/provenance text mismatch: ' + name)
        destination = output / 'appimage' / (name + '.txt')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return lock


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('appdir', type=Path)
    parser.add_argument('sources', type=Path)
    parser.add_argument('project', type=Path)
    args = parser.parse_args(argv)
    appdir, sources, project = [item.resolve() for item in (args.appdir, args.sources, args.project)]
    output = appdir / APP_ROOT / 'resources/licenses'
    output.mkdir(parents=True, exist_ok=True)
    source_lock = json.loads((project / 'packaging/sources.lock.json').read_text())
    owners = installed_sources(sources, source_lock)
    elf_records, packages = collect_elf_provenance(appdir, owners)
    package_records = collect_package_notices(packages, output)
    source_records = collect_source_notices(sources, source_lock, output)
    notices = collect_remote_notices(project, output)
    for name in ('sources.lock.json', 'tools.lock.json', 'notices.lock.json', 'build_appimage.sh', 'collect_runtime.py', 'collect_licenses.py'):
        copy_notice(project / 'packaging' / name, output / 'build-inputs' / name)
    copy_notice(project / 'docs/THIRD_PARTY.md', output / 'THIRD_PARTY.md')
    # NOTICE refers to this path; preserve it in the application root as well.
    copy_notice(project / 'docs/THIRD_PARTY.md', appdir / APP_ROOT / 'docs/THIRD_PARTY.md')
    revision = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    report = dict(schema=1, application_source_revision=revision, ubuntu_packages=package_records,
                  source_builds=source_records, appimage_notices=notices, elf_files=elf_records,
                  elf_hash_stage='before strip; final payload hashes are covered by the signed release manifest',
                  runtime_provenance_note='Official pinned Type-2 binary; source recipe uses Alpine 3.21 packages whose exact transitive versions are not fixed by upstream. Included notices do not assert those package versions.')
    (output / 'inventory.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('Collected notices:', len(package_records), 'Ubuntu packages,', len(source_records), 'source builds,', len(notices), 'AppImage provenance files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
