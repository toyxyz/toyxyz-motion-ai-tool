"""GPU work lives here, outside Blender. Writes an atomic JSON result."""
import argparse
import json
from pathlib import Path
import sys
import time
import os
from contextlib import redirect_stdout,redirect_stderr

_kimodo_cache=None
_motionbricks_cache=None
_ardy_cache=None
_loads=0


def atomic_json(path,value):
    temp=path.with_suffix('.partial')
    temp.write_text(json.dumps(value,allow_nan=False,separators=(',',':')),encoding='utf-8')
    for attempt in range(50):
        try:temp.replace(path);return
        except PermissionError:
            # A Windows health reader can briefly hold the old state file open.
            if attempt==49:raise
            time.sleep(.01)


def filter_empty_kimodo_constraints(model):
    """Pinned Kimodo crops every target per segment, including empty target sets.

    Its frame writer cannot reshape an empty set. Filter on this worker's model
    instance only; retain the official multi-prompt transition/postprocess path.
    """
    original=model.motion_rep.create_conditions_from_constraints
    def create(constraints_lst,*args,**kwargs):
        # crop_move rebuilds end-effector index tensors on CPU in this release.
        # Restore their device before the native condition writer pairs indices.
        return original([c.to(model.device) for c in constraints_lst if len(c.frame_indices)],*args,**kwargs)
    model.motion_rep.create_conditions_from_constraints=create


