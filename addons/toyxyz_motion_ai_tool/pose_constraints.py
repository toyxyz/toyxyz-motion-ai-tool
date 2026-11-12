"""Constraint annotations on native authoring Action slots, without extra keys."""
from . import rig_store
import json
import time
import bpy
from bpy.app.handlers import persistent
from . import rig

KEY='toyxyz_pose_constraint_types'
ITEMS=[('FULL','Full Body','Constrain the full body pose'),('LEFT_HAND','Left Hand','Constrain the left hand position and orientation'),
       ('RIGHT_HAND','Right Hand','Constrain the right hand position and orientation'),('LEFT_FOOT','Left Foot','Constrain the left foot position and orientation'),
       ('RIGHT_FOOT','Right Foot','Constrain the right foot position and orientation'),('ROOT','Root Position (2D)','Constrain the root ground-plane position')]
LABELS=dict(FULL='FB',LEFT_HAND='LH',RIGHT_HAND='RH',LEFT_FOOT='LF',RIGHT_FOOT='RF',ROOT='R2')
FLAGS=[(*item,1<<index) for index,item in enumerate(ITEMS)]
HEADING='ROOT_HEADING'
HEIGHT='ROOT_HEIGHT'
HEADING_HEIGHT='ROOT_HEADING_HEIGHT'
ROOT_OPTIONS={'ROOT':(False,False),HEADING:(True,False),HEIGHT:(False,True),HEADING_HEIGHT:(True,True)}
_states={}
_manual={}


def normalize(value):
    """Canonical token keeps legacy single-type Action metadata compatible."""
    values=set(value.split('+') if isinstance(value,str) else value)
    if not values<=set(LABELS)|ROOT_OPTIONS.keys():raise ValueError('Unknown pose constraint type.')
    if not values or 'FULL' in values:return 'FULL'
    roots=values&ROOT_OPTIONS.keys()
    heading=any(ROOT_OPTIONS[value][0] for value in roots);height=any(ROOT_OPTIONS[value][1] for value in roots)
    token=next(value for value,options in ROOT_OPTIONS.items() if options==(heading,height))
    if roots:values.add('ROOT')
    return '+'.join(token if item[0]=='ROOT' else item[0] for item in ITEMS if item[0] in values)


def base_kinds(value):return tuple('ROOT' if item in ROOT_OPTIONS else item for item in normalize(value).split('+'))


def mask(value):return sum(item[3] for item in FLAGS if item[0] in base_kinds(value))


def with_options(value,heading=None,height=None):
    values=set(normalize(value).split('+'));roots=values&ROOT_OPTIONS.keys()
    if roots:
        old_heading,old_height=ROOT_OPTIONS[next(iter(roots))]
        options=(old_heading if heading is None else bool(heading),old_height if height is None else bool(height))
        values-=roots;values.add(next(item for item,flags in ROOT_OPTIONS.items() if flags==options))
    return normalize(values)


def with_heading(value,enabled):return with_options(value,heading=enabled)


def with_height(value,enabled):return with_options(value,height=enabled)


def choose_mask(value,previous):
    # Selecting Full Body clears partial goals; selecting a partial goal clears FB.
    return 1 if value&1 and not previous&1 else (value&62 or 1)


def from_mask(value):return normalize([item[0] for item in FLAGS if value&item[3]])


def clear():_states.clear();_manual.clear()


def load(action):
    try:
        value=json.loads(action.get(KEY,'{}'))
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}


