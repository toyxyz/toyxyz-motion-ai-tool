"""Fail-closed local client: never falls back to loading a second text encoder."""
import importlib
import json
import os
import urllib.request
from encoder_profiles import PROFILES


class SharedEncoderClient:
    llm_dim = 4096
    def __init__(self, engine, url=None, device='cuda:0', precision=None):
        precision = precision or os.environ.get('MOTION_ENCODER_PRECISION','int8')
        profile = PROFILES[precision]
        self.url = url or os.environ.get('MOTION_ENCODER_URL', f'http://127.0.0.1:{profile["port"]}')
        self.engine = engine
        self._device = str(device)
        self.calls = []
        self.identity = self.health()
        if self.identity.get('precision') != precision or self.identity.get('model_load_count') != 1:
            raise RuntimeError(f'The shared endpoint is not a single {precision} encoder')
        if self.identity.get('repo') != profile['repo'] or self.identity.get('revision') != profile['revision']:
            raise RuntimeError('Unexpected shared encoder weights')
    def health(self):
        with urllib.request.urlopen(self.url+'/health', timeout=20) as response:
            return json.load(response)
    def to(self, device=None, dtype=None):
        if device is not None:
            self._device = str(device)
        return self
    def eval(self):
        return self
    def get_device(self):
        import torch
        return torch.device(self._device)
    @property
    def device(self):
        return self.get_device()
    @property
    def dtype(self):
        import torch
        return torch.float32
    def __call__(self, texts):
        import torch
        is_string = isinstance(texts, str)
        batch = [texts] if is_string else list(texts)
        data = json.dumps({'texts': batch, 'client': self.engine}).encode()
        request = urllib.request.Request(self.url+'/encode', data=data,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        if result['instance_id'] != self.identity['instance_id']:
            raise RuntimeError('Shared encoder changed during this worker session')
        encoded = torch.tensor(result['vectors'], dtype=torch.float32, device=self._device)[:, None]
        if tuple(encoded.shape) != (len(batch),1,4096) or not encoded.isfinite().all():
            raise ValueError('Invalid shared embedding')
        self.calls.append({k:v for k,v in result.items() if k != 'vectors'})
        lengths = [1]*len(batch)
        return (encoded[0], lengths[0]) if is_string else (encoded, lengths)


def inject_shared_encoder(engine, client=None, on_load=None):
    client = client or SharedEncoderClient(engine)
    module = importlib.import_module(f'{engine}.model.load_model')
    original = module.load_model
    def load(*args, **kwargs):
        if kwargs.get('text_encoder') is None:
            kwargs['text_encoder'] = client
        result = original(*args, **kwargs)
        if on_load:
            on_load(result[0] if isinstance(result,tuple) else result)
        return result
    module.load_model = load
    importlib.import_module(engine).load_model = load
    importlib.import_module(f'{engine}.model').load_model = load
    if engine == 'ardy':
        module.load_text_encoder = lambda *args, **kwargs: client
    return client
