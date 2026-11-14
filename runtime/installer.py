"""End-user preparation uses bundled Python and pinned artifacts, never pip or compilers."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import runpy
import urllib.request
from entry import ROOT

DEFAULT_PRECISION='nf4'

def settings():
    path=ROOT/'settings.json'
    if not path.exists():return dict(precision=DEFAULT_PRECISION,engines=['kimodo','ardy'])
    return json.loads(path.read_text(encoding='utf-8'))

def required_models(precision):
    names={'nvidia/Kimodo-SOMA-RP-v1.2','nvidia/ARDY-SOMA-RP-30FPS-Horizon60'}
    if precision in ('bf16','all'):
        names.update(['meta-llama/Meta-Llama-3-8B-Instruct',
                      'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp',
                      'McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised'])
    for kind in ('int8','nf4'):
        if precision in (kind,'all'):names.add(f'voxta/Llama-3-8B-LLM2Vec-ARDY-{kind.upper()}')
    return names

def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):result.update(block)
    return result.hexdigest()

def model_status(precision,verify=False,engine=None):
    manifest=json.loads((ROOT/'manifests/models.lock.json').read_text(encoding='utf-8'))
    missing=[]
    repos=required_models(precision) if engine!='motionbricks' else set()
    if engine=='kimodo':repos.discard('nvidia/ARDY-SOMA-RP-30FPS-Horizon60')
    if engine=='ardy':repos.discard('nvidia/Kimodo-SOMA-RP-v1.2')
    for model in manifest['models']:
        if model['repo'] not in repos:continue
        base=ROOT/'models/huggingface/hub'/('models--'+model['repo'].replace('/','--'))/'snapshots'/model['revision']
        for file in model['files']:
            path=base/file['name']
            if not path.is_file() or path.stat().st_size!=file['bytes'] or (verify and digest(path)!=file['sha256']):
                missing.append(dict(model=model,file=file,target=path))
    for asset in manifest['assets']:
        if engine in ('kimodo','ardy'):continue
        if not (ROOT/'launch.cmd').exists() and not asset['path'].endswith(('soma_base_skel_minimal_no_root.usd','mmm_v6_soma_fp32.onnx')):continue
        path=ROOT/asset['path']
        if not path.resolve().is_relative_to(ROOT):raise RuntimeError('Invalid asset path')
        if not path.is_file() or path.stat().st_size!=asset['bytes'] or (verify and digest(path)!=asset['sha256']):
            missing.append(dict(asset=asset,target=path))
    return missing

def download_asset(asset,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+'.partial')
    offset=partial.stat().st_size if partial.exists() else 0
    if offset>asset['bytes']:raise RuntimeError('Oversized partial asset: '+str(partial))
    if offset<asset['bytes']:
        request=urllib.request.Request(asset['url'],headers={'Range':f'bytes={offset}-'} if offset else {})
        with urllib.request.urlopen(request,timeout=90) as response:
            if response.status==206:
                if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                    raise RuntimeError('Invalid asset resume response')
            elif response.status==200:offset=0
            else:raise RuntimeError('Unexpected asset response')
            with partial.open('ab' if offset else 'wb') as stream:
                while block:=response.read(4*1024**2):
                    stream.write(block)
                    if stream.tell()>asset['bytes']:raise RuntimeError('Oversized asset download')
    if partial.stat().st_size!=asset['bytes'] or digest(partial)!=asset['sha256']:
        raise RuntimeError('Asset checksum mismatch; remove and retry: '+str(partial))
    partial.replace(target)

def install(precision=None,verify=False):
    precision=precision or settings()['precision']
    print('Checking runtime and model files.',flush=True)
    validator=runpy.run_path(str(ROOT/'bootstrap/check_runtime.py'))
    validator['verify'](ROOT/'python_embeded',ROOT/'manifests/runtime.lock.json',False)
    missing=model_status(precision,verify)
    if missing:
        from huggingface_hub import hf_hub_download
        token=None
        for item in missing:
            if 'asset' in item:
                print('Preparing engine asset: '+item['asset']['path'],flush=True)
                download_asset(item['asset'],item['target'])
                continue
            model=item['model'];file=item['file'];target=item['target']
            print(f'Preparing model: {model["repo"]} / {file["name"]}',flush=True)
            while True:
                try:
                    local=hf_hub_download(model['repo'],file['name'],revision=model['revision'],
                                          local_dir=target.parents[len(Path(file['name']).parts)-1],token=token or False,force_download=target.exists())
                    if digest(Path(local))!=file['sha256']:raise RuntimeError('Downloaded file checksum failed.')
                    break
                except Exception as exc:
                    status=getattr(getattr(exc,'response',None),'status_code',None)
                    if status not in (401,403):raise
                    print('A read token from a Hugging Face account with model access is required. The token is not saved.')
                    token=getpass.getpass('HF token: ').strip()
                    if not token:raise RuntimeError('No model access token was supplied.') from None
    if model_status(precision):raise RuntimeError('Some required model files are still missing.')
    manifest=json.loads((ROOT/'manifests/models.lock.json').read_text(encoding='utf-8'))
    for model in manifest['models']:
        if model['repo'] not in required_models(precision):continue
        refs=ROOT/'models/huggingface/hub'/('models--'+model['repo'].replace('/','--'))/'refs'
        refs.mkdir(parents=True,exist_ok=True);(refs/'main').write_text(model['revision'],encoding='utf-8')
    report=dict(status='passed',precision=precision,full_hash_verification=verify,downloads=len(missing))
    (ROOT/'results/install.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    location=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'Toyxyz/MotionAI'
    location.mkdir(parents=True,exist_ok=True)
    marker=location/'companion.json'
    temporary=marker.with_name(f'companion-{os.getpid()}.tmp')
    temporary.write_text(json.dumps(dict(root=str(ROOT))),encoding='utf-8')
    temporary.replace(marker)
    print('Ready. Install the Blender add-on ZIP and open the Motion AI sidebar.',flush=True)
