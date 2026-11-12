"""Windows closes the entire owned worker group if the launcher exits unexpectedly."""
import ctypes
from ctypes import wintypes

HANDLE=None
def adopt(pid):
    """Include a verified same-installation pre-existing encoder in our kill job."""
    if HANDLE is None:attach()
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];api.AssignProcessToJobObject.restype=wintypes.BOOL
    api.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)];api.IsProcessInJob.restype=wintypes.BOOL
    process=api.OpenProcess(0x1000|0x0100|0x0001,False,int(pid))
    if not process:raise ctypes.WinError(ctypes.get_last_error())
    try:
        inside=wintypes.BOOL()
        if not api.IsProcessInJob(process,HANDLE,ctypes.byref(inside)):raise ctypes.WinError(ctypes.get_last_error())
        if not inside.value and not api.AssignProcessToJobObject(HANDLE,process):raise ctypes.WinError(ctypes.get_last_error())
    finally:api.CloseHandle(process)

def attach():
    global HANDLE
    if HANDLE is not None:return
    size=ctypes.c_size_t
    class Limits(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),
                  ('min_working',size),('max_working',size),('active_processes',wintypes.DWORD),
                  ('affinity',size),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Limits),('io',Counters),('process_memory',size),('job_memory',size),('peak_process',size),('peak_job',size)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];api.CreateJobObjectW.restype=wintypes.HANDLE
    api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    api.SetInformationJobObject.restype=wintypes.BOOL
    api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];api.AssignProcessToJobObject.restype=wintypes.BOOL
    api.GetCurrentProcess.restype=wintypes.HANDLE
    handle=api.CreateJobObjectW(None,None)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    limits=Extended();limits.basic.flags=0x2000
    if not api.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not api.AssignProcessToJobObject(handle,api.GetCurrentProcess()):raise ctypes.WinError(ctypes.get_last_error())
    HANDLE=handle
