"""Summarize paired motion differences; these are not animation-quality pass/fail thresholds."""
import csv
import json
from pathlib import Path
import numpy as np

LAB=Path(__file__).resolve().parents[1]
ROOT=LAB/'results/shared_int8'

def metrics(reference,candidate):
    root=np.linalg.norm(reference['root_positions']-candidate['root_positions'],axis=-1)
    world=np.linalg.norm(reference['posed_joints']-candidate['posed_joints'],axis=-1)
    rel_a=reference['posed_joints']-reference['root_positions'][:,None,:]
    rel_b=candidate['posed_joints']-candidate['root_positions'][:,None,:]
    relative=np.linalg.norm(rel_a-rel_b,axis=-1)
    delta=np.swapaxes(reference['local_rot_mats'],-1,-2)@candidate['local_rot_mats']
    angle=np.degrees(np.arccos(np.clip((np.trace(delta,axis1=-2,axis2=-1)-1)/2,-1,1)))
    result=dict(root_mean_cm=float(root.mean()*100),root_final_cm=float(root[-1]*100),
                root_max_cm=float(root.max()*100),world_mpjpe_cm=float(world.mean()*100),
                root_relative_mpjpe_cm=float(relative.mean()*100),rotation_mean_deg=float(angle.mean()),
                rotation_p95_deg=float(np.percentile(angle,95)))
    if 'foot_contacts' in reference and 'foot_contacts' in candidate:
        result['contact_agreement']=float(np.mean(reference['foot_contacts']==candidate['foot_contacts']))
    return result

def main():
    summary=json.loads((ROOT/'benchmark_summary.json').read_text())
    rows=[]
    historical={}
    timings={}
    cross_engine=[]
    for engine in ('kimodo','ardy'):
        bf=json.loads((ROOT/f'{engine}_bf16.json').read_text())
        trial=json.loads((ROOT/f'{engine}_int8.json').read_text())
        timings[engine]={
            'bf16_load_s':bf['load_s'],'int8_worker_load_s':trial['load_s'],
            'bf16_generation_s':[c['generation_call_s'] for c in bf['cases']],
            'int8_generation_s':[c['generation_call_s'] for c in trial['cases']],
            'bf16_peak_cuda_allocated_bytes':bf['peak_cuda_allocated_bytes'],
            'int8_worker_peak_cuda_allocated_bytes':trial['peak_cuda_allocated_bytes'],
        }
        for a,b in zip(bf['cases'],trial['cases']):
            assert a['id']==b['id'] and a['motion_noise_sha256']==b['motion_noise_sha256']
            with np.load(a['output'],allow_pickle=False) as ref,np.load(b['output'],allow_pickle=False) as target:
                row=dict(engine=engine,case=a['id'],**metrics(ref,target))
            emb_a=np.load(Path(a['output']).with_name(a['id']+'_embeddings.npz'),allow_pickle=False)
            emb_b=np.load(Path(b['output']).with_name(b['id']+'_embeddings.npz'),allow_pickle=False)
            x=np.concatenate([emb_a[k].ravel() for k in emb_a.files]).astype(np.float64)
            y=np.concatenate([emb_b[k].ravel() for k in emb_b.files]).astype(np.float64)
            row.update(embedding_cosine=float(x@y/(np.linalg.norm(x)*np.linalg.norm(y))),
                       embedding_relative_l2=float(np.linalg.norm(x-y)/np.linalg.norm(x)),
                       embedding_norm_ratio=float(np.linalg.norm(y)/np.linalg.norm(x)))
            rows.append(row)
            emb_a.close();emb_b.close()
        with np.load(LAB/f'results/{engine}/walk.npz',allow_pickle=False) as old,\
             np.load(bf['cases'][0]['output'],allow_pickle=False) as fresh:
            historical[engine]=metrics(old,fresh)
    # Identical raw text is served as the same tensor to both engines.
    sharing=[]
    for case in json.loads((ROOT/'kimodo_int8.json').read_text())['cases']:
        name=case['id']
        with np.load(ROOT/f'comparison/kimodo/int8/{name}_embeddings.npz') as a,\
             np.load(ROOT/f'comparison/ardy/int8/{name}_embeddings.npz') as b:
            sharing.append(dict(case=name,identical=bool(np.array_equal(a['embedding_0'],b['embedding_0']))))
    assert all(x['identical'] for x in sharing)
    for case in json.loads((ROOT/'kimodo_bf16.json').read_text())['cases']:
        name=case['id']
        with np.load(ROOT/f'comparison/kimodo/bf16/{name}_embeddings.npz') as a,\
             np.load(ROOT/f'comparison/ardy/bf16/{name}_embeddings.npz') as b:
            x=a['embedding_0'].astype(np.float64).ravel()
            y=b['embedding_0'].astype(np.float64).ravel()
            cross_engine.append(dict(case=name,cosine=float(x@y/np.linalg.norm(x)/np.linalg.norm(y)),
                                     relative_l2=float(np.linalg.norm(x-y)/np.linalg.norm(x)),
                                     identical=bool(np.array_equal(x,y))))
    report=dict(status='passed',scope='paired numerical differences, not perceptual-quality acceptance',
                cases=rows,historical_bf16_repeat=historical,timings=timings,
                identical_shared_embeddings=sharing,bf16_cross_engine_embeddings=cross_engine,benchmark=summary)
    (ROOT/'comparison_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (ROOT/'comparison_metrics.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in report.items() if k!='benchmark'},indent=2))

if __name__=='__main__': main()