def sync(obj,force=False):
    from . import keyframes
    if obj is None:return {}
    action,slot=rig.pose_action(obj)
    if action is None:return {}
    slot_id=str(slot.handle if slot else 0);ident=(action.as_pointer(),slot_id);raw=action.get(KEY,'{}');now=time.monotonic()
    if ident in _manual:return _manual[ident]['values']
    old=_states.get(ident)
    if old and old['raw']==raw and not force and now-old['time']<.15:return old['values']
    records=load(action).get(slot_id,{})
    if not isinstance(records,dict):records={}
    values={}
    for frame,kind in records.items():
        try:
            at=round(float(frame),5)
            kind=normalize(kind)
            if kind!='FULL':values[at]=kind
        except (TypeError,ValueError):continue
    points={};anchors={};counts={};selections={};times={}
    for fc in keyframes.curves(obj,model_only=True):
        curve=fc.as_pointer();counts[curve]=len(fc.keyframe_points);selections[curve]=[];times[curve]=set()
        for point in fc.keyframe_points:
            at=round(float(point.co.x),5);pointer=(fc.as_pointer(),point.as_pointer())
            points[pointer]=at;anchors.setdefault(at,set()).add(pointer)
            times[curve].add(at)
            if point.select_control_point:selections[curve].append(at)
    actual=set(anchors)
    if old and old['raw']==raw:
        # Pointer identities survive ordinary native key moves. Reallocated
        # arrays fall back to frame matching; a split copies the annotation to
        # moved keys while a merge keeps an existing destination annotation.
        previous=old['values'];result={frame:kind for frame,kind in previous.items() if frame in actual}
        shifts={}
        for curve,selected in selections.items():
            before=sorted(old.get('selections',{}).get(curve,()));after=sorted(selected)
            old_times=old.get('times',{}).get(curve,set());new_times=times[curve]
            if counts.get(curve)!=old.get('counts',{}).get(curve) or old_times==new_times:continue
            if before and len(before)==len(after):
                deltas=[round(b-a,5) for a,b in zip(before,after)]
                if deltas[0] and len(set(deltas))==1 and (old_times-set(before))|set(after)==new_times:
                    shifts.update({(curve,frame):round(frame+deltas[0],5) for frame in before})
                    continue
            # A quick native click+drag can finish between timer samples. Infer
            # its unique translation from the selected destination and frame sets.
            if after:
                candidates=[]
                for frame in old_times:
                    delta=round(after[0]-frame,5)
                    source={round(at-delta,5) for at in after}
                    if delta and source<=old_times and (old_times-source)|set(after)==new_times:
                        candidates.append((delta,source))
                if len(candidates)==1:
                    delta,source=candidates[0];shifts.update({(curve,frame):round(frame+delta,5) for frame in source})
        for frame,kind in previous.items():
            destinations=set()
            for pointer in old['anchors'].get(frame,()):
                if counts.get(pointer[0])!=old.get('counts',{}).get(pointer[0]):continue
                if (pointer[0],frame) in shifts:destinations.add(shifts[pointer[0],frame])
                elif pointer in points:destinations.add(points[pointer])
            for destination in destinations:result.setdefault(destination,kind)
        values=result
    else:values={frame:kind for frame,kind in values.items() if frame in actual}
    _states[ident]=dict(action=action,slot=slot_id,raw=raw,values=values,anchors=anchors,counts=counts,selections=selections,times=times,time=now)
    return values


def kind(obj,frame):return sync(obj).get(round(float(frame),5),'FULL')


def kinds(obj,frame):return base_kinds(kind(obj,frame))


def uses_heading(obj,frame):return any(ROOT_OPTIONS.get(value,(False,False))[0] for value in kind(obj,frame).split('+'))


def uses_height(obj,frame):return any(ROOT_OPTIONS.get(value,(False,False))[1] for value in kind(obj,frame).split('+'))


def label(obj,frame):
    from . import keyframes
    if frame not in keyframes.frames(obj,model_only=True):return ''
    labels={HEADING:'R2H',HEIGHT:'R3',HEADING_HEIGHT:'R3H',**LABELS}
    return '+'.join(labels[value] for value in kind(obj,frame).split('+'))


def signature(obj,start,end):
    from . import keyframes
    return [[frame,kind(obj,frame)] for frame in keyframes.frames(obj,model_only=True) if start<=frame<end]


def flush():
    for ident,state in list(_states.items()):
        if ident in _manual:continue
        try:
            action=state['action'];current=load(action);slot=state['slot']
            values={format(frame,'.5f').rstrip('0').rstrip('.'):kind for frame,kind in state['values'].items()}
            if current.get(slot,{})==values:continue
            if values:current[slot]=values
            else:current.pop(slot,None)
            if current:action[KEY]=json.dumps(current,sort_keys=True,separators=(',',':'))
            elif KEY in action:del action[KEY]
            for other in _states.values():
                if other['action']==action:other['raw']=action.get(KEY,'{}')
        except ReferenceError:_states.pop(ident,None)


