"""Blender-held Windows jobs: last owner exit kills the companion and its workers.

No bpy imports. Runtime startup also loads join_from_environment from this file.
The companion must never retain a handle to its outer lifetime job.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import threading
import uuid

ENV='TOYXYZ_BLENDER_LIFETIME_JOB'
_handles={};_bound=set();_lock=threading.RLock()
api=ctypes.WinDLL('kernel32',use_last_error=True)
for name,args,result in [
    ('CreateJobObjectW',[ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
    ('OpenJobObjectW',[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
    ('SetInformationJobObject',[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
    ('AssignProcessToJobObject',[wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
    ('IsProcessInJob',[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)],wintypes.BOOL),
    ('OpenProcess',[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
    ('GetCurrentProcess',[],wintypes.HANDLE),
    ('CloseHandle',[wintypes.HANDLE],wintypes.BOOL),
    ('GetProcessTimes',[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)],wintypes.BOOL),
    ('QueryFullProcessImageNameW',[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
]:
    function=getattr(api,name);function.argtypes=args;function.restype=result

class Limits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),
              ('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active_processes',wintypes.DWORD),
              ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
class Counters(ctypes.Structure):
    _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
class Extended(ctypes.Structure):
    _fields_=[('basic',Limits),('io',Counters),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
              ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]

def check(result):
    if not result:raise ctypes.WinError(ctypes.get_last_error())
    return result

def prefix(root):
    digest=hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()[:16]
    return 'Local\\toyxyz_motion_ai_tool_'+digest+'_'

def keep(name):
    with _lock:
        if name not in _handles:
            handle=check(api.CreateJobObjectW(None,name))
            info=Extended();info.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            try:check(api.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)))
            except BaseException:api.CloseHandle(handle);raise
            _handles[name]=handle
        return _handles[name]

def prepare(root):
    name=prefix(root)+uuid.uuid4().hex;keep(name);return name

def created(handle):
    times=[wintypes.FILETIME() for _ in range(4)]
    check(api.GetProcessTimes(handle,*[ctypes.byref(value) for value in times]))
    return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime

def identity():return created(api.GetCurrentProcess())

def join(name):
    """Borrow a parent-held job, join, and immediately close the borrowed handle."""
    if not re.fullmatch(r'Local\\toyxyz_motion_ai_tool_[a-f0-9]{16}_[a-f0-9]{32}',name):
        raise ValueError('Invalid Blender lifetime job name.')
    handle=check(api.OpenJobObjectW(0x0001|0x0004,False,name)) # ASSIGN_PROCESS | QUERY
    try:
        inside=wintypes.BOOL();check(api.IsProcessInJob(api.GetCurrentProcess(),handle,ctypes.byref(inside)))
        if not inside.value:check(api.AssignProcessToJobObject(handle,api.GetCurrentProcess()))
    finally:api.CloseHandle(handle)

def join_from_environment():
    name=os.environ.get(ENV)
    if name:join(name)

def bind(info,root):
    """A second Blender opens the same job; only the last Blender closes it."""
    if 'blender_process_lifetime' not in info.get('capabilities',[]):
        raise ValueError('Update the companion with Start to enable automatic Blender shutdown.')
    if Path(info.get('installation_root','')).resolve()!=Path(root).resolve():
        raise ValueError('The companion belongs to a different installation.')
    name=info.get('lifetime_job','');pid=int(info['pid']);stamp=int(info['process_created'])
    if not name.startswith(prefix(root)) or not re.fullmatch('[a-f0-9]{32}',name[len(prefix(root)):]):
        raise ValueError('Invalid companion lifetime identity.')
    with _lock:
        key=(pid,stamp,name)
        if key in _bound:return
        handle=keep(name)
        process=check(api.OpenProcess(0x1000|0x0100|0x0001,False,pid))
        try:
            buffer=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(buffer))
            check(api.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(length)))
            if created(process)!=stamp or Path(buffer.value).resolve()!=(Path(root)/'python_embeded/python.exe').resolve():
                raise ValueError('Companion process identity changed.')
            inside=wintypes.BOOL();check(api.IsProcessInJob(process,handle,ctypes.byref(inside)))
            if not inside.value:check(api.AssignProcessToJobObject(handle,process))
            _bound.add(key)
        finally:api.CloseHandle(process)

def close_all():
    with _lock:
        values=list(_handles.values());_handles.clear();_bound.clear()
        for handle in values:api.CloseHandle(handle)
