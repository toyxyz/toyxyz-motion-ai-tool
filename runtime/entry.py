"""All roles run with the same app-local CPython executable."""
import argparse
import locale
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
DLL_HANDLES=[]

def bootstrap(engine='ardy',online=False):
    # Python's UTF-8 mode does not change native UCRT fopen. Warp passes UTF-8
    # filenames to C, so set only LC_CTYPE before any worker threads start.
    # Keep LC_NUMERIC unchanged for model text/number parsing.
    locale.setlocale(locale.LC_CTYPE,'.UTF8')
    common=ROOT/'python_embeded/packages/common'
    private=ROOT/f'python_embeded/packages/{engine}'
    source=ROOT/f'engines/{engine}'
    sys.path[:0]=[str(private),str(source),str(ROOT/'runtime'),str(common)]
    # ._pth ignores PYTHONPATH, registry Python installations, and user site packages.
    env=dict(MOTION_RUNTIME_ROOT=str(ROOT),HF_HOME=str(ROOT/'cache/huggingface'),
             HF_HUB_CACHE=str(ROOT/'models/huggingface/hub'),HF_HUB_OFFLINE='0' if online else '1',
             HF_HUB_DISABLE_PROGRESS_BARS='1',HF_HUB_DISABLE_SYMLINKS_WARNING='1',
             TRANSFORMERS_OFFLINE='0' if online else '1',PYTHONUTF8='1',
             PYTHONIOENCODING='utf-8',GRADIO_ANALYTICS_ENABLED='False',
             TORCHINDUCTOR_CACHE_DIR=str(ROOT/'cache/torch_inductor'),
             WARP_CACHE_PATH=os.environ.get('WARP_CACHE_PATH',str(ROOT/'cache/warp')),LOCAL_CACHE='true',
             TEXT_ENCODER_MODE='api',SERVER_NAME='127.0.0.1')
    os.environ.update(env)
    # Native modules with the same import name remain in different worker processes.
    for directory in [ROOT/'python_embeded',common/'torch/lib',private,common/'nvidia/cuda_runtime/bin']:
        if directory.is_dir():DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    for folder in ['logs','results','cache/warp','cache/torch_inductor','cache/sessions']:
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    os.chdir(ROOT)

def main():
    if ';' in str(ROOT):
        print('This installation path contains a semicolon (;). Move the entire folder to a path without semicolons.',file=sys.stderr,flush=True)
        raise SystemExit(2)
    parser=argparse.ArgumentParser()
    parser.add_argument('role',choices=['ui','install','doctor','encoder','demo','sample','motionbricks','selftest','bridge'])
    parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--engine',choices=['kimodo','ardy','motionbricks'],default='ardy')
    parser.add_argument('--precision',choices=['bf16','int8','nf4','all'],default=None)
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--test',action='store_true')
    parser.add_argument('--cases',type=int,default=2)
    parser.add_argument('--hold',action='store_true')
    args=parser.parse_args()
    if args.role in ('ui','selftest','bridge'):
        from blender_owner import join
        join()
        from process_owner import attach
        attach()
    bootstrap(args.engine,online=args.role=='install')
    if args.role=='bridge':
        from motion_bridge_service import serve
        serve(args.port,not args.no_browser)
    elif args.role=='encoder':
        from shared_encoder_service import main as serve
        sys.argv=['encoder','--precision',args.precision or 'bf16','--output-dir',str(ROOT/'results'/f'encoder_{args.precision or "bf16"}')]
        serve()
    elif args.role=='demo':
        from engine_runner import demo
        demo(args.engine,args.precision or 'bf16')
    elif args.role=='sample':
        from engine_runner import sample
        sample(args.engine,args.precision or 'bf16',args.cases,args.hold)
    elif args.role=='motionbricks':
        from engine_runner import motionbricks
        motionbricks(args.test)
    elif args.role=='selftest':
        from verify_runtime import main as verify
        verify(args.precision or 'all')
    elif args.role=='doctor':
        from verify_runtime import doctor
        doctor(args.engine)
    elif args.role=='install':
        from installer import install
        install(args.precision,args.verify)
    else:
        from launcher import serve_ui
        serve_ui(open_browser=not args.no_browser)

if __name__=='__main__':main()