def begin_manual(obj):
    """Keep modal key previews separate from the persisted Action annotations."""
    values=dict(sync(obj,force=True));flush();action,slot=rig.pose_action(obj)
    ident=(action.as_pointer(),str(slot.handle if slot else 0))
    if ident in _manual:raise ValueError('Finish the current pose-key edit first.')
    _manual[ident]=dict(action=action,original=values,values=dict(values))
    return ident


def preview_manual(ident,frames,delta=0,delete=False,positions=None):
    state=_manual[ident];values={at:kind for at,kind in state['original'].items() if at not in frames}
    if not delete:
        values.update({positions.get(at,round(at+delta,5)) if positions is not None else round(at+delta,5):kind
                       for at,kind in state['original'].items() if at in frames})
    state['values']=values


def end_manual(ident,commit):
    state=_manual.pop(ident,None)
    if state is None:return
    if commit:
        action=state['action'];data=load(action)
        values={format(at,'.5f').rstrip('0').rstrip('.'):kind for at,kind in state['values'].items()}
        if values:data[ident[1]]=values
        else:data.pop(ident[1],None)
        if data:action[KEY]=json.dumps(data,sort_keys=True,separators=(',',':'))
        elif KEY in action:del action[KEY]
    _states.pop(ident,None)


def set_kind(obj,frame,value):
    from . import keyframes
    frame=round(float(frame),5)
    value=normalize(value)
    if frame not in keyframes.frames(obj,force=True,model_only=True):raise ValueError('This frame has no body pose key.')
    values=sync(obj,force=True)
    if value=='FULL':values.pop(frame,None)
    else:values[frame]=value
    flush();keyframes.clear()


def current(scene,obj):
    from . import keyframes
    at=round(float(scene.frame_current_final),5)
    return at if at in keyframes.frames(obj,model_only=True) else None


def ui_get(settings):
    frame=current(settings.id_data,settings.rig)
    value=kinds(settings.rig,frame)[0] if frame is not None else 'FULL'
    return next(i for i,item in enumerate(ITEMS) if item[0]==value)


def ui_set(settings,index):
    frame=current(settings.id_data,settings.rig)
    if frame is not None:set_kind(settings.rig,frame,ITEMS[index][0])


def ui_flags_get(settings):
    frame=current(settings.id_data,settings.rig)
    return mask(kind(settings.rig,frame)) if frame is not None else 1


def ui_flags_set(settings,value):
    frame=current(settings.id_data,settings.rig)
    if frame is not None:
        selected=from_mask(choose_mask(value,ui_flags_get(settings)))
        set_kind(settings.rig,frame,with_options(selected,uses_heading(settings.rig,frame),uses_height(settings.rig,frame)))


def ui_heading_get(settings):
    frame=current(settings.id_data,settings.rig)
    return frame is not None and uses_heading(settings.rig,frame)


def ui_heading_set(settings,value):
    frame=current(settings.id_data,settings.rig)
    if frame is not None:set_kind(settings.rig,frame,with_heading(kind(settings.rig,frame),value))


def ui_height_get(settings):
    frame=current(settings.id_data,settings.rig)
    return frame is not None and uses_height(settings.rig,frame)


def ui_height_set(settings,value):
    frame=current(settings.id_data,settings.rig)
    if frame is not None:set_kind(settings.rig,frame,with_height(kind(settings.rig,frame),value))


def dialog_get(operator):return operator.get('constraint_mask',1)


def dialog_set(operator,value):operator['constraint_mask']=choose_mask(value,dialog_get(operator))


def draw_options(layout,data,prop):
    column=layout.column(align=True)
    for value,name,_ in ITEMS:column.prop_enum(data,prop,value,text=LABELS[value]+' · '+name)
    if 'ROOT' in getattr(data,prop):
        column.prop(data,'root_heading');column.prop(data,'root_height')
        if data.root_height:column.label(text='Height is a soft model goal.')


@persistent
def save_pre(_):
    for scene in bpy.data.scenes:
        if hasattr(scene,'toyxyz_motion_ai_tool'):sync(rig_store.settings(scene).rig,force=True)
    flush()


def register():
    if save_pre not in bpy.app.handlers.save_pre:bpy.app.handlers.save_pre.append(save_pre)


def unregister():
    if save_pre in bpy.app.handlers.save_pre:bpy.app.handlers.save_pre.remove(save_pre)
    clear()
