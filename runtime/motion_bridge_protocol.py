"""Versioned, bounded JSON protocol shared with the Blender-facing local app."""
import json
import math
from pathlib import Path

APP='toyxyz_motion_ai_tool'
VERSION=1
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'addons'/APP/'soma.json').read_text(encoding='utf-8'))
MODEL_LIMITS=json.loads((ROOT/'addons'/APP/'model_limits.json').read_text(encoding='utf-8'))
KINDS={'FULL','ROOT','LEFT_HAND','RIGHT_HAND','LEFT_FOOT','RIGHT_FOOT'}


def finite_array(value,shape):
    if not shape:
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    return isinstance(value,list) and len(value)==shape[0] and all(finite_array(x,shape[1:]) for x in value)


def model_frame_index(frame,start,end,fps):
    """Nearest 30 Hz sample, bounded by the exclusive-end output length.

    At 60 FPS, frame 120 in [1,121) rounds to sample 60, but the
    two-second output contains only samples 0..59.
    """
    count=round((end-start)*30/fps)
    return max(0,min(count-1,round((frame-start)*30/fps)))


def validate(data):
    if not isinstance(data,dict) or data.get('protocol')!=VERSION:raise ValueError('Unsupported protocol version.')
    if 'terrain' in data:raise ValueError('Ground Mesh was removed. Generate again with the updated addon.')
    engine=data.get('engine')
    if engine not in ('kimodo','motionbricks','ardy'):raise ValueError('Choose Kimodo, MotionBricks or ARDY.')
    if data.get('precision','bf16') not in ('bf16','int8','nf4'):raise ValueError('Invalid encoder precision.')
    fps=data.get('fps',30)
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not math.isfinite(fps) or not 1<=fps<=240:raise ValueError('FPS must be between 1 and 240.')
    if data.get('joint_names')!=SCHEMA['names']:raise ValueError('The SOMA hierarchy differs from this installation.')
    blocks=data.get('blocks')
    if not isinstance(blocks,list) or not 1<=len(blocks)<=32:raise ValueError('Add between 1 and 32 generation blocks.')
    if not all(isinstance(b,dict) and isinstance(b.get('start'),int) for b in blocks):raise ValueError('Invalid motion block data.')
    blocks=sorted(blocks,key=lambda b:b['start'])
    last=None
    for index,b in enumerate(blocks):
        if not all(isinstance(b.get(k),int) and not isinstance(b[k],bool) for k in ('start','end')):raise ValueError('Block frames must be integers.')
        if b['end']<=b['start'] or abs(b['start'])>1000000:raise ValueError('Check each block start and end frame.')
        duration=(b['end']-b['start'])/fps
        limits=MODEL_LIMITS[engine];model_frames=duration*limits['sample_rate']
        maximum=math.inf if limits['max_frames'] is None else limits['max_frames']
        if not limits['min_frames']-1e-6<=model_frames<=maximum+1e-6:
            raise ValueError({'kimodo':'Kimodo blocks must last 2–10 seconds.','motionbricks':'MotionBricks blocks must span 18–58 frames at 30 FPS (0.6–1.933 seconds).','ardy':'ARDY blocks must span at least one model frame at 30 FPS.'}[engine])
        if last is not None and last!=b['start']:raise ValueError('Blocks for one model must be contiguous, without gaps or overlaps.')
        if not isinstance(b.get('prompt',''),str) or len(b.get('prompt',''))>4000:raise ValueError('The prompt is too long.')
        if engine in ('kimodo','ardy') and not b.get('prompt','').strip():raise ValueError('Enter a prompt for each text-driven block.')
        if engine=='kimodo':
            overlap=b.get('transition_frames',5)
            if isinstance(overlap,bool) or not isinstance(overlap,int) or not 1<=overlap<=300:
                raise ValueError('Transition Overlap must be 1–300 model frames at 30 FPS.')
            if index:
                previous=blocks[index-1]
                available=round((previous['end']-blocks[0]['start'])*30/fps)-round((previous['start']-blocks[0]['start'])*30/fps)
                if overlap>available:raise ValueError(f'Transition Overlap exceeds the previous Kimodo block length ({available} frames at 30 FPS).')
        path=b.get('root_path')
        if path is not None:
            count=round((b['end']-blocks[0]['start'])*30/fps)-round((b['start']-blocks[0]['start'])*30/fps)
            if engine not in ('kimodo','ardy'):raise ValueError('Path Curves are supported for Kimodo and ARDY blocks only.')
            if not isinstance(path,dict):raise ValueError('Invalid Path Curve samples.')
            offset=path.get('start_index',0)
            if isinstance(offset,bool) or not isinstance(offset,int) or not 0<=offset<count:raise ValueError('Invalid Path Curve start sample.')
            if not finite_array(path.get('points'),(count-offset,2)):raise ValueError('Invalid Path Curve samples.')
            if any(abs(v)>1000 for point in path['points'] for v in point):raise ValueError('Path Curve exceeds the allowed coordinate range.')
            if not isinstance(path.get('curve'),str) or not isinstance(path.get('signature'),str):raise ValueError('Invalid Path Curve metadata.')
        if 'foot_contact' in b:raise ValueError('Foot Contact was removed. Generate again with the updated addon.')
        last=b['end']
    if engine!='ardy' and (blocks[-1]['end']-blocks[0]['start'])/fps>60:raise ValueError('A non-ARDY job can contain at most 60 seconds of motion.')
    previous=data.get('previous_motion_context')
    if previous is not None:
        if engine not in ('kimodo','ardy') or not isinstance(previous,dict):raise ValueError('Invalid previous motion context.')
        count=previous.get('frame_count');history=previous.get('poses')
        if (isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=300
            or (engine=='kimodo' and count!=blocks[0].get('transition_frames',5))
            or (engine=='ardy' and count>240) or not isinstance(history,list) or len(history)!=max(5,count)):
            raise ValueError('Previous motion context must match the first block Transition Overlap.')
        times=previous.get('sample_frames')
        samples=max(5,count)
        if not finite_array(times,(samples,)):raise ValueError('Invalid previous motion sample times.')
        expected=[blocks[0]['start']-(samples-i)*fps/30 for i in range(samples)]
        if any(abs(a-b)>1e-4 for a,b in zip(times,expected)):raise ValueError('Previous motion context must immediately precede the selected block at 30 FPS.')
        for pose in history:
            if (not isinstance(pose,dict) or not finite_array(pose.get('root'),(3,))
                or not finite_array(pose.get('local_rotations'),(77,3,3)) or max(abs(v) for v in pose['root'])>1000):
                raise ValueError('Invalid previous motion pose data.')
    poses=data.get('poses',[])
    if not isinstance(poses,list) or len(poses)>100:raise ValueError('Too many pose targets.')
    counts={}
    object_samples=set();full_samples=set()
    for p in poses:
        if not isinstance(p,dict):raise ValueError('Invalid pose target.')
        if p.get('kind') not in KINDS or not isinstance(p.get('frame'),int):raise ValueError('Check the pose frame and target type.')
        if 'root_heading' in p and (not isinstance(p['root_heading'],bool) or p['kind']!='ROOT'):
            raise ValueError('Root Heading must be a boolean option on a Root Position (2D) target.')
        if 'root_height' in p and (not isinstance(p['root_height'],bool) or p['kind']!='ROOT'):
            raise ValueError('Root Height must be a boolean option on a Root Position (2D) target.')
        if not blocks[0]['start']<=p['frame']<blocks[-1]['end']:raise ValueError('Pose targets must be inside the generation range. The block end frame is exclusive.')
        if not finite_array(p.get('root'),(3,)) or not finite_array(p.get('local_rotations'),(77,3,3)):raise ValueError('Invalid pose data.')
        if max(abs(v) for v in p['root'])>1000:raise ValueError('Root position exceeds the allowed range.')
        if 'object_goal' in p:
            validate_object_goal(p,engine)
        for field in ('history','target_poses'):
            if field not in p:continue
            window=p[field]
            if not isinstance(window,list) or len(window) not in ((4,) if field=='history' else (1,2,3,4)):
                raise ValueError('Invalid MotionBricks pose window length.')
            for sample in window:
                if not isinstance(sample,dict) or not finite_array(sample.get('root'),(3,)) or not finite_array(sample.get('local_rotations'),(77,3,3)):
                    raise ValueError('Invalid MotionBricks pose window.')
                if max(abs(v) for v in sample['root'])>1000:raise ValueError('Pose window root position exceeds the allowed range.')
        key=(p['kind'],model_frame_index(p['frame'],blocks[0]['start'],blocks[-1]['end'],fps))
        if p['kind']=='FULL':full_samples.add(key[1])
        if 'object_goal' in p:object_samples.add(key[1])
        if key in counts:raise ValueError(f"Pose keys at frames {counts[key]} and {p['frame']} are too close: they map to the same 30 FPS model sample. Space those keys farther apart.")
        counts[key]=p['frame']
    if object_samples & full_samples:raise ValueError('Object constraints cannot share a 30 FPS model sample with a Full Body pose.')
    for kind in KINDS:
        if engine=='kimodo' and sum(p['kind']==kind for p in poses)>=20:raise ValueError('Kimodo accepts at most 19 targets per constraint type per job. Remove keys or shorten the selection.')
    if engine=='motionbricks':
        if any(p['kind']!='FULL' for p in poses):raise ValueError('This MotionBricks adapter accepts full-body targets.')
        if len(poses)<(1 if data.get('next_motion_context') is not None else 2):
            raise ValueError('MotionBricks needs two SOMA poses. Adjacent generated motion can supply the start or the destination.')
    steps=data.get('steps',10 if engine=='ardy' else 30)
    if not isinstance(steps,int) or not 1<=steps<=(10 if engine=='ardy' else 200):raise ValueError('ARDY denoising steps must be 1–10.' if engine=='ardy' else 'Denoising steps must be between 1 and 200.')
    seed=data.get('seed',0)
    if not isinstance(seed,int) or not 0<=seed<2**31:raise ValueError('Seed is out of range.')
    for key in ('text_weight','constraint_weight'):
        value=data.get(key,2)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=20:raise ValueError('Guidance weights must be between 0 and 20.')
    data=dict(data,blocks=blocks,poses=sorted(poses,key=lambda p:p['frame']),steps=steps,seed=seed,fps=float(fps))
    validate_next_motion(data)
    if engine=='motionbricks':motionbricks_segments(data)
    return data


