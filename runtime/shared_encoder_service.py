"""One local GPU text encoder, shared by the original Kimodo and ARDY workers."""
import argparse
from collections import OrderedDict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import traceback
import uuid
from encoder_profiles import PROFILES

LAB = Path(os.environ.get('MOTION_RUNTIME_ROOT', Path(__file__).resolve().parents[1]))
os.environ.setdefault('HF_HUB_CACHE', str(LAB / 'cache/huggingface/hub'))
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'


class EncoderService:
    def __init__(self, output_dir, precision='int8'):
        import bitsandbytes as bnb
        import torch
        import transformers
        from huggingface_hub import snapshot_download
        from ardy.model.llm2vec.llm2vec import LLM2Vec

        self.torch = torch
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        profile = PROFILES[precision]
        started = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        snapshot = snapshot_download(profile['repo'], revision=profile['revision'], local_files_only=True)
        adapter = (snapshot_download(profile['adapter_repo'], revision=profile['adapter_revision'], local_files_only=True)
                   if precision == 'bf16' else None)
        if precision == 'bf16':
            # Transformers treats a local adapter folder containing config.json as
            # a complete base model. Original repo IDs follow the correct PEFT path.
            # The portable package pins refs/main and loads entirely from its own cache.
            import huggingface_hub.constants as hub_constants
            hub_constants.HF_HUB_OFFLINE = True
            self.encoder = LLM2Vec.from_pretrained(
                profile['repo'], peft_model_name_or_path=profile['adapter_repo'],
                torch_dtype=torch.bfloat16, local_files_only=True,
            )
        else:
            self.encoder = LLM2Vec.from_pretrained(
                snapshot, peft_model_name_or_path=None, torch_dtype=torch.bfloat16,
                device_map={'': 'cuda:0'},
            )
        if precision == 'bf16':
            self.encoder = self.encoder.to('cuda:0')
        self.encoder.model.config._name_or_path = 'meta-llama/Meta-Llama-3-8B-Instruct'
        self.encoder.eval()
        for parameter in self.encoder.parameters():
            parameter.requires_grad = False
        kind = bnb.nn.Linear8bitLt if precision == 'int8' else bnb.nn.Linear4bit
        modules = [m for m in self.encoder.modules() if isinstance(m, kind)]
        if precision != 'bf16' and len(modules) != 224:
            raise RuntimeError(f'Expected 224 actual {precision} linear layers, got {len(modules)}')
        if precision == 'bf16' and any(isinstance(m,(bnb.nn.Linear8bitLt,bnb.nn.Linear4bit)) for m in self.encoder.modules()):
            raise RuntimeError('The BF16 profile unexpectedly contains quantized layers')
        if precision == 'int8' and any(m.weight.dtype != torch.int8 for m in modules):
            raise RuntimeError('INT8 weights were not retained')
        if precision == 'nf4' and any(m.weight.dtype != torch.uint8 or m.weight.quant_state is None
                                    or m.weight.quant_state.quant_type != 'nf4' for m in modules):
            raise RuntimeError('NF4 weights or quantization state were not retained')
        torch.cuda.synchronize()
        source_root = LAB/'engines' if (LAB/'engines').exists() else LAB/'sources'
        source = source_root / 'ardy/ardy/model/llm2vec/llm2vec.py'
        identity = dict(repo=profile['repo'], revision=profile['revision'], preprocessing='original Llama3 header, mean, batch1',
                        torch=torch.__version__, transformers=transformers.__version__,
                        bitsandbytes=bnb.__version__, compute='bfloat16',
                        llm2vec_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        if precision == 'bf16':
            identity.update(adapter_repo=profile['adapter_repo'], adapter_revision=profile['adapter_revision'],
                            bf16_adapter_policy='Original Kimodo policy: BF16 base, retain supervised adapter FP32')
        self.stats = dict(identity, fingerprint=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                          instance_id=uuid.uuid4().hex, pid=os.getpid(), model_load_count=1,
                          precision=precision, int8_linear_layers=len(modules) if precision=='int8' else 0,
                          nf4_linear_layers=len(modules) if precision=='nf4' else 0, state='ready',
                          load_s=time.perf_counter()-started, requests=0, encoded_prompts=0,
                          cache_hits=0, clients={}, total_encode_s=0.)
        if precision == 'bf16':
            dtypes = {}
            for parameter in self.encoder.parameters():
                key = str(parameter.dtype)
                dtypes[key] = dtypes.get(key, 0) + parameter.numel()*parameter.element_size()
            self.stats['parameter_bytes_by_dtype'] = dtypes
        self.persist()

    def snapshot(self):
        torch = self.torch
        return dict(self.stats, cuda_allocated_bytes=torch.cuda.memory_allocated(),
                    cuda_reserved_bytes=torch.cuda.memory_reserved(),
                    peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                    peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(),
                    cache_entries=len(self.cache))

    def persist(self):
        target = self.output_dir / 'encoder_service.json'
        temp = target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.snapshot(), indent=2), encoding='utf-8')
        os.replace(temp, target)

    def encode(self, texts, client):
        if not isinstance(texts, list) or not texts or len(texts) > 64:
            raise ValueError('texts must contain 1..64 strings')
        if not all(isinstance(t, str) and len(t) <= 16384 for t in texts):
            raise ValueError('Invalid text')
        with self.lock:
            started = time.perf_counter()
            vectors = []
            hits = 0
            for text in texts:
                key = hashlib.sha256((self.stats['fingerprint']+'\0'+text).encode()).hexdigest()
                if key in self.cache:
                    hits += 1
                    vector = self.cache[key]
                    self.cache.move_to_end(key)
                else:
                    with self.torch.inference_mode():
                        encoded = self.encoder.encode([text], batch_size=1, show_progress_bar=False, device='cuda:0')
                    if tuple(encoded.shape) != (1, 4096) or not encoded.isfinite().all():
                        raise ValueError('Invalid embedding')
                    vector = encoded[0].float().cpu().tolist()
                    self.cache[key] = vector
                    if len(self.cache) > 256:
                        self.cache.popitem(last=False)
                    self.stats['encoded_prompts'] += 1
                vectors.append(vector)
            elapsed = time.perf_counter()-started
            self.stats['requests'] += 1
            self.stats['cache_hits'] += hits
            self.stats['clients'][client] = self.stats['clients'].get(client, 0)+1
            self.stats['total_encode_s'] += elapsed
            self.persist()
            return dict(vectors=vectors, fingerprint=self.stats['fingerprint'],
                        instance_id=self.stats['instance_id'], pid=self.stats['pid'],
                        elapsed_s=elapsed, cache_hits=hits, precision=self.stats['precision'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--precision', choices=PROFILES, default='int8')
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--output-dir', type=Path, default=None)
    args = parser.parse_args()
    # Bind before loading so a second launcher cannot allocate a duplicate model.
    service = None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # Startup health probes may time out while the GPU model is loading.
                pass
        def do_GET(self):
            if self.path != '/health':
                self.send(404, {'error': 'not found'}); return
            self.send(200, service.snapshot())
        def do_POST(self):
            if self.path != '/encode':
                self.send(404, {'error': 'not found'}); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length < 2*1024*1024:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                self.send(200, service.encode(data['texts'], str(data.get('client', 'unknown'))[:80]))
            except Exception as exc:
                traceback.print_exc()
                self.send(500, {'error': str(exc), 'type': type(exc).__name__})
    port = args.port or PROFILES[args.precision]['port']
    output_dir = args.output_dir or LAB/f'results/shared_{args.precision}'
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    try:
        service = EncoderService(output_dir, args.precision)
        print(json.dumps(service.snapshot(), indent=2), flush=True)
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