def kimodo(data,progress=None):
    global _kimodo_cache,_loads
    progress=progress or (lambda *args,**kwargs:None)
    progress(0,'Loading Kimodo model',force=True)
    import numpy as np
    import math
    import torch
    from kimodo import load_model
    from kimodo.skeleton import SOMASkeleton77
    from kimodo.constraints import FullBodyConstraintSet,Root2DConstraintSet,TYPE_TO_CLASS,compute_global_heading
    from root_height_constraint import with_height,height_errors
    from shared_encoder_client import SharedEncoderClient
    from motion_bridge_protocol import model_frame_index,next_pose_targets,path_runs,set_object_effector,object_effector_samples,object_root_points
    from kimodo_transitions import transition_frames
    client=SharedEncoderClient('kimodo',precision=data['precision'])
    if _kimodo_cache is None:
        model=load_model('Kimodo-SOMA-RP-v1.2',device='cuda',text_encoder=client)
        filter_empty_kimodo_constraints(model)
        _kimodo_cache=(model,SOMASkeleton77().to('cuda'));_loads+=1
    model,full=_kimodo_cache
    # A new proxy follows encoder profile/instance changes without reloading motion weights.
    model.text_encoder=client
    fps=data['fps'];start=data['blocks'][0]['start']
    paths=[(at,np.asarray(points,dtype=np.float32),uid) for at,points,uid in path_runs(data)]
    def path_point(index):
        for at,points,uid in paths:
            if at<=index<at+len(points):return points[index-at]
        return None
    origin=np.zeros(3,dtype=np.float32)
    if data['poses']:
        origin[[0,2]]=np.asarray(data['poses'][0]['root'])[[0,2]]
    if paths and paths[0][0]==0:origin[[0,2]]=paths[0][1][0]
    constraints=[]
    mapped=[]
    kinds={'LEFT_HAND':'left-hand','RIGHT_HAND':'right-hand','LEFT_FOOT':'left-foot','RIGHT_FOOT':'right-foot'}
    object_effectors=object_effector_samples(data);object_roots=object_root_points(data)
    end=data['blocks'][-1]['end']
    lengths=[round((b['end']-start)*30/fps)-round((b['start']-start)*30/fps) for b in data['blocks']]
    output_frames=sum(lengths)
    following=next_pose_targets(data,output_frames)
    lengths[-1]+=len(following)
    targets=[(model_frame_index(pose['frame'],start,end,fps),pose) for pose in data['poses']]+following
    for index,pose in targets:
        local=torch.tensor([pose['local_rotations']],dtype=torch.float32,device='cuda')
        # Validate rotations, not just array dimensions, before sending to the model.
        eye=torch.eye(3,device='cuda')
        if (local.transpose(-1,-2)@local-eye).abs().max()>.002 or (torch.linalg.det(local)-1).abs().max()>.002:
            raise ValueError('Invalid pose rotation matrices.')
        local=model.skeleton.from_SOMASkeleton77(local)
        root_value=np.asarray(pose['root'],dtype=np.float32).copy();point=path_point(index)
        goal=pose.get('object_goal')
        if goal and pose['kind']=='ROOT':root_value=np.asarray(goal['position'],dtype=np.float32)
        if point is not None and pose['kind'] in ('FULL','ROOT') and pose.get('source')!='previous_motion_end':root_value[[0,2]]=point
        root=torch.tensor(np.asarray([root_value],dtype=np.float32)-origin,device='cuda')
        rotations,positions,_=model.skeleton.fk(local,root)
        frames=torch.tensor([index],device='cuda')
        if pose['kind']=='ROOT':
            heading=(root.new_tensor([goal['heading']]) if goal else compute_global_heading(positions,model.skeleton)) if pose.get('root_heading') else None
            if pose.get('root_height'):
                constraint=with_height(Root2DConstraintSet)(model.skeleton,frames,root[:,[0,2]],positions[:,model.skeleton.root_idx,1],heading)
            else:constraint=Root2DConstraintSet(model.skeleton,frames,root[:,[0,2]],global_root_heading=heading)
        elif pose['kind']=='FULL':
            smooth=torch.tensor([point-origin[[0,2]]],dtype=torch.float32,device='cuda') if point is not None else None
            constraint=FullBodyConstraintSet(model.skeleton,frames,positions,rotations,smooth_root_2d=smooth)
        else:
            reference=object_roots.get(index,point)
            centered=np.asarray(reference,dtype=np.float32)-origin[[0,2]] if reference is not None else None
            smooth=root.new_tensor([centered.tolist()]) if centered is not None else None
            for target in object_effectors.get(index,()):
                set_object_effector(model.skeleton,target,positions,rotations,origin,postprocess=data.get('postprocess',True),
                                    root_2d=centered)
            constraint=TYPE_TO_CLASS[kinds[pose['kind']]](model.skeleton,frames,positions,rotations,smooth)
        constraints.append(constraint.to('cuda'))
        mapped.append(dict(frame=pose['frame'],model_frame=index,kind=pose['kind']))
    for at,points,uid in paths:
        constraints.append(Root2DConstraintSet(model.skeleton,torch.arange(at,at+len(points),device='cuda'),
                                              torch.tensor(points-origin[[0,2]],device='cuda')).to('cuda'))
    previous=data.get('previous_motion_context');prefix=0;previous_motion=None
    if previous:
        prefix=previous['frame_count'];history=previous['poses']
        local=torch.tensor([p['local_rotations'] for p in history],dtype=torch.float32,device='cuda')
        eye=torch.eye(3,device='cuda')
        if (local.transpose(-1,-2)@local-eye).abs().max()>.002 or (torch.linalg.det(local)-1).abs().max()>.002:
            raise ValueError('Invalid previous motion rotation matrices.')
        local=model.skeleton.from_SOMASkeleton77(local)[None]
        root=torch.tensor(np.asarray([[p['root'] for p in history]],dtype=np.float32)-origin,device='cuda')
        with torch.inference_mode():
            previous_motion=model.motion_rep(local,root,to_normalize=False,lengths=torch.tensor([len(history)],device='cuda'))[:,-prefix:]
    torch.manual_seed(data['seed']);torch.cuda.manual_seed_all(data['seed'])
    total=len(lengths)*data['steps'];completed=0;segment=0
    def progress_bar(iterable,*args,**kwargs):
        nonlocal completed,segment
        segment+=1;step=0
        progress(.98*completed/total,f'Kimodo block {segment}/{len(lengths)}: step 0/{data["steps"]}',completed,total,force=True)
        for value in iterable:
            yield value
            step+=1;completed+=1
            progress(.98*completed/total,f'Kimodo block {segment}/{len(lengths)}: step {step}/{data["steps"]}',completed,total)
        progress(.98*completed/total,'Post-processing Kimodo motion',completed,total,force=True)
    # This pinned multi-prompt implementation does not forward its public
    # progress_bar argument to _generate. Inject it only on our model instance.
    original_generate=model._generate;generated_context_frames=[]
    def generate_with_progress(*args,**kwargs):
        generated_context_frames.append(int(args[1])-lengths[len(generated_context_frames)])
        kwargs['progress_bar']=progress_bar
        return original_generate(*args,**kwargs)
    model._generate=generate_with_progress
    initial_heading=None
    if paths and paths[0][0]==0 and len(paths[0][1])>1 and not any(p['frame']==start for p in data['poses']):
        delta=paths[0][1][1]-paths[0][1][0];initial_heading=math.atan2(float(delta[0]),float(delta[1]))
    try:
        with torch.inference_mode(),transition_frames(model,[b.get('transition_frames',5) for b in data['blocks']],previous_motion):
            output=model(prompts=[b['prompt'] for b in data['blocks']],num_frames=lengths,multi_prompt=True,
                         num_denoising_steps=data['steps'],num_samples=1,constraint_lst=constraints,
                         cfg_weight=[float(data.get('text_weight',2)),float(data.get('constraint_weight',2))],
                         post_processing=bool(data.get('postprocess',True)),return_numpy=True,first_heading_angle=initial_heading)
    finally:model._generate=original_generate
    if prefix:
        # The official transition returns its history prefix as well. Keep the
        # existing clip untouched and apply only the newly selected interval.
        total_frames=prefix+sum(lengths)
        for key,value in output.items():
            if isinstance(value,np.ndarray):
                if value.ndim>=2 and value.shape[0]==1 and value.shape[1]==total_frames:output[key]=value[:,prefix:]
                elif value.ndim and value.shape[0]==total_frames:output[key]=value[prefix:]
    local=np.asarray(output['local_rot_mats']);root=np.asarray(output['root_positions'])
    if local.ndim==5:local=local[0];root=root[0]
    root=root+origin
    assert local.shape==(sum(lengths),77,3,3) and root.shape==(sum(lengths),3)
    assert np.isfinite(local).all() and np.isfinite(root).all()
    # Measure constrained joint positions after the actual 77->30->77 conversion.
    errors=[]
    positions=np.asarray(output['posed_joints'])
    if positions.ndim==4:positions=positions[0]
    positions=positions+origin
    with torch.inference_mode():
        for (_,pose),item in zip(targets,mapped):
            root_value=np.asarray(pose['root'],dtype=np.float32).copy();point=path_point(item['model_frame'])
            if point is not None and pose['kind'] in ('FULL','ROOT') and pose.get('source')!='previous_motion_end':root_value[[0,2]]=point
            _,reference,_=full.fk(torch.tensor([pose['local_rotations']],device='cuda'),torch.tensor([root_value],device='cuda'))
            ids=[full.bone_index[n] for n in model.skeleton.bone_order_names]
            if pose['kind'] in kinds:
                joint={'LEFT_HAND':'LeftHand','RIGHT_HAND':'RightHand','LEFT_FOOT':'LeftFoot','RIGHT_FOOT':'RightFoot'}[pose['kind']]
                ids=[full.bone_index[joint]]
            elif pose['kind']=='ROOT':ids=[0]
            goal=pose.get('object_goal')
            wanted=np.asarray([goal['position']]) if goal else reference[0,ids].cpu().numpy()
            difference=positions[item['model_frame'],ids]-wanted
            if pose['kind']=='ROOT':difference=difference[:,[0,2]]
            errors.append(dict(**item,max_position_error_m=float(np.linalg.norm(difference,axis=-1).max())))
    path_errors=[];smooth=np.asarray(output['smooth_root_pos'])
    if smooth.ndim==3:smooth=smooth[0]
    smooth=smooth+origin
    for at,points,uid in paths:
        difference=np.linalg.norm(smooth[at:at+len(points)][:,[0,2]]-points,axis=-1)
        hips=np.linalg.norm(root[at:at+len(points)][:,[0,2]]-points,axis=-1)
        path_errors.append(dict(uid=uid,max_smooth_root_error_m=float(difference.max()),mean_smooth_root_error_m=float(difference.mean()),max_hips_error_m=float(hips.max())))
    return dict(local_rotations=local[:output_frames].tolist(),root_positions=root[:output_frames].tolist(),fps=30,
                transition_context_frames=generated_context_frames,
                previous_motion_context_frames=prefix,previous_motion_context_uid=previous.get('uid') if previous else None,
                root_path_errors=path_errors,root_height_errors=height_errors(data,root),smooth_root_positions=smooth[:output_frames].tolist() if paths else None,
                progress_work_completed=completed,progress_work_total=total,
                encoder_instance=client.identity['instance_id'],encoder_load_count=client.identity['model_load_count'],
                constraint_errors=errors,frame_count=output_frames,source='real Kimodo-SOMA-RP-v1.2')


