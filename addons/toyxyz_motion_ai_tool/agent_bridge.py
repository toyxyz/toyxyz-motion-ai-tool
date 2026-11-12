"""Opt-in local command transport. Blender evaluates requests on its main thread."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
import time
import traceback

import bpy

from . import agent_commands, rig_store


ROOT = Path(gettempdir()) / 'toyxyz-motion-ai-agent'
PROTOCOL = 1
MAX_REQUEST = 256 * 1024
RETRY_WINDOW = 600
MAX_REPLIES = 4096
_session = None
_edit_request = None
_edit_response = None


def enabled():
    return _session is not None


def publish(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def start(context):
    global _session
    if enabled():
        raise ValueError('The agent bridge is already running.')
    if not context.window or not context.scene:
        raise ValueError('Open a Blender scene to enable the agent bridge.')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = TemporaryDirectory(prefix='session-', dir=ROOT, ignore_cleanup_errors=True)
    path = Path(directory.name)
    try:
        rig_store.ensure(context.scene)
        metadata = dict(protocol=PROTOCOL, id=path.name, pid=os.getpid(), scene=context.scene.name,
                        file=bpy.data.filepath, commands=sorted(agent_commands.COMMANDS))
        publish(path / 'session.json', metadata)
    except BaseException:
        directory.cleanup()
        raise
    _session = dict(directory=directory, path=path, window=context.window.as_pointer(),
                    scene=context.scene.as_pointer(), heartbeat=0., replies={})
    return metadata


def stop():
    global _session
    if enabled():
        session = _session
        _session = None
        session['directory'].cleanup()


def failure(exc):
    return dict(ok=False, error=str(exc) or type(exc).__name__)


def dispatch(context, command, args):
    global _edit_request, _edit_response
    if command not in agent_commands.UNDOABLE:
        return dict(ok=True, result=agent_commands.run(context, command, args))
    _edit_request = command, args
    _edit_response = None
    try:
        bpy.ops.toyxyz_motion_ai_tool.agent_edit()
        if _edit_response is None:
            raise ValueError('Blender could not run the edit in this context.')
        return _edit_response
    finally:
        _edit_request = _edit_response = None


def handle(context, request, session_id, request_id, replies):
    if not isinstance(request, dict) or request.get('protocol') != PROTOCOL or request.get('session') != session_id:
        raise ValueError('This request does not match the current agent session.')
    now = time.time()
    expires = request.get('expires')
    if type(expires) not in (int, float) or not now <= expires <= now + 602:
        raise ValueError('The request expired. Send it again.')
    command, args = request.get('command'), request.get('args')
    if not isinstance(command, str) or not isinstance(args, dict):
        raise ValueError('Supply a command name and a JSON object of arguments.')
    fingerprint = json.dumps([command, args], sort_keys=True, separators=(',', ':'), allow_nan=False)
    if request_id in replies:
        _, previous, result = replies[request_id]
        if previous != fingerprint:
            raise ValueError('This request ID was already used with different arguments or a different command.')
        return result
    if len(replies) >= MAX_REPLIES:
        raise ValueError('The agent retry cache is full. Wait for older requests to expire.')
    try:
        result = dispatch(context, command, args)
    except (ValueError, RuntimeError, TypeError, OSError) as exc:
        result = failure(exc)
    replies[request_id] = time.monotonic() + RETRY_WINDOW, fingerprint, result
    return result


def tick(context):
    """Process a single request per tick from the Blender window that enabled access."""
    if not enabled():
        return
    session = _session
    window = next((window for window in context.window_manager.windows if window.as_pointer() == session['window']), None)
    if window is None or window.scene.as_pointer() != session['scene']:
        stop()
        return
    path = session['path']
    try:
        now = time.monotonic()
        if now >= session['heartbeat']:
            os.utime(path / 'session.json', None)
            session['heartbeat'] = now + 2.
            for request_id, (deadline, _, _) in list(session['replies'].items()):
                if deadline <= now:
                    del session['replies'][request_id]
            for response in path.glob('*.response.json'):
                if time.time() - response.stat().st_mtime > 60:
                    response.unlink(missing_ok=True)
        request_path = next(path.glob('*.request.json'), None)
        if request_path is None:
            return
        request_id = request_path.name.removesuffix('.request.json')
        if len(request_id) != 32 or any(character not in '0123456789abcdef' for character in request_id):
            request_path.unlink(missing_ok=True)
            return
        try:
            with request_path.open('rb') as stream:
                raw = stream.read(MAX_REQUEST + 1)
            if len(raw) > MAX_REQUEST:
                raise ValueError('The command request is too large.')
            # Claim the file before dispatching. The session cache handles retries.
            request_path.unlink()
            with context.temp_override(window=window, area=None, region=None):
                result = handle(bpy.context, json.loads(raw), path.name, request_id, session['replies'])
        except Exception as exc:
            request_path.unlink(missing_ok=True)
            if not isinstance(exc, (ValueError, RuntimeError, TypeError, OSError)):
                traceback.print_exc()
            result = failure(exc)
        publish(path / (request_id + '.response.json'), result)
    except FileNotFoundError:
        if not path.is_dir() or not (path / 'session.json').is_file():
            stop()
    except OSError:
        traceback.print_exc()
        if not path.is_dir() or not (path / 'session.json').is_file():
            stop()


class TOYXYZ_OT_agent_edit(bpy.types.Operator):
    bl_idname = 'toyxyz_motion_ai_tool.agent_edit'
    bl_label = 'Motion AI Agent Edit'
    bl_options = {'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _edit_request is not None

    def execute(self, context):
        global _edit_response
        command, args = _edit_request
        try:
            _edit_response = dict(ok=True, result=agent_commands.run(context, command, args))
        except Exception as exc:
            if not isinstance(exc, (ValueError, RuntimeError, TypeError, OSError)):
                traceback.print_exc()
            _edit_response = failure(exc)
            return {'CANCELLED'}
        return {'FINISHED'}


class TOYXYZ_OT_agent_bridge(bpy.types.Operator):
    bl_idname = 'toyxyz_motion_ai_tool.agent_bridge'
    bl_label = 'Toggle AI Agent Control'
    bl_description = 'Allow or stop local AI agent commands for the current Blender scene'

    def execute(self, context):
        try:
            if enabled():
                stop()
            else:
                start(context)
        except (ValueError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


CLASSES = (TOYXYZ_OT_agent_edit, TOYXYZ_OT_agent_bridge)
