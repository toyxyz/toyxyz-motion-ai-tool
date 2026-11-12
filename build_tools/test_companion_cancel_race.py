import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'runtime'))
import motion_bridge_service as service

class Worker:
    def __init__(self):
        self.terminated=False
    def poll(self):
        return -1 if self.terminated else None
    def terminate(self):
        self.terminated=True

with TemporaryDirectory(dir=root) as temporary:
    path=Path(temporary)
    worker=Worker()
    model=service.Application.__new__(service.Application)
    model.lock=RLock();model.closed=Event();model.motion=worker;model.motion_engine='motionbricks'
    model.ensure_motion=lambda engine:worker
    model.mailbox=path
    result=dict(status='succeeded',frame_count=30,elapsed_seconds=1,worker_pid=10,model_reused=True,model_load_count=1)
    text=json.dumps(result)
    (path/'result.json').write_text(text,encoding='utf-8')
    job=dict(id='cancel-race',status='queued',message='',engine='motionbricks',process=None,
             progress=0.,folder=path,result=None)
    model.jobs={job['id']:job};model.active=job['id']
    inside_load,resume_load=Event(),Event()
    decode=json.loads
    def held_load(raw,*args,**kwargs):
        if raw==text:
            inside_load.set()
            if not resume_load.wait(5):
                raise TimeoutError('The test did not release the worker.')
        return decode(raw,*args,**kwargs)
    with patch.object(service.json,'loads',side_effect=held_load):
        task=Thread(target=model.run,args=(job,))
        task.start()
        assert inside_load.wait(5)
        cancelled=model.cancel(job['id'])
        resume_load.set()
        task.join(5)
        assert not task.is_alive()
    assert cancelled['status']=='cancelled'
    evidence=dict(check='cancel_during_result_decode',cancel_reply=cancelled['status'],final_status=job['status'],
                  result_published=job['result'] is not None,worker_terminated=worker.terminated)
    print(json.dumps(evidence,indent=2))
    assert job['status']=='cancelled' and job['result'] is None and worker.terminated

    queued=dict(job,id='cancel-before-start',status='queued',message='',process=None)
    model.jobs[queued['id']]=queued
    model.active=queued['id']
    assert model.cancel(queued['id'])['status']=='cancelled'
    with patch.object(model,'ensure_motion') as launch:
        model.run(queued)
        launch.assert_not_called()
    assert queued['status']=='cancelled' and queued['result'] is None and model.active is None