def motionbricks(data,progress=None):
    global _motionbricks_cache,_loads
    progress=progress or (lambda *args,**kwargs:None)
    progress(0,'Loading MotionBricks model',force=True)
    import numpy as np
    import warp as wp
    from scipy.spatial.transform import Rotation,Slerp
    from motion_bridge_protocol import SCHEMA,motionbricks_segments,model_frame_index
    from entry import ROOT
    import os
    os.chdir(ROOT/'engines/motionbricks')
    from native_paths import configure_warp
    configure_warp()
    from motionbricks_soma_adapter import SOMAAdapter
    from motionbricks.model.soma.engine import MotionBricksSOMAEngine
    from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH
    wp.init();wp.set_device('cuda:0')
    if _motionbricks_cache is None:
        adapter=SOMAAdapter(SCHEMA);skeleton=adapter.skeleton
        engine=MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH)
        with wp.ScopedStream(engine.stream):
            context=engine.create_input(skeleton);target=engine.create_input(skeleton);output=engine.create_output(skeleton)
        _motionbricks_cache=(engine,adapter,context,target,output);_loads+=1
    engine,adapter,context,target,output=_motionbricks_cache
    def local_pose(p):return adapter.to_native(p)
    local_results=[];root_results=[];raw_counts=[];context_array=None;contexts=[];window_counts=[]
    segments=motionbricks_segments(data)
    with wp.ScopedStream(engine.stream):
        for segment_index,segment in enumerate(segments):
            progress(.98*segment_index/len(segments),f'MotionBricks transition {segment_index+1}/{len(segments)}',segment_index,len(segments),force=True)
            if context_array is None:
                history=segment['first'].get('history',[segment['first']]*4)
                context_array=np.stack([local_pose(p) for p in history])
            contexts.append('authored_history' if not raw_counts else 'previous_output_tail_4')
            context.update_from_poses(wp.array(context_array,dtype=wp.transform,device=engine.device),stream=engine.stream)
            target_window=segment['last'].get('target_poses',[segment['last']])
            window_counts.append(len(target_window))
            target.update_from_poses(wp.array(np.stack([local_pose(p) for p in target_window]),dtype=wp.transform,device=engine.device),stream=engine.stream)
            engine.generate_animation(context,target,output);engine.synchronize()
            raw=output.poses[:output.num_frames].numpy();raw_counts.append(len(raw))
            canonical_rotations=adapter.to_canonical(raw)
            count=segment['samples']
            times=np.linspace(0,len(raw)-1,count)
            roots=np.stack([np.interp(times,np.arange(len(raw)),raw[:,0,axis]) for axis in range(3)],axis=-1)
            rotations=np.stack([Slerp(np.arange(len(raw)),Rotation.from_matrix(canonical_rotations[:,j]))(times).as_matrix() for j in range(77)],axis=1)
            if not local_results:
                leading=model_frame_index(segment['first']['frame'],data['blocks'][0]['start'],data['blocks'][-1]['end'],data['fps'])
                if leading:
                    local_results.append(np.repeat(rotations[:1],leading,axis=0));root_results.append(np.repeat(roots[:1],leading,axis=0))
            drop=segment['drop'];local_results.append(rotations[drop:]);root_results.append(roots[drop:])
            # Feed the last four resampled poses actually used by Blender, including short spans.
            tail_root=np.concatenate(root_results)[-4:];tail_rot=np.concatenate(local_results)[-4:]
            if len(tail_root)<4:
                pad=4-len(tail_root)
                context_array=np.concatenate([context_array[-pad:],np.stack([local_pose(dict(root=r,local_rotations=q)) for r,q in zip(tail_root,tail_rot)])])
            else:context_array=np.stack([local_pose(dict(root=r,local_rotations=q)) for r,q in zip(tail_root,tail_rot)])
            progress(.98*(segment_index+1)/len(segments),f'MotionBricks transition {segment_index+1}/{len(segments)} complete',segment_index+1,len(segments),force=True)
    local=np.concatenate(local_results);root=np.concatenate(root_results)
    # Block bounds stay linked to NLA. The last authored target keeps its timing;
    # unused time after it holds that pose instead of stretching the transition.
    total=round((data['blocks'][-1]['end']-data['blocks'][0]['start'])*30/data['fps'])
    trailing=total-len(root)
    if trailing>0:
        local=np.concatenate([local,np.repeat(local[-1:],trailing,axis=0)])
        root=np.concatenate([root,np.repeat(root[-1:],trailing,axis=0)])
    if data.get('next_motion_context'):
        local,root=local[:total],root[:total]
    return dict(local_rotations=local.tolist(),root_positions=root.tolist(),fps=30,frame_count=len(root),
                progress_work_completed=len(segments),progress_work_total=len(segments),
                soma_frame_adapter='native_usd_joint_frames_v1',
                raw_segment_frames=raw_counts,context_sources=contexts,target_window_counts=window_counts,retimed=True,source='real MotionBricks-SOMA-RP-v1 FP32 TensorRT',
                pose_key_frames=[p['frame'] for p in data['poses']],
                notes=['Transitions pass through every keyed pose and are resampled to the authored timing. Adjacent blocks share generated motion history; interior target windows carry authored velocity. The final keyed pose requests a stop and is held through unused block time.'])


