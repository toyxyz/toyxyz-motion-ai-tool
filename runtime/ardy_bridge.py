"""Bounded-window ARDY generation for finite Blender prompt blocks."""
import math


def generate(data,progress,state):
    import numpy as np
    import torch
    from ardy.model import load_model
    from ardy.constraints import FullBodyConstraintSet,Root2DConstraintSet,TYPE_TO_CLASS
    from ardy.postprocess import post_process_motion
    from ardy.motion_rep.tools import compute_heading_angle
    from motion_bridge_protocol import model_frame_index,next_pose_targets,path_runs,set_object_effector,object_effector_samples,object_root_points
    from root_height_constraint import with_height,height_errors
    from shared_encoder_client import SharedEncoderClient
    progress(0,'Loading ARDY model',force=True)
    client=SharedEncoderClient('ardy',precision=data['precision'])
    if state._ardy_cache is None:
        state._ardy_cache=load_model('soma',device='cuda',text_encoder=client);state._loads+=1
    model=state._ardy_cache;model.text_encoder=client
    start=data['blocks'][0]['start'];fps=data['fps'];rate=model.motion_rep.fps
    lengths=[round((b['end']-start)*rate/fps)-round((b['start']-start)*rate/fps) for b in data['blocks']]
    output_frames=sum(lengths);horizon=model.gen_horizon_len;patch=model.num_frames_per_token
    capacity=int(10*rate);max_history=((capacity-horizon)//patch)*patch
    following=next_pose_targets(data,output_frames)
    lengths[-1]+=len(following)
    total=sum(lengths)
    paths=[(at,np.asarray(points,dtype=np.float32),uid) for at,points,uid in path_runs(data,rate)]
    def point_at(index):
        for at,points,uid in paths:
            if at<=index<at+len(points):return points[index-at]
        return None
    def local_rotations(values):
        local=torch.tensor(values,dtype=torch.float32,device='cuda');eye=torch.eye(3,device='cuda')
        if (local.transpose(-1,-2)@local-eye).abs().max()>.002 or (torch.linalg.det(local)-1).abs().max()>.002:
            raise ValueError('Invalid ARDY pose rotation matrices.')
        return model.skeleton.from_SOMASkeleton77(local)
    poses=[];object_effectors=object_effector_samples(data);object_roots=object_root_points(data)
    targets=[(model_frame_index(pose['frame'],start,data['blocks'][-1]['end'],fps),pose) for pose in data['poses']]+following
    for index,pose in targets:
        local=local_rotations([pose['local_rotations']]);root=np.array(pose['root'],dtype=np.float32);point=point_at(index)
        goal=pose.get('object_goal')
        if goal and pose['kind']=='ROOT':root=np.asarray(goal['position'],dtype=np.float32)
        if point is not None and pose['kind'] in ('FULL','ROOT') and pose.get('source')!='previous_motion_end':root[[0,2]]=point
        rotations,positions,_=model.skeleton.fk(local,torch.tensor(root[None],device='cuda'))
        heading=None
        if pose.get('root_heading'):
            if goal:heading=positions.new_tensor([math.atan2(goal['heading'][1],goal['heading'][0])])
            else:heading=compute_heading_angle(positions[:,None],model.skeleton)[:,0]
        height=positions[:,model.skeleton.root_idx,1] if pose.get('root_height') else None
        if pose['kind'] not in ('FULL','ROOT'):
            for target in object_effectors.get(index,()):
                set_object_effector(model.skeleton,target,positions,rotations,postprocess=data.get('postprocess',True),
                                    root_2d=object_roots.get(index,point))
        inherited=index==0 and pose.get('source')=='previous_motion_end'
        poses.append((index,pose['kind'],rotations,positions,heading,height,inherited))
    kinds={'LEFT_HAND':'left-hand','RIGHT_HAND':'right-hand','LEFT_FOOT':'left-foot','RIGHT_FOOT':'right-foot'}
    def constraints(a,b,offset=0,*,moving_root=None):
        values=[]
        for index,kind,rotations,positions,heading,height,inherited in poses:
            if not a<=index<b:continue
            if inherited and moving_root is not None:
                shift=torch.zeros_like(moving_root)
                shift[[0,2]]=moving_root[[0,2]]-positions[0,0,[0,2]]
                positions=positions+shift
            # This ARDY release builds its joint/frame index pairs on CPU;
            # feature values remain on CUDA, matching its native JSON loader.
            frames=torch.tensor([index-a+offset])
            if kind=='FULL':value=FullBodyConstraintSet(model.skeleton,frames,positions,rotations)
            elif kind=='ROOT':
                if height is not None:value=with_height(Root2DConstraintSet)(model.skeleton,frames,positions[:,0,[0,2]],height,heading)
                else:value=Root2DConstraintSet(model.skeleton,frames,positions[:,0,[0,2]],global_root_heading=heading)
            else:
                point=object_roots.get(index,point_at(index));root_2d=positions.new_tensor(np.asarray([point])) if point is not None else None
                value=TYPE_TO_CLASS[kinds[kind]](model.skeleton,frames,positions,rotations,root_2d)
            values.append(value)
        for at,points,uid in paths:
            lo=max(a,at);hi=min(b,at+len(points))
            if hi>lo:
                values.append(Root2DConstraintSet(model.skeleton,torch.arange(lo-a+offset,hi-a+offset),
                    torch.tensor(points[lo-at:hi-at],device='cuda')))
        return values
    history=None;previous=data.get('previous_motion_context')
    if previous:
        recorded=previous['poses'];local=local_rotations([p['local_rotations'] for p in recorded])[None]
        roots=torch.tensor([[p['root'] for p in recorded]],dtype=torch.float32,device='cuda')
        with torch.inference_mode():history=model.motion_rep(local,roots,to_normalize=True)[:,-previous['frame_count']:]

    def continues_moving(output):
        if total<3 or not previous or previous['frame_count']<3 or not any(p[-1] for p in poses):
            return False
        if any(p[0]<3 and not p[-1] for p in poses) or any(at<3 for at,_,_ in paths):
            return False
        prior=roots[0,-3:][:,[0,2]]
        earlier,last=prior[1]-prior[0],prior[2]-prior[1]
        speed=float(last.norm())
        if speed<.003 or float((earlier-last).norm())>.5*speed:
            return False
        incoming=output['root_positions'][0,0,[0,2]]-prior[2]
        return float((incoming-last).norm())<=max(.005,.5*speed)
    initial_translation=torch.zeros((1,3),device='cuda');initial_heading=torch.zeros(1,device='cuda')
    if poses and poses[0][0]==0:
        initial_translation[:,[0,2]]=poses[0][3][:,0,[0,2]]
        initial_heading=compute_heading_angle(poses[0][3][:,None],model.skeleton)[:,0]
        for pose in data['poses']:
            if model_frame_index(pose['frame'],start,data['blocks'][-1]['end'],fps)!=0:break
            goal=pose.get('object_goal')
            if pose['kind']=='ROOT' and goal:
                initial_translation[:,[0,2]]=initial_translation.new_tensor(goal['position'][::2])
                if 'heading' in goal:initial_heading[:]=math.atan2(goal['heading'][1],goal['heading'][0])
                break
    if paths and paths[0][0]==0:
        initial_translation[:,[0,2]]=torch.tensor(paths[0][1][:1],device='cuda')
        if not poses and len(paths[0][1])>1:
            delta=paths[0][1][1]-paths[0][1][0];initial_heading[:]=math.atan2(float(delta[0]),float(delta[1]))
    torch.manual_seed(data['seed']);torch.cuda.manual_seed_all(data['seed'])
    windows=sum(math.ceil(n/horizon) for n in lengths);work=windows*data['steps'];completed=0;window=0
    original=model._generate_window;stage='ARDY'
    def progress_bar(iterable):
        nonlocal completed
        for item in iterable:
            yield item;completed+=1;progress(.97*completed/work,stage,completed,work)
    def generate_window(*args,**kwargs):
        kwargs['progress_bar']=progress_bar
        return original(*args,**kwargs)
    model._generate_window=generate_window;chunks=[];cursor=0;history_counts=[];moving_start=False
    try:
        with torch.inference_mode():
            for block_number,(block,count) in enumerate(zip(data['blocks'],lengths),1):
                text_feat,text_mask=model._encode_text([block['prompt']]);remaining=count
                while remaining:
                    window+=1;stage=f'ARDY block {block_number}/{len(lengths)}: window {window}/{windows}'
                    progress(.97*completed/work,stage,completed,work,force=True)
                    history_limit=max_history
                    if following and cursor<output_frames<=cursor+horizon:
                        # Reserve room for the real successor poses even when the history is full.
                        history_limit=min(max_history,((capacity-(total-cursor))//patch)*patch)
                    source=history[:,-history_limit:] if history is not None and history_limit else None
                    if source is not None and source.shape[1]%patch:
                        pad=patch-source.shape[1]%patch;source=torch.cat([source[:,:1].expand(-1,pad,-1),source],dim=1)
                    size=source.shape[1] if source is not None else 0;history_counts.append(size)
                    future=min(max(0,total-cursor-horizon),max(0,capacity-size-horizon))
                    visible=math.ceil((size+horizon+future)/patch)*patch
                    targets=constraints(cursor,min(total,cursor+visible-size),size)
                    observed=mask=None
                    if targets:
                        observed,mask=model.motion_rep.create_conditions_from_constraints_batched(targets,torch.tensor([visible],device='cuda'),to_normalize=True,device='cuda')
                    samples=model.autoregressive_step(num_frames=visible,num_denoising_steps=data['steps'],motion_mask=mask,observed_motion=observed,
                        cfg_weight=(data.get('text_weight',2),data.get('constraint_weight',2)),text_feat=text_feat,text_pad_mask=text_mask,
                        init_history_sequence=source,init_global_translation=initial_translation if source is None else None,
                        init_first_heading_angle=initial_heading if source is None else None)
                    take=min(horizon,remaining);new=samples[:,size:size+take]
                    chunks.append(new.cpu());history=new if history is None else torch.cat([history,new],dim=1)
                    history=history[:,-max_history:];cursor+=take;remaining-=take
            output=model.motion_rep.inverse(torch.cat(chunks,dim=1).to('cuda'),is_normalized=True)
            postprocess=data.get('postprocess',True)
            targets=[];options={}
            if postprocess:
                # Keep the inherited articulation and height. A matching predicted
                # horizontal step avoids pinning the character to the previous frame.
                moving_root=output['root_positions'][0,0] if continues_moving(output) else None
                moving_start=moving_root is not None
                targets=constraints(0,total,moving_root=moving_root)
                if moving_root is not None and not paths and all(p[1]=='FULL' for p in poses):
                    # Keep the first two velocity samples in the native contact solve.
                    # Its root margin remains unchanged for authored paths or effectors.
                    points=output['root_positions'][0,1:3][:,[0,2]]
                    targets.append(Root2DConstraintSet(model.skeleton,torch.arange(1,3),points))
                    options['root_margin']=0.
            if postprocess and (total>1 or targets):
                progress(.98,'Post-processing ARDY motion',completed,work,force=True)
                inputs=[output[key] for key in ('local_rot_mats','root_positions','foot_contacts')]
                # The native correction needs two samples. Duplicate a single pose for its solve.
                if total==1:inputs=[torch.cat((value,value),dim=1) for value in inputs]
                corrected=post_process_motion(*inputs,model.skeleton,targets,**options)
                output.update({key:value[:,:total] for key,value in corrected.items()})
            output=model.skeleton.output_to_SOMASkeleton77(output)
    finally:model._generate_window=original
    local=output['local_rot_mats'][0].cpu().numpy();root=output['root_positions'][0].cpu().numpy()
    if local.shape!=(total,77,3,3) or root.shape!=(total,3) or not np.isfinite(local).all() or not np.isfinite(root).all():
        raise RuntimeError('Invalid ARDY motion output.')
    errors=[]
    for at,points,uid in paths:
        difference=np.linalg.norm(root[at:at+len(points)][:,[0,2]]-points,axis=-1)
        errors.append(dict(uid=uid,max_hips_error_m=float(difference.max()),mean_hips_error_m=float(difference.mean())))
    return dict(local_rotations=local[:output_frames].tolist(),root_positions=root[:output_frames].tolist(),fps=rate,frame_count=output_frames,
        source='real ARDY-SOMA-RP-30FPS-Horizon60',progress_work_completed=completed,progress_work_total=work,
        autoregressive_windows=window,generation_horizon_frames=horizon,history_limit_frames=max_history,history_frames_per_window=history_counts,
        previous_motion_context_frames=previous['frame_count'] if previous else 0,moving_start=moving_start,
        root_path_errors=errors,root_height_errors=height_errors(data,root),
        encoder_instance=client.identity['instance_id'],encoder_load_count=client.identity['model_load_count'])
