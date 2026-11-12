"""Version-matched generation limits, shared with the bridge's JSON validation."""
import json
import math
from pathlib import Path

LIMITS=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))

def frames(engine,fps):
    value=LIMITS[engine];rate=value['sample_rate']
    maximum=math.inf if value['max_frames'] is None else max(1,math.floor(value['max_frames']*fps/rate+1e-7))
    return max(1,math.ceil(value['min_frames']*fps/rate-1e-7)),maximum

def clamp(engine,fps,length):
    low,high=frames(engine,fps)
    return max(low,min(high,length))