def match_following_boundary(data,result,following):
    """Ease the generated tail into the measured pose and velocity at the next clip."""
    import numpy as np
    from scipy.spatial.transform import Rotation
    from motion_bridge_protocol import model_frame_index

    start=data['blocks'][0]['start'];last=data['blocks'][-1];end=last['end'];fps=data['fps']
    last_start=round((last['start']-start)*30/fps)
    keyed=[model_frame_index(p['frame'],start,end,fps) for p in data['poses'] if last['start']<=p['frame']<end]
    count=result['frame_count']
    first=max(1,last_start,count-12,max(keyed,default=-1)+1)
    if first>=count:return
    roots=result['root_positions'];rotations=result['local_rotations']
    next_root=np.asarray(following[0]['root'])
    next_pose=Rotation.from_matrix(following[0]['local_rotations'])
    velocity=np.zeros(3);angular_velocity=np.zeros((77,3))
    if len(following)>1:
        velocity=np.asarray(following[1]['root'])-next_root
        angular_velocity=(next_pose.inv()*Rotation.from_matrix(following[1]['local_rotations'])).as_rotvec()
    for index in range(first,count):
        distance=count-index
        # Match the last two samples exactly and taper the correction earlier.
        t=min(1.,(index-first+1)/max(1,count-first-1))
        weight=t*t*(3.-2.*t)
        lead=min(4,distance)
        target_root=next_root-velocity*lead
        root=np.asarray(roots[index])
        if last.get('root_path'):
            target_root[[0,2]]=root[[0,2]]
        pose=Rotation.from_matrix(rotations[index])
        target_pose=next_pose*Rotation.from_rotvec(-angular_velocity*lead)
        roots[index]=(root+weight*(target_root-root)).tolist()
        rotations[index]=(pose*Rotation.from_rotvec(weight*(pose.inv()*target_pose).as_rotvec())).as_matrix().tolist()


