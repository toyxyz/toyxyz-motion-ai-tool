"""Keep NVRTC include arguments relative and ASCII inside the fixed package layout."""
import os
from pathlib import Path
import threading

def configure_warp():
    import warp
    import warp._src.build as build
    if getattr(build,'_motionai_unicode_paths',False):return
    if warp.__version__!='1.19.0':raise RuntimeError('Revalidate native path adapter for the new Warp version')
    original=build.build_cuda
    original_extra=build._get_extra_include_dirs
    warp_root=Path(warp.__file__).resolve().parent
    lock=threading.RLock()
    def relative(path):
        value=os.path.relpath(path,os.getcwd()).replace('\\','/')
        if not value.isascii():raise RuntimeError('NVRTC include path is outside the portable ASCII package layout')
        return value
    def extra(entries):return [relative(path).encode('utf-8') for path in original_extra(entries)]
    def compile_cuda(*args,**kwargs):
        # NVRTC 13.4 rejects non-ASCII absolute include paths even with UTF-8
        # Windows file APIs. Relative paths use the unchanged wide-character cwd.
        with lock:
            previous=build.warp_home
            try:
                build.warp_home=relative(warp_root)
                return original(*args,**kwargs)
            finally:build.warp_home=previous
    build._get_extra_include_dir_bytes=extra
    build.build_cuda=compile_cuda
    build._motionai_unicode_paths=True
