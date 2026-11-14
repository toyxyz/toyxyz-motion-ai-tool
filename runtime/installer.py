"""End-user preparation uses bundled Python and pinned artifacts, never pip or compilers."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import urllib.request
import warnings
from entry import ROOT

DEFAULT_PRECISION='nf4'
GATED_ENCODER_REPO = 'meta-llama/Meta-Llama-3-8B-Instruct'
MODEL_REPOS = {
    'kimodo': 'nvidia/Kimodo-SOMA-RP-v1.2',
    'ardy': 'nvidia/ARDY-SOMA-RP-30FPS-Horizon60',
}
MOTION_MODELS = (*MODEL_REPOS, 'motionbricks')

def settings():
    path=ROOT/'settings.json'
    if not path.exists():return dict(precision=DEFAULT_PRECISION,engines=['kimodo','ardy'])
    return json.loads(path.read_text(encoding='utf-8'))

def parse_models(value):
    if value is None:
        return MOTION_MODELS
    models = tuple(dict.fromkeys(item.strip().lower() for item in value.split(',')))
    if any(model not in MOTION_MODELS for model in models):
        raise ValueError('Choose one or more of kimodo, ardy, and motionbricks.')
    return models


def required_models(precision, engines=MOTION_MODELS):
    names = {MODEL_REPOS[engine] for engine in engines if engine in MODEL_REPOS}
    if not names:
        return names
    if precision in ('bf16','all'):
        names.update([GATED_ENCODER_REPO,
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

def model_status(precision,verify=False,engine=None,*,engines=MOTION_MODELS):
    manifest=json.loads((ROOT/'manifests/models.lock.json').read_text(encoding='utf-8'))
    missing=[]
    if engine is not None:
        engines = (engine,)
    repos=required_models(precision, engines)
    for model in manifest['models']:
        if model['repo'] not in repos:continue
        base=ROOT/'models/huggingface/hub'/('models--'+model['repo'].replace('/','--'))/'snapshots'/model['revision']
        for file in model['files']:
            path=base/file['name']
            if not path.is_file() or path.stat().st_size!=file['bytes'] or (verify and digest(path)!=file['sha256']):
                missing.append(dict(model=model,file=file,target=path))
    for asset in manifest['assets'] if 'motionbricks' in engines else ():
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

def prompt_read_token(repo):
    if not sys.stdin.isatty():
        raise RuntimeError(f'{repo} requires Hugging Face access. Run install.cmd in a console to enter a Read token.')
    print('1. Sign in to Hugging Face and request access on the model page.')
    print(f'   https://huggingface.co/{repo}')
    print('   Accept any required terms and wait for approval.')
    print('2. Open Access Tokens in the same approved account.')
    print('   https://huggingface.co/settings/tokens')
    print('   Choose New token, select Read, name it, and copy the generated token.')
    print('3. Paste it below. The installer uses it only for this download and does not save it.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            token = getpass.getpass('HF token (hidden, Enter to cancel): ').strip()
    except (getpass.GetPassWarning, EOFError):
        raise RuntimeError('Hidden token entry is unavailable. Open install.cmd in a Windows console.') from None
    if not token:
        raise RuntimeError('Model download cancelled.')
    return token


def download_missing(missing, *, encoder_token=None):
    # Keep authentication in the downloader process. Disable optional Hub debug
    # output and its native transfer helper before the Hub imports its settings.
    os.environ['HF_DEBUG'] = '0'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    from huggingface_hub import hf_hub_download

    active_repo = None
    token = False
    for item in missing:
        if 'asset' in item:
            token = False
            active_repo = None
            print('Preparing engine asset: '+item['asset']['path'],flush=True)
            download_asset(item['asset'],item['target'])
            continue
        model, file, target = item['model'], item['file'], item['target']
        repo, name = model['repo'], file['name']
        if repo != active_repo:
            active_repo = repo
            token = (encoder_token or False) if repo == GATED_ENCODER_REPO else False
        print(f'Preparing model: {repo} / {name}',flush=True)
        while True:
            try:
                local = hf_hub_download(repo, name, revision=model['revision'],
                                        local_dir=target.parents[len(Path(name).parts)-1],
                                        token=token, endpoint='https://huggingface.co',
                                        force_download=target.exists())
            except Exception as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status in (401, 403) and repo == GATED_ENCODER_REPO and encoder_token:
                    raise RuntimeError(
                        'Hugging Face refused access to the BF16 files. Confirm the account has approval at '
                        f'https://huggingface.co/{GATED_ENCODER_REPO} and create a Read token from that account at '
                        'https://huggingface.co/settings/tokens before trying again.'
                    ) from None
                if status not in (401, 403):
                    if token:
                        raise RuntimeError(f'Authenticated download failed for {repo} / {name}.') from None
                    raise
            else:
                if digest(Path(local)) != file['sha256']:
                    raise RuntimeError('Downloaded file checksum failed.')
                break
            token = prompt_read_token(repo)


def install(precision=None,verify=False,*,models=MOTION_MODELS,encoder_token=None):
    precision=precision or settings()['precision']
    print('Selected motion models: '+', '.join(models),flush=True)
    if any(model in MODEL_REPOS for model in models):
        print('Text encoder profile: '+precision.upper(),flush=True)
    print('Checking runtime and model files.',flush=True)
    validator=runpy.run_path(str(ROOT/'bootstrap/check_runtime.py'))
    validator['verify'](ROOT/'python_embeded',ROOT/'manifests/runtime.lock.json',False)
    missing=model_status(precision,verify,engines=models)
    if missing:
        download_missing(missing, encoder_token=encoder_token)
    if model_status(precision,engines=models):raise RuntimeError('Some required model files are still missing.')
    manifest=json.loads((ROOT/'manifests/models.lock.json').read_text(encoding='utf-8'))
    repos = required_models(precision, models)
    for model in manifest['models']:
        if model['repo'] not in repos:continue
        refs=ROOT/'models/huggingface/hub'/('models--'+model['repo'].replace('/','--'))/'refs'
        refs.mkdir(parents=True,exist_ok=True);(refs/'main').write_text(model['revision'],encoding='utf-8')
    report=dict(status='passed',models=models,precision=precision,full_hash_verification=verify,downloads=len(missing))
    (ROOT/'results/install.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    location=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'Toyxyz/MotionAI'
    location.mkdir(parents=True,exist_ok=True)
    marker=location/'companion.json'
    temporary=marker.with_name(f'companion-{os.getpid()}.tmp')
    temporary.write_text(json.dumps(dict(root=str(ROOT))),encoding='utf-8')
    temporary.replace(marker)
    print('Ready. Install the Blender add-on ZIP and open the Motion AI sidebar.',flush=True)
