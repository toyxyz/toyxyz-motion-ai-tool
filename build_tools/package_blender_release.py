"""Build the user-facing packages from an explicit, tracked release tree."""
import argparse
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ADDON = 'addons/toyxyz_motion_ai_tool/'
BOOT_FILES = {'install.cmd', 'check.cmd', 'toyxyz_motion_ai_tool.cmd', 'README.md'}
SHARED_ADDON_FILES = {ADDON + filename for filename in ('soma.json', 'model_limits.json', 'lifetime.py')}
ENGINE_ROOTS = ('engines/ardy/ardy/', 'engines/kimodo/kimodo/', 'engines/motionbricks/motionbricks/')
DENIED_PARTS = {'.git', '.codex', '.agents', '.vscode', '__pycache__', 'testdata', 'tests', 'examples'}
SECRET = re.compile(rb'\b(?:gh[pousr]_[0-9A-Za-z]{35,}|github_pat_[0-9A-Za-z_]{55,}|hf_[0-9A-Za-z]{30,}|sk-proj-[0-9A-Za-z_-]{35,})\b')
PRIVATE_PATH = re.compile(rb'(?i)([a-z]:[/\\]users[/\\]|/home/|/Users/)toyxy(?:[/\\]|\b)')


def companion_file(name):
    return (name in BOOT_FILES or name.startswith(('bootstrap/', 'manifests/', 'runtime/'))
            or name in SHARED_ADDON_FILES
            or (name.startswith(ENGINE_ROOTS) and '/g1skel34/meshes/' not in name)
            or (name.startswith('engines/') and (
                PurePosixPath(name).name.lower().startswith(('license', 'notice', 'copying')) or '/licenses/' in name)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tree = subprocess.check_output(['git', 'archive', '--format=zip', args.ref], cwd=ROOT)
    with ZipFile(io.BytesIO(tree)) as source:
        manifest = source.read(ADDON + '__init__.py')
        match = re.search(rb"'version':\((\d+),(\d+),(\d+)\)", manifest)
        version = '.'.join(part.decode() for part in match.groups())
        args.output.mkdir(parents=True, exist_ok=True)
        archives = (
            (f'toyxyz_motion_ai_tool-{version}-blender-addon.zip', lambda n: n.startswith(ADDON), lambda n: n.removeprefix('addons/')),
            (f'MotionAI_Windows_Companion-{version}.zip', companion_file, lambda n: f'MotionAI_Windows_Companion-{version}/{n}'),
        )
        for filename, include, archive_name in archives:
            path = args.output / filename
            with ZipFile(path, 'w', ZIP_DEFLATED, compresslevel=9) as output:
                for item in source.infolist():
                    name = item.filename
                    if item.is_dir() or not include(name) or DENIED_PARTS.intersection(PurePosixPath(name).parts):
                        continue
                    if name.endswith(('.log', '.pyc', '.pem', '.pfx')) or PurePosixPath(name).name in {'app_location.json', 'settings.json', '.deployment.json'}:
                        raise ValueError(f'Unexpected release member: {name}')
                    content = source.read(item)
                    if SECRET.search(content):
                        raise ValueError(f'Credential pattern in {name}')
                    if PRIVATE_PATH.search(content):
                        raise ValueError(f'Development path in {name}')
                    output.writestr(archive_name(name), content)
            print(f'{path}: {path.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