def execute(request,output):
    data=json.loads(request.read_text(encoding='utf-8'))
    from motion_bridge_protocol import validate,SCHEMA,APP,VERSION
    from motion_progress import ProgressReporter
    data=validate(data);started=time.monotonic();reused=_loads>0
    progress=ProgressReporter(output.with_name('progress.json'));progress(0,'Preparing generation',force=True)
    if data['engine']=='ardy':
        from ardy_bridge import generate
        result=generate(data,progress,sys.modules[__name__])
    else:result=kimodo(data,progress) if data['engine']=='kimodo' else motionbricks(data,progress)
    following=data.get('next_motion_context')
    if following:
        match_following_boundary(data,result,following['poses'])
        result.update(next_motion_reference=following['reference'],next_motion_frames=len(following['poses']),
                      next_motion_pose=following['poses'][0])
    result.update(app=APP,protocol=VERSION,status='succeeded',engine=data['engine'],blocks=data['blocks'],precision=data['precision'] if data['engine'] in ('kimodo','ardy') else 'fp32',
                  text_encoder_precision=data['precision'] if data['engine'] in ('kimodo','ardy') else None,
                  joint_names=SCHEMA['names'],start=data['blocks'][0]['start'],end=data['blocks'][-1]['end'],
                  scene_fps=data['fps'],elapsed_seconds=time.monotonic()-started,
                  worker_pid=os.getpid(),model_load_count=_loads,model_reused=reused)
    progress(.99,'Writing generated motion',force=True);atomic_json(output,result)
    motion_fields={'local_rotations','root_positions','joint_names','next_motion_pose','ardy_blocks','ardy_join'}
    print(json.dumps({k:v for k,v in result.items() if k not in motion_fields}),flush=True)


