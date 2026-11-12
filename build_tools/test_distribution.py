"""Local end-to-end distribution test. No GitHub upload or external download."""
import argparse
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', required=True, type=Path)
    parser.add_argument('--test-root', required=True, type=Path)
    parser.add_argument('--with-models', action='store_true', help='Link local model fixtures and run GPU regression')
    args = parser.parse_args()
    target = args.test_root.resolve()
    # Never remove or overwrite an existing installation.
    if target.exists():
        raise RuntimeError('Test target must not exist: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which('git.exe')
    if not git:
        raise RuntimeError('Developer test requires Git')
    subprocess.run([git, 'clone', '--no-hardlinks', str(ROOT), str(target)], check=True)
    assert not (target / 'python_embeded').exists() and not (target / 'models').exists()
    (target / 'logs').mkdir()
    report = dict(status='running', source=str(ROOT), clone=str(target), checks=[], requests=[], uploaded=False)
    report_path = ROOT / 'results/source_runtime_separation_report.json'
    clean_env = dict(os.environ, PATH='C:/Windows/System32;C:/Windows', CUDA_PATH='', CUDA_HOME='',
                     PYTHONHOME='invalid-system-python', PYTHONPATH='invalid-system-python')
    lock = json.loads((target / 'manifests/runtime.lock.json').read_text(encoding='utf-8'))
    archive_dir = args.runtime_dir.resolve()
    parts = {part['name']: archive_dir / part['name'] for part in lock['parts']}
    assert parts and all(p.is_file() for p in parts.values())

    def batch(name, arguments='', success=True, env=clean_env, timeout=900):
        log = target / 'logs' / (name + '_' + str(time.time_ns()) + '.log')
        command = f'"C:\\Windows\\System32\\cmd.exe" /d /v:off /s /c ""{target / name}" {arguments}"'
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=target, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        if (result.returncode == 0) != success:
            raise RuntimeError(f'Unexpected {name} return {result.returncode}; see {log}')
        return log

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *values):
            pass

        def do_GET(self):
            name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path.rsplit('/', 1)[-1])
            if name not in parts:
                self.send_error(404)
                return
            path = parts[name]
            size = path.stat().st_size
            start = 0
            header = self.headers.get('Range')
            if header:
                match = re.fullmatch(r'bytes=(\d+)-', header)
                if not match or int(match[1]) >= size:
                    self.send_error(416)
                    return
                start = int(match[1])
            status = 206 if header else 200
            report['requests'].append(dict(name=name, status=status, start=start))
            self.send_response(status)
            self.send_header('Content-Length', str(size - start))
            if header:
                self.send_header('Content-Range', f'bytes {start}-{size-1}/{size}')
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with path.open('rb') as stream:
                stream.seek(start)
                shutil.copyfileobj(stream, self.wfile, 1024**2)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        failed = batch('install.cmd', '-RuntimeOnly', success=False)
        assert '아직 배포 주소가 등록되지 않았습니다' in failed.read_text(encoding='utf-8')
        report['checks'].append('Unpublished runtime URL fails with an actionable message')
        downloads = target / 'downloads'
        downloads.mkdir(exist_ok=True)
        first = next(iter(parts))
        corrupt = downloads / first
        corrupt.write_bytes(b'corrupt test volume')
        failed = batch('install.cmd', '-RuntimeOnly', success=False)
        assert '손상된 압축 파일입니다' in failed.read_text(encoding='utf-8')
        corrupt.unlink()
        assert not report['requests'] and not (target / 'python_embeded').exists()
        report['checks'].append('Corrupt local archive rejected before extraction')
        seed_bytes = 8 * 1024**2
        with parts[first].open('rb') as stream:
            (downloads / (first + '.partial')).write_bytes(stream.read(seed_bytes))
        batch('install.cmd', f'-RuntimeOnly -RuntimeBaseUrl http://127.0.0.1:{server.server_port}')
        assert any(r['status'] == 206 and r['start'] == seed_bytes for r in report['requests'])
        assert len(report['requests']) == len(parts)
        assert (target / 'python_embeded/packages/common/torch/__init__.py').is_file()
        assert not (target / 'packages').exists()
        report['checks'].append('Actual split download, HTTP 206 resume, SHA-256, extraction and full runtime verification without system Python')
        count = len(report['requests'])
        batch('install.cmd', '-RuntimeOnly')
        assert len(report['requests']) == count
        report['checks'].append('Existing matching runtime reused offline, without another download')
        invalid_lock = dict(lock, runtime_id='deliberately-wrong-runtime-for-test')
        mismatch = target / '.install/version-mismatch.json'
        mismatch.write_text(json.dumps(invalid_lock), encoding='utf-8')
        result = subprocess.run([str(target / 'python_embeded/python.exe'), '-X', 'utf8',
                                 str(target / 'bootstrap/check_runtime.py'), '--environment', str(target / 'python_embeded'),
                                 '--lock', str(mismatch)], capture_output=True)
        assert result.returncode != 0 and b'Runtime version mismatch' in result.stderr
        report['checks'].append('Mismatched runtime version rejected')
        settings = target / 'settings.json'
        settings.write_text(json.dumps(dict(precision='bf16',engines=['kimodo','ardy'],user_note='Enabled자 설정 보존')), encoding='utf-8')
        saved_settings = settings.read_bytes()
        subprocess.run([git, '-C', str(target), 'pull', '--ff-only'], check=True)
        batch('update.cmd', '-RuntimeOnly', env=dict(clean_env, PATH=os.environ['PATH']))
        assert settings.read_bytes() == saved_settings
        report['checks'].append('Local git clone, git pull --ff-only and update.cmd')
        if args.with_models:
            # Same-volume NTFS hardlinks avoid copying 30 GB of immutable test fixtures.
            # Every runtime import and native-library path must still be inside the clone.
            def link(source, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, destination)
            for folder in ('models', 'testdata'):
                for source in (ROOT / folder).rglob('*'):
                    if source.is_file():
                        link(source, target / source.relative_to(ROOT))
            models = json.loads((target / 'manifests/models.lock.json').read_text(encoding='utf-8'))
            for asset in models['assets']:
                link(ROOT / asset['path'], target / asset['path'])
            batch('install.cmd', '-Precision all')
            report['checks'].append('All cached model profiles and SOMA assets adopted without an external download')
            with (target / 'logs/clone_selftest.log').open('wb') as output:
                subprocess.run([str(target / 'python_embeded/python.exe'), '-X', 'utf8', '-u',
                                str(target / 'runtime/entry.py'), 'selftest', '--precision', 'nf4'],
                               cwd=target, env=clean_env, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=1200)
            verification = json.loads((target / 'results/portable_verification.json').read_text(encoding='utf-8'))
            assert verification['status'] == 'passed'
            for engine in ('kimodo', 'ardy', 'motionbricks'):
                doctor = json.loads((target / f'results/doctor_{engine}.json').read_text(encoding='utf-8'))
                assert doctor['windows_process_code_page'] == 65001 and not doctor['external_development_runtime_dlls']
            report['gpu_verification'] = verification
            report['checks'].append('Mixed Unicode/metacharacter clone: all three CUDA engines, shared NF4 generation and MotionBricks chained generation')
            with (target / 'logs/clone_viewer.log').open('wb') as output:
                subprocess.run([str(target / 'python_embeded/python.exe'), '-X', 'utf8', '-u',
                                str(target / 'runtime/entry.py'), 'motionbricks', '--engine', 'motionbricks', '--test'],
                               cwd=target, env=clean_env, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
            report['checks'].append('MotionBricks native viewer: three frames and clean exit')
        status = subprocess.check_output([git, '-C', str(target), 'status', '--porcelain']).decode('utf-8')
        assert not status, status
        report['checks'].append('Git stays clean after runtime/model installation and execution')
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(status=report['status'], clone=str(target), checks=report['checks']), ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