def validate_next_motion(data):
    context=data.get('next_motion_context')
    if context is None:return
    if not isinstance(context,dict):raise ValueError('Invalid following motion context.')
    end=data['blocks'][-1]['end'];fps=data['fps']
    reference=context.get('reference')
    if not isinstance(reference,dict):raise ValueError('Invalid following motion reference.')
    overlap=reference.get('overlap');clip_end=reference.get('clip_end')
    limit=300 if data['engine']=='kimodo' else 4
    if (type(overlap) is not int or not 1<=overlap<=limit or not finite_array(clip_end,()) or clip_end<=end
        or not isinstance(reference.get('uid'),str) or type(reference.get('action_uid')) is not int):
        raise ValueError('Invalid following motion reference.')
    count=min(overlap,max(1,math.floor((clip_end-end)*30/fps+1e-6)))
    times=context.get('sample_frames');poses=context.get('poses')
    if (not finite_array(times,(count,)) or any(abs(at-(end+i*fps/30))>1e-4 for i,at in enumerate(times))
        or not isinstance(poses,list) or len(poses)!=count):
        raise ValueError('Following motion context must start at the block end and be sampled at 30 FPS.')
    for pose in poses:
        if (not isinstance(pose,dict) or not finite_array(pose.get('root'),(3,))
            or max(map(abs,pose['root']))>1000 or not finite_array(pose.get('local_rotations'),(77,3,3))):
            raise ValueError('Invalid following motion pose data.')