def serve(engine,mailbox):
    """One trusted app-owned mailbox, one request at a time, one resident engine."""
    from entry import ROOT
    import traceback,faulthandler
    completed=0
    def state(status):
        value=dict(engine=engine,pid=os.getpid(),status=status,model_load_count=_loads,jobs_completed=completed)
        if (engine=='kimodo' and _kimodo_cache is not None) or (engine=='ardy' and _ardy_cache is not None):
            import torch
            torch.cuda.empty_cache()
            value.update(cuda_allocated_bytes=torch.cuda.memory_allocated(),cuda_reserved_bytes=torch.cuda.memory_reserved())
        atomic_json(mailbox/'state.json',value)
    state('ready')
    while True:
        command=mailbox/'command.json'
        if not command.exists():time.sleep(.04);continue
        item=json.loads(command.read_text(encoding='utf-8'));command.unlink()
        request=Path(item['request']);output=Path(item['output'])
        # Commands are generated by the local app, never accepted over a worker socket.
        if request.parent.resolve()!=output.parent.resolve() or not request.resolve().is_relative_to((ROOT/'results').resolve()):
            raise ValueError('Invalid worker request paths')
        state('generating')
        logpath=ROOT/'logs'/f'toyxyz_motion_ai_tool_{output.parent.name}.log'
        with logpath.open('a',encoding='utf-8',buffering=1) as log:
            with redirect_stdout(log),redirect_stderr(log):
                faulthandler.enable(file=log)
                try:
                    data=json.loads(request.read_text(encoding='utf-8'))
                    if data['engine']!=engine:raise ValueError('Motion worker engine mismatch')
                    execute(request,output);completed+=1
                except BaseException as exc:
                    atomic_json(output.with_name('error.json'),dict(error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
                finally:faulthandler.enable(file=sys.__stderr__)
        state('idle')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--serve',action='store_true');parser.add_argument('--engine',choices=['kimodo','motionbricks','ardy'])
    parser.add_argument('--mailbox',type=Path)
    args=parser.parse_args()
    from entry import bootstrap
    if args.serve:
        if not args.engine or not args.mailbox:parser.error('--serve requires --engine and --mailbox')
        bootstrap(args.engine);serve(args.engine,args.mailbox)
    else:
        if not args.request or not args.output:parser.error('--request and --output are required')
        data=json.loads(args.request.read_text(encoding='utf-8'));bootstrap(data['engine'])
        execute(args.request,args.output)


def configure_logging():
    """Open our own stream when launched from a Windows GUI without Python stdio."""
    if '--output' not in sys.argv:return
    output=Path(sys.argv[sys.argv.index('--output')+1]);ident=output.parent.name
    if len(ident)==32 and all(c in '0123456789abcdef' for c in ident):
        log=Path(__file__).resolve().parents[1]/'logs'/f'toyxyz_motion_ai_tool_{ident}.log'
    else:log=output.with_suffix('.log')
    log.parent.mkdir(parents=True,exist_ok=True)
    stream=log.open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=stream
    import faulthandler
    faulthandler.enable(file=stream,all_threads=True)


if __name__=='__main__':
    configure_logging()
    try:main()
    except BaseException as exc:
        # Some Windows GUI launchers have no usable inherited stderr. Persist the
        # Python failure independently of subprocess stdout/stderr redirection.
        import traceback
        if '--output' in sys.argv:
            try:
                output=Path(sys.argv[sys.argv.index('--output')+1])
                error=dict(error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
                output.with_name('error.json').write_text(json.dumps(error,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception:pass
        raise
