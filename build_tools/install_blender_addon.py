"""Copy only our addon into Blender's scripts/addons directory, preserving other addons."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
NAME='toyxyz_motion_ai_tool'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--addons',type=Path,default=Path.home()/'AppData/Roaming/Blender Foundation/Blender/5.2/scripts/addons')
    args=parser.parse_args();source=ROOT/'addons'/NAME;target=args.addons.resolve()/NAME
    receipt=target/'.deployment.json';previous=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
    if target.exists() and previous is None:raise RuntimeError('Existing addon has no deployment receipt; inspect it before overwriting')
    if previous:
        changed=[name for name,sha in previous['files'].items() if (target/name).is_file() and digest(target/name)!=sha]
        if changed:raise RuntimeError('Installed files were modified; preserved: '+', '.join(changed))
    planned={p.relative_to(source).as_posix() for p in source.rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.name not in ('app_location.json','.deployment.json')}
    removed=sorted(set(previous['files'] if previous else ())-planned-{'app_location.json'})
    obsolete=[]
    for name in removed:
        path=(target/name).resolve()
        if target not in path.parents:raise RuntimeError('Deployment receipt points outside the addon: '+name)
        obsolete.append(path)
    files={}
    for path in source.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.name in ('app_location.json','.deployment.json'):continue
        rel=path.relative_to(source);destination=target/rel;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination);files[rel.as_posix()]=digest(destination)
    for path in obsolete:
        if path.is_file():path.unlink()
        if path.suffix=='.py':
            for cache in (path.parent/'__pycache__').glob(path.stem+'.*.pyc'):
                if target not in cache.resolve().parents:raise RuntimeError('Bytecode path points outside the addon.')
                if cache.is_file():cache.unlink()
    local=target/'app_location.json';local.write_text(json.dumps(dict(root=str(ROOT)),ensure_ascii=False),encoding='utf-8');files[local.name]=digest(local)
    receipt.write_text(json.dumps(dict(source=str(source),files=files),indent=2),encoding='utf-8')
    print(json.dumps(dict(status='installed',path=str(target),files=len(files),removed_files=removed),ensure_ascii=False))

if __name__=='__main__':main()