def next_pose_targets(data,first_index):
    context=data.get('next_motion_context')
    if context is None:return []
    return [(first_index+i,dict(pose,kind='FULL',frame=context['sample_frames'][i]))
            for i,pose in enumerate(context['poses'])]


def validate_object_goal(pose,engine):
    goal=pose['object_goal'];kind=pose['kind']
    if engine=='motionbricks' or kind=='FULL' or not isinstance(goal,dict):
        raise ValueError('Object constraints require a partial target in Kimodo or ARDY.')
    position=goal.get('position')
    if not finite_array(position,(3,)) or max(map(abs,position))>1000:
        raise ValueError('Invalid object constraint position.')
    if kind=='ROOT':
        heading=goal.get('heading')
        if pose.get('root_heading') or 'heading' in goal:
            if not pose.get('root_heading') or not finite_array(heading,(2,)) or abs(math.hypot(*heading)-1)>.002:
                raise ValueError('Invalid object root heading.')
        if 'rotation' in goal or goal.get('height',False) is not pose.get('root_height',False):
            raise ValueError('Invalid object root height option.')
    else:
        rotation=goal.get('rotation')
        if not finite_array(rotation,(3,3)) or 'heading' in goal or 'height' in goal:
            raise ValueError('Invalid object constraint rotation.')
        a,b,c=rotation
        dot=lambda u,v:sum(x*y for x,y in zip(u,v))
        cross=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
        if abs(dot(cross,c)-1)>.002 or any(abs(dot(u,v)-(i==j))>.002 for i,u in enumerate(rotation) for j,v in enumerate(rotation)):
            raise ValueError('Object constraint rotation must be a proper rotation matrix.')


def object_effector_samples(data):
    start=data['blocks'][0]['start'];end=data['blocks'][-1]['end']
    samples={}
    for pose in data['poses']:
        if pose['kind']=='ROOT' or 'object_goal' not in pose:continue
        index=model_frame_index(pose['frame'],start,end,data['fps'])
        samples.setdefault(index,[]).append(pose)
    return samples


