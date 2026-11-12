"""Build release volumes locally. This command never uploads anything."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'distribution')
    args = parser.parse_args()
    lock_path = ROOT / 'manifests/runtime.lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    env = ROOT / 'python_embeded'
    if digest(env / 'environment.files.json') != lock['environment_manifest_sha256']:
        raise RuntimeError('Rebuild the environment manifest before packaging')
    # Fail rather than accidentally including an unrecorded package or secret.
    manifest = json.loads((env / 'environment.files.json').read_text(encoding='utf-8'))
    expected = {file['path'] for file in manifest['files']} | {'environment.files.json'}
    actual = {p.relative_to(env).as_posix() for p in env.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}
    if actual != expected:
        raise RuntimeError('Unexpected runtime files: ' + repr(sorted(actual ^ expected)[:10]))
    tool = ROOT / lock['extractor']['path']
    if digest(tool) != lock['extractor']['sha256']:
        raise RuntimeError('7-Zip checksum mismatch')
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output.resolve() / lock['archive_base']
    if list(archive.parent.glob(archive.name + '*')):
        raise RuntimeError('Output already exists; choose an empty output directory')
    subprocess.run([str(tool), 'a', '-t7z', '-mx=9', '-m0=LZMA2:d=256m', '-ms=64g', '-mqs=on',
                    '-myx=9', '-mmt=16', '-v1536m', '-y', str(archive), 'python_embeded',
                    '-xr!__pycache__', '-xr!*.pyc', '-xr!*.pyo', '-bsp0', '-bb0'], cwd=ROOT, check=True)
    parts = sorted(archive.parent.glob(archive.name + '.*'))
    if not parts or any(p.stat().st_size >= 2 * 1024**3 for p in parts):
        raise RuntimeError('Missing or oversized release volumes')
    subprocess.run([str(tool), 't', str(parts[0]), '-bsp0'], check=True)
    lock['parts'] = [dict(name=p.name, bytes=p.stat().st_size, sha256=digest(p)) for p in parts]
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = dict(status='passed', runtime_id=lock['runtime_id'], top_level='python_embeded',
                  raw_bytes=sum((env / name).stat().st_size for name in expected),
                  archive_bytes=sum(p.stat().st_size for p in parts), parts=lock['parts'], uploaded=False)
    (args.output / 'package_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
