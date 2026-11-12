"""Standard-library-only verification; also runs before a staged runtime is activated."""
import argparse
import concurrent.futures
import ctypes
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def checked_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Invalid runtime path: ' + name)
    return path


def verify(environment, lock_path, full=False):
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    manifest = environment / 'environment.files.json'
    if digest(manifest) != lock['environment_manifest_sha256']:
        raise RuntimeError('Runtime manifest checksum mismatch')
    records = json.loads(manifest.read_text(encoding='utf-8'))
    metadata = json.loads((environment / 'environment.json').read_text(encoding='utf-8'))
    if metadata['runtime_id'] != lock['runtime_id'] or records['runtime_id'] != lock['runtime_id']:
        raise RuntimeError('Runtime version mismatch')
    files = records['files'] if full else lock['critical_files']

    def check(record):
        path = checked_path(environment, record['path'])
        if not path.is_file() or path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            return record['path']
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        errors = [error for error in pool.map(check, files) if error]
    if errors:
        raise RuntimeError('Runtime verification failed: ' + ', '.join(errors[:10]))
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment):
        raise RuntimeError('Python isolation is disabled')
    if ctypes.windll.kernel32.GetACP() != 65001:
        raise RuntimeError('Native UTF-8 host is disabled')
    return dict(status='passed', runtime_id=lock['runtime_id'], full=full, checked_files=len(files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--environment', required=True, type=Path)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.environment, args.lock, args.full)), flush=True)