def object_root_points(data):
    start=data['blocks'][0]['start'];end=data['blocks'][-1]['end']
    return {model_frame_index(p['frame'],start,end,data['fps']):p['object_goal']['position'][::2]
            for p in data.get('poses',()) if p['kind']=='ROOT' and 'object_goal' in p}


def seed_effector_rotations(skeleton,positions,rotations,pivot,target):
    """Give stock correction a reachable FK reference without adding model pose masks."""
    import numpy as np
    from scipy.spatial.transform import Rotation

    lower=int(skeleton.joint_parents[pivot]);upper=int(skeleton.joint_parents[lower])
    start,mid,end=positions[0,[upper,lower,pivot]].detach().cpu().numpy()
    a=mid-start;b=end-mid
    length_a=np.linalg.norm(a);length_b=np.linalg.norm(b)
    aim=target.detach().cpu().numpy()-start
    distance=np.linalg.norm(aim)
    direction=aim/distance if distance>=1e-6 else a/length_a
    bend=a-np.dot(a,direction)*direction
    if np.linalg.norm(bend)<1e-6:
        axis=np.eye(3)[np.argmin(np.abs(direction))]
        bend=axis-np.dot(axis,direction)*direction
    bend/=np.linalg.norm(bend)
    reach=np.clip(distance,abs(length_a-length_b)+1e-6,length_a+length_b-1e-6)
    along=(reach**2+length_a**2-length_b**2)/(2*reach)
    first=direction*along+bend*np.sqrt(max(0,length_a**2-along**2))
    second=direction*reach-first
    for joint,old,new in ((upper,a,first),(lower,b,second)):
        swing=Rotation.align_vectors(new,old)[0].as_matrix()
        rotations[:,joint]=rotations.new_tensor(swing) @ rotations[:,joint]


def set_object_effector(skeleton,pose,positions,rotations,origin=None,*,postprocess=False,root_2d=None):
    """Place the native wrist/ankle goal and its secondary points as a rigid group."""
    goal=pose['object_goal']
    joint=''.join(word.title() for word in pose['kind'].split('_'))
    rot_names,pos_names=skeleton.expand_joint_names([joint])
    pivot=skeleton.bone_index[rot_names[0]]
    indices=[skeleton.bone_index[name] for name in pos_names]
    target=positions.new_tensor(goal['position'])
    if origin is not None:target=target-positions.new_tensor(origin)
    rotation=rotations.new_tensor(goal['rotation'])
    delta=rotation @ rotations[:,pivot].transpose(-1,-2)
    offsets=positions[:,indices]-positions[:,pivot:pivot+1]
    if postprocess:
        seed_target=target.clone()
        if root_2d is not None:
            root_delta=positions.new_tensor(root_2d)-positions[0,skeleton.root_idx,[0,2]]
            seed_target[[0,2]]-=root_delta
        seed_effector_rotations(skeleton,positions,rotations,pivot,seed_target)
    positions[:,indices]=(delta[:,None] @ offsets.unsqueeze(-1)).squeeze(-1)+target
    rotations[:,pivot]=rotation


def path_runs(data,rate=30):
    """Only constrained samples; the prefix before a delayed route stays free."""
    start=data['blocks'][0]['start']
    roots=object_root_points(data)
    runs=[]
    for block in data['blocks']:
        path=block.get('root_path')
        if not path:continue
        at=round((block['start']-start)*rate/data['fps'])+path.get('start_index',0)
        points=[roots.get(at+i,point) for i,point in enumerate(path['points'])] if roots else path['points']
        runs.append((at,points,block['uid']))
    return runs


def motionbricks_segments(data):
    """Plan transitions through every keyed pose, sharing each interior endpoint once."""
    start=data['blocks'][0]['start'];end=data['blocks'][-1]['end']
    poses=sorted(data['poses'],key=lambda p:p['frame'])
    indices=[model_frame_index(p['frame'],start,end,data['fps']) for p in poses]
    context=data.get('next_motion_context')
    if context:
        poses.append(dict(context['poses'][0],frame=end,kind='FULL',target_poses=context['poses']))
        indices.append(round((end-start)*30/data['fps']))
    segments=[]
    for i,(first,last) in enumerate(zip(poses,poses[1:])):
        samples=indices[i+1]-indices[i]+1
        if samples<2 or (last['frame']!=end and (last['frame']-first['frame'])*30/data['fps']<1-1e-7):
            raise ValueError(f"MotionBricks: pose keys at frames {first['frame']} and {last['frame']} are too close. "
                             f"Space them at least {math.ceil(data['fps']/30-1e-7)} scene frames apart (30 FPS model sampling).")
        # First segment includes the sequence start; later ones share its preceding endpoint.
        segments.append(dict(first=first,last=last,samples=samples,drop=0 if i==0 else 1))
    return segments
