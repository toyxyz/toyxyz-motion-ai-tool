"""Small atomic progress snapshots; percentages follow completed work, never a timer."""
import json
import time


class ProgressReporter:
    def __init__(self,path):
        self.path=path;self.last_write=0;self.percent=0;self.completed=0;self.total=None

    def __call__(self,fraction,stage,completed=None,total=None,force=False):
        percent=max(self.percent,min(99,float(fraction)*100));self.percent=percent
        if completed is not None:self.completed=completed
        if total is not None:self.total=total
        now=time.monotonic()
        if not force and now-self.last_write<.05:return
        value=dict(progress=percent,stage=stage,completed=self.completed,total=self.total,updated=time.time())
        temp=self.path.with_suffix('.partial');temp.write_text(json.dumps(value),encoding='utf-8')
        for attempt in range(50):
            try:temp.replace(self.path);break
            except PermissionError:
                if attempt==49:raise
                time.sleep(.01)
        self.last_write=now
