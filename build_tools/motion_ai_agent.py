"""Send JSON commands to an opted-in Motion AI session in an open Blender."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import gettempdir
import time
import uuid


ROOT = Path(gettempdir()) / 'toyxyz-motion-ai-agent'
PROTOCOL = 1


def sessions():
    result = []
    for metadata in ROOT.glob('session-*/session.json'):
        try:
            if time.time() - metadata.stat().st_mtime > 20:
                continue
            session = json.loads(metadata.read_text(encoding='utf-8'))
            if session['protocol'] == PROTOCOL and session['id'] == metadata.parent.name:
                result.append(session)
        except (OSError, TypeError, ValueError, KeyError):
            continue
    return sorted(result, key=lambda item: item['id'])


def send(command, args, session, timeout, *, request_id=None):
    directory = ROOT / session['id']
    request_id = request_id if request_id is not None else uuid.uuid4().hex
    if len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
        raise ValueError('The request ID must contain 32 lowercase hexadecimal characters.')
    request = directory / f'{request_id}.request.json'
    response = directory / f'{request_id}.response.json'
    temporary = request.with_suffix('.tmp')
    payload = json.dumps(dict(protocol=PROTOCOL, session=session['id'], expires=time.time() + timeout,
                              command=command, args=args), ensure_ascii=False, allow_nan=False)
    try:
        response.unlink(missing_ok=True)
        temporary.write_text(payload, encoding='utf-8')
        temporary.replace(request)
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if response.is_file():
                return json.loads(response.read_text(encoding='utf-8'))
            if not (directory / 'session.json').is_file():
                raise ValueError('Blender closed the agent connection.')
            time.sleep(.075)
        if request.is_file():
            raise ValueError('Blender did not pick up the request before timeout.')
        raise ValueError(f'Blender started the request but has not replied. Retry with --request-id {request_id} and the same command and arguments.')
    finally:
        for path in (temporary, request, response):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('list', help='List enabled Blender agent sessions and their commands')
    call = sub.add_parser('call', help='Send a command to an open Blender')
    call.add_argument('command')
    call.add_argument('--session', help='Exact session ID from list; optional when only one session is enabled')
    call.add_argument('--timeout', type=int, default=30, help='Seconds to wait for the command reply (1–600)')
    call.add_argument('--request-id', help='Reuse an ID to retry the same command in the same session')
    args_input = call.add_mutually_exclusive_group()
    args_input.add_argument('--args', default='{}', help='Command arguments as a JSON object')
    args_input.add_argument('--args-file', type=Path, help='UTF-8 JSON arguments file')
    options = parser.parse_args()
    try:
        active = sessions()
        if options.operation == 'list':
            result = dict(ok=True, result=active)
        else:
            if not 1 <= options.timeout <= 600:
                raise ValueError('--timeout must be from 1 to 600 seconds.')
            chosen = [item for item in active if options.session is None or item['id'] == options.session]
            if not chosen:
                raise ValueError('No matching session. Click Enable Agent Control in Blender, then run list.')
            if len(chosen) > 1:
                raise ValueError('More than one session is enabled. Run list and specify --session.')
            raw = options.args_file.read_text(encoding='utf-8-sig') if options.args_file else options.args
            args = json.loads(raw)
            if not isinstance(args, dict):
                raise ValueError('Command arguments must be a JSON object.')
            result = send(options.command, args, chosen[0], options.timeout, request_id=options.request_id)
    except (OSError, ValueError) as exc:
        result = dict(ok=False, error=str(exc))
    print(json.dumps(result, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
