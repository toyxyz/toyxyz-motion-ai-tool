"""Exercise selective model installation and download-only token handling."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import installer


class ModelSelection(unittest.TestCase):
    def test_manifest_selection(self):
        manifest = json.loads((ROOT / 'manifests/models.lock.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifests').mkdir()
            (root / 'manifests/models.lock.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(installer, 'ROOT', root):
                kimodo = installer.model_status('nf4', engines=('kimodo',))
                self.assertEqual({item['model']['repo'] for item in kimodo},
                                 {installer.MODEL_REPOS['kimodo'], 'voxta/Llama-3-8B-LLM2Vec-ARDY-NF4'})
                two = installer.model_status('nf4', engines=('kimodo', 'ardy'))
                self.assertEqual(len(two), len(kimodo) + sum(
                    len(model['files']) for model in manifest['models']
                    if model['repo'] == installer.MODEL_REPOS['ardy']))
                motionbricks = installer.model_status('bf16', engines=('motionbricks',))
                self.assertEqual(len(motionbricks), 2)
                self.assertTrue(all('asset' in item for item in motionbricks))
                self.assertEqual(motionbricks, installer.model_status('fp32', engine='motionbricks'))
        self.assertEqual(installer.parse_models('ARDY, motionbricks, ardy'), ('ardy', 'motionbricks'))
        for invalid in ('', 'all', 'kimodo,', 'missing'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                installer.parse_models(invalid)

    def test_install_reports_only_selected_models(self):
        for selection in (('kimodo',), ('motionbricks',), ('ardy', 'motionbricks')):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for subdir in ('manifests', 'results'):
                    (root / subdir).mkdir()
                (root / 'manifests/models.lock.json').write_text((ROOT / 'manifests/models.lock.json').read_text(
                    encoding='utf-8'), encoding='utf-8')
                with patch.object(installer, 'ROOT', root), patch.dict(os.environ, {'LOCALAPPDATA': str(root)}), \
                     patch.object(installer.runpy, 'run_path', return_value={'verify': lambda *args: None}), \
                     patch.object(installer, 'model_status', side_effect=[[{'missing': True}], []]) as status, \
                     patch.object(installer, 'download_missing') as download, contextlib.redirect_stdout(io.StringIO()):
                    installer.install('nf4', models=selection)
                    self.assertTrue(all(call.kwargs['engines'] == selection for call in status.call_args_list))
                    download.assert_called_once_with([{'missing': True}], encoder_token=None)
                report = json.loads((root / 'results/install.json').read_text(encoding='utf-8'))
                self.assertEqual(report['models'], list(selection))
                refs = set(path.parent.parent.name for path in root.glob('models/**/refs/main'))
                self.assertEqual(refs, {'models--' + repo.replace('/', '--')
                                        for repo in installer.required_models('nf4', selection)})

    def test_token_reused_only_for_the_protected_repository(self):
        secret = 'test-private-credential'
        public, protected = 'owner/public', 'owner/protected'
        calls = []

        class Forbidden(Exception):
            response = SimpleNamespace(status_code=403)

        def fetch(repo, name, **kwargs):
            calls.append((repo, name, kwargs['token']))
            self.assertEqual(kwargs['endpoint'], 'https://huggingface.co')
            self.assertEqual(os.environ['HF_DEBUG'], '0')
            if repo == protected and kwargs['token'] is False:
                raise Forbidden()
            target = kwargs['local_dir'] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'payload')
            return target

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checksum = hashlib.sha256(b'payload').hexdigest()
            missing = [dict(model={'repo': repo, 'revision': 'test'}, file={'name': name, 'sha256': checksum},
                            target=root / repo / name) for repo, name in
                       ((public, 'model'), (protected, 'shard1'), (protected, 'shard2'), (public, 'other'))]
            output = io.StringIO()
            with patch.dict(os.environ, {'HF_DEBUG': '1'}), \
                 patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(hf_hub_download=fetch)}), \
                 patch.object(installer, 'prompt_read_token', return_value=secret) as prompt, \
                 contextlib.redirect_stdout(output):
                installer.download_missing(missing)
                prompt.assert_called_once_with(protected)
            self.assertEqual(calls, [(public, 'model', False), (protected, 'shard1', False),
                                     (protected, 'shard1', secret), (protected, 'shard2', secret),
                                     (public, 'other', False)])
            self.assertNotIn(secret, output.getvalue())
            self.assertTrue(all(secret.encode() not in path.read_bytes() for path in root.rglob('*') if path.is_file()))

    def test_token_prompt_fails_closed(self):
        def echo_fallback(*args):
            import warnings
            warnings.warn('Would fall back to echoed entry', installer.getpass.GetPassWarning)
            self.fail('An echoed prompt was allowed')

        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys.stdin, 'isatty', return_value=True), \
             patch.object(installer.getpass, 'getpass', side_effect=echo_fallback):
            with self.assertRaisesRegex(RuntimeError, 'Hidden token entry is unavailable'):
                installer.prompt_read_token('owner/protected')
        with patch.object(sys.stdin, 'isatty', return_value=False), patch.object(installer.getpass, 'getpass') as prompt:
            with self.assertRaisesRegex(RuntimeError, 'in a console'):
                installer.prompt_read_token('owner/protected')
            prompt.assert_not_called()

    def test_preentered_token_is_used_only_for_gated_encoder(self):
        secret = 'test-preentered-credential'
        gated = installer.GATED_ENCODER_REPO
        public = installer.MODEL_REPOS['kimodo']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / 'file'
            local.write_bytes(b'model')
            missing = [
                dict(model={'repo': repo, 'revision': 'pinned'},
                     file={'name': 'file', 'sha256': installer.digest(local)}, target=local)
                for repo in (public, gated, public)
            ]
            with patch.dict(os.environ), patch.object(installer, 'prompt_read_token') as prompt, \
                 patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(hf_hub_download=unittest.mock.Mock(return_value=local))}), \
                 contextlib.redirect_stdout(io.StringIO()):
                fetch = sys.modules['huggingface_hub'].hf_hub_download
                installer.download_missing(missing, encoder_token=secret)
                self.assertEqual([call.kwargs['token'] for call in fetch.call_args_list], [False, secret, False])
                prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
