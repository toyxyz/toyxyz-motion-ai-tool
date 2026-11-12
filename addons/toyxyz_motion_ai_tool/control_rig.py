"""Native FK/IK authoring above the unchanged 77-joint SOMA output skeleton."""
import json
import math
import bpy
from bpy.props import EnumProperty
from mathutils import Matrix, Quaternion, Vector, Euler
from . import rig

VERSION='toyxyz_split_control_rig_v1'
ALIGNMENT='Controls · Alignment'
FINGER_CONTROLS='Controls · Fingers'
FINGER_WIDGETS='toyxyz_finger_widgets_v1'
MASTER='CTRL_Master'
PREFIX='CTRL_'
LIMBS={}
for kind,parts in [('Arm',('Arm','ForeArm','Hand')),('Leg',('Leg','Shin','Foot'))]:
    for side in ('Left','Right'):
        key=side+kind
        LIMBS[key]=dict(bones=tuple(side+p for p in parts),target='IK_'+side+parts[-1],pole='Pole_'+key)
EFFECTORS=tuple(limb['bones'][-1] for limb in LIMBS.values())

def enabled(obj):return bool(obj and obj.get(VERSION))
def fk(name):return PREFIX+name
def mch(name):return 'MCH_IK_'+name
def aligned_fk(name):return 'MATCH_FK_'+name
def aligned_ik(key):return 'MATCH_IK_'+key

DIGIT_EFFECTORS={fk(name):rig.NAMES[parent]
                 for name,parent in zip(rig.NAMES,rig.PARENTS) if parent>=0 and rig.NAMES[parent] in EFFECTORS}

def follows_effector(name):
    parent=rig.PARENTS[rig.NAMES.index(name)]
    while parent>=0:
        if rig.NAMES[parent] in EFFECTORS:return True
        parent=rig.PARENTS[parent]
    return False

def names(obj,*,model_only=False):
    bones=rig.GENERATED_NAMES if model_only else rig.NAMES
    return [MASTER,*map(fk,bones),*[v[k] for v in LIMBS.values() for k in ('target','pole')]] if enabled(obj) else bones

def mode_path(target):return target.path_from_id()+'["ik"]'

def mode_paths(obj):
    return {mode_path(obj.pose.bones[limb['target']]) for limb in LIMBS.values()} if enabled(obj) else set()

def bags(action,slot):
    if action.is_action_layered:
        return [bag for layer in action.layers for strip in layer.strips if strip.type=='KEYFRAME'
                for bag in [strip.channelbag(slot)] if bag]
    return [action]

def action_curves(action,slot):
    return [curve for bag in bags(action,slot) for curve in bag.fcurves] if action else []

def widget(kind):
    name='MotionAI_Widget_'+kind
    old=bpy.data.objects.get(name)
    if old and old.get('toyxyz_control_widget'):return old
    vertices=[];edges=[]
    if kind.startswith('Ring'):
        for i in range(48):
            angle=i*math.tau/48
            vertices.append((math.cos(angle),math.sin(angle),0) if kind=='RingGround' else (math.cos(angle),0,math.sin(angle)))
            edges.append((i,(i+1)%48))
    elif kind=='Pole':
        for axis in range(3):
            first=len(vertices)
            for i in range(24):
                p=[0.,0.,0.];p[(axis+1)%3]=math.cos(i*math.tau/24);p[(axis+2)%3]=math.sin(i*math.tau/24)
                vertices.append(p);edges.append((first+i,first+(i+1)%24))
    else:
        vertices=[(x,y,z) for x in (-1,1) for y in ((-1,1) if kind=='BoxCentered' else (0,1)) for z in (-1,1)]
        edges=[(i,j) for i in range(8) for j in range(i+1,8) if sum(a!=b for a,b in zip(vertices[i],vertices[j]))==1]
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,edges,[])
    obj=bpy.data.objects.new(name,data);obj['toyxyz_control_widget']=True
    collection=bpy.data.collections.get('Motion AI Widgets')
    if collection is None:
        collection=bpy.data.collections.new('Motion AI Widgets');bpy.context.scene.collection.children.link(collection)
    collection.objects.link(obj);obj.hide_render=True;obj.hide_select=True;obj.hide_set(True)
    return obj

def shape(pb,kind,size,color):
    pb.custom_shape=widget(kind);pb.use_custom_shape_bone_size=False
    pb.custom_shape_scale_xyz=size
    pb.color.palette='CUSTOM';pb.color.custom.normal=color
    pb.color.custom.select=tuple(min(1,c+.2) for c in color);pb.color.custom.active=(1,1,1)

def fit_clavicle_widgets(obj):
    """Replace the stock clavicle rings with boxes along the control bones."""
    if not enabled(obj) or not obj.is_editable:return
    units=obj['toyxyz_units']
    for name in ('LeftShoulder','RightShoulder'):
        pb=obj.pose.bones.get(fk(name))
        current=pb.custom_shape if pb else None
        if not (current and current.get('toyxyz_control_widget')
                and current.name.startswith('MotionAI_Widget_RingJoint')):continue
        pb.custom_shape=widget('Box')
        pb.use_custom_shape_bone_size=False
        # The box runs from local Y=0 to Y=1, and the SOMA tail is at the upper-arm joint.
        pb.custom_shape_scale_xyz=(.031*units,pb.bone.length,.028*units)
        pb.custom_shape_translation=(0.,0.,0.)
        pb.custom_shape_rotation_euler=(0.,0.,0.)


def fit_finger_widgets(obj):
    """Fit local FK boxes to the existing finger controls without altering their keys."""
    if not enabled(obj) or obj.get(FINGER_WIDGETS) or not obj.is_editable or not obj.data.is_editable or obj.mode=='EDIT':return
    collection=obj.data.collections.get(FINGER_CONTROLS)
    if collection is None:return
    units=obj['toyxyz_units']
    for name in rig.FINGER_NAMES:
        pb=obj.pose.bones.get(fk(name))
        if pb is None:continue
        current=pb.custom_shape
        if current and not (current.get('toyxyz_control_widget') and current.name.startswith('MotionAI_Widget_RingJoint')):
            continue
        length=pb.bone.length
        width=min(.008*units,max(.0028*units,length*.19))
        color=(.15,.65,1.) if name.startswith('Left') else (1.,.35,.12)
        shape(pb,'Box',(width,length*.74,width),color)
        pb.custom_shape_translation=(0.,length*.13,0.)
        pb.custom_shape_rotation_euler=(0.,0.,0.)
    collection.is_visible=True
    obj[FINGER_WIDGETS]=True


def drive(owner,path,obj,target,expression):
    fc=owner.driver_add(path);driver=fc.driver;driver.type='SCRIPTED';driver.expression=expression
    variable=driver.variables.new();variable.name='ik';variable.type='SINGLE_PROP'
    variable.targets[0].id=obj;variable.targets[0].data_path=obj.pose.bones[target].path_from_id()+'["ik"]'

def show_in_mode(pb,obj,target,ik,sizes=None):
    sizes=tuple(sizes if sizes is not None else pb.custom_shape_scale_xyz)
    pb['_toyxyz_widget_size']=sizes
    for axis,size in enumerate(sizes):
        fc=pb.driver_add('custom_shape_scale_xyz',axis);driver=fc.driver;driver.type='SCRIPTED'
        driver.expression=f'{size!r}*'+('ik' if ik else '(1-ik)')
        for variable in list(driver.variables):driver.variables.remove(variable)
        variable=driver.variables.new();variable.name='ik';variable.type='SINGLE_PROP'
        variable.targets[0].id=obj;variable.targets[0].data_path=obj.pose.bones[target].path_from_id()+'["ik"]'

def fit_head_widget(obj,skin=None):
    """Fit a display-only box to neutral SOMA head skin, in head-bone space."""
    pb=obj.pose.bones[fk('Head')];rest=obj.data.bones['Head'].matrix_local
    units=obj['toyxyz_units']
    try:
        import numpy as np
        if skin is None:
            from . import preview_mesh
            skin=preview_mesh.load_asset(bpy.context,obj)
        head_indices=[rig.NAMES.index(n) for n in ('Head','HeadEnd','Jaw','LeftEye','RightEye')]
        keep=np.isin(skin['joints'],head_indices)
        mass=np.bincount(skin['vertex'][keep],weights=skin['weights'][keep],minlength=len(skin['vertices']))
        points=skin['vertices'][mass>=.5]
        if len(points)<20:raise ValueError('Head skin region is unavailable.')
        low=Vector(points.min(axis=0));high=Vector(points.max(axis=0))
    except (OSError,ValueError,ImportError):
        center=rest.translation+Vector((0,0,.07*units))
        half=Vector((.115,.13,.16))*units;low=center-half;high=center+half
    center=(low+high)*.5;half=(high-low)*.5+Vector((.015,.015,.015))*units
    shape(pb,'BoxCentered',tuple(half),tuple(pb.color.custom.normal))
    pb.custom_shape_translation=rest.inverted()@center
    pb.custom_shape_rotation_euler=rest.to_quaternion().inverted().to_euler('XYZ')

def fit_hand_widgets(obj,skin=None):
    """Neutral hand boxes align with the actor axes in front and top views."""
    units=obj['toyxyz_units'];frame=Matrix.Identity(3)
    for side in ('Left','Right'):
        origin=obj.data.bones[side+'Hand'].head_local
        landmarks=[obj.data.bones[n].head_local[:] for n in rig.NAMES if n.startswith(side+'Hand')]
        try:
            import numpy as np
            if skin is None:raise ValueError('Palm skin is unavailable.')
            hand_indices=[i for i,n in enumerate(rig.NAMES) if n.startswith(side+'Hand')]
            keep=np.isin(skin['joints'],hand_indices)
            mass=np.bincount(skin['vertex'][keep],weights=skin['weights'][keep],minlength=len(skin['vertices']))
            points=skin['vertices'][mass>=.5]
            if len(points)<12:raise ValueError('Palm skin region is unavailable.')
            # Include fingertips and thumb as well as the palm, with axis-aligned
            # bounds. This is display geometry only, not a change to wrist axes.
            points=np.vstack((points,np.asarray(landmarks),np.asarray(origin)[None]))
            local=(points-np.asarray(origin))@np.asarray(frame)
            low=Vector(local.min(axis=0));high=Vector(local.max(axis=0))
        except (ValueError,ImportError):
            points=[Vector(v)-origin for v in landmarks]
            low=Vector(tuple(min(v[i] for v in points) for i in range(3)))
            high=Vector(tuple(max(v[i] for v in points) for i in range(3)))
        center=origin+frame@((low+high)*.5)
        half=(high-low)*.5+Vector((.008,.008,.008))*units
        for name,ik in ((fk(side+'Hand'),False),(LIMBS[side+'Arm']['target'],True)):
            pb=obj.pose.bones[name];rest=obj.data.bones[name].matrix_local
            shape(pb,'BoxCentered',tuple(half),tuple(pb.color.custom.normal))
            pb.custom_shape_translation=rest.inverted()@center
            pb.custom_shape_rotation_euler=(rest.to_3x3().inverted()@frame).to_euler('XYZ')
            show_in_mode(pb,obj,LIMBS[side+'Arm']['target'],ik,sizes=tuple(half))

def fit_foot_widgets(obj,skin=None):
    """Foot and toe boxes follow the sole/forward axes, not bone rest roll."""
    units=obj['toyxyz_units'];up=Vector((0,0,1))
    for side in ('Left','Right'):
        for part in ('Foot','ToeBase'):
            origin=obj.data.bones[side+part].head_local
            end=obj.data.bones[side+('ToeBase' if part=='Foot' else 'ToeEnd')].head_local
            along=end-origin;along.z=0
            if along.length<1e-8:along=Vector((0,-1,0))
            along.normalize();across=along.cross(up).normalized()
            frame=Matrix((across,along,up)).transposed()
            try:
                import numpy as np
                if skin is None:raise ValueError('Foot skin is unavailable.')
                joints=[rig.NAMES.index(side+part)]
                if part=='ToeBase':joints.append(rig.NAMES.index(side+'ToeEnd'))
                keep=np.isin(skin['joints'],joints)
                mass=np.bincount(skin['vertex'][keep],weights=skin['weights'][keep],minlength=len(skin['vertices']))
                points=skin['vertices'][mass>=.5]
                if len(points)<12:raise ValueError('Foot skin region is unavailable.')
                points=np.vstack((points,np.asarray(origin)[None],np.asarray(end)[None]))
                local=(points-np.asarray(origin))@np.asarray(frame)
                low=Vector(local.min(axis=0));high=Vector(local.max(axis=0))
            except (ValueError,ImportError):
                low=Vector((-.055,-.07,-.065) if part=='Foot' else (-.055,-.02,-.015))*units
                high=Vector((.055,.16,.06) if part=='Foot' else (.055,.10,.045))*units
            center=origin+frame@((low+high)*.5)
            half=(high-low)*.5+Vector((.008,.008,.008))*units
            controls=((fk(side+part),False),(LIMBS[side+'Leg']['target'],True)) if part=='Foot' else ((fk(side+part),None),)
            for name,ik in controls:
                pb=obj.pose.bones[name];rest=obj.data.bones[name].matrix_local
                shape(pb,'BoxCentered',tuple(half),tuple(pb.color.custom.normal))
                pb.custom_shape_translation=rest.inverted()@center
                pb.custom_shape_rotation_euler=(rest.to_3x3().inverted()@frame).to_euler('XYZ')
                if ik is not None:show_in_mode(pb,obj,LIMBS[side+'Leg']['target'],ik,sizes=tuple(half))

def fit_widgets(context,obj):
    try:
        from . import preview_mesh
        skin=preview_mesh.load_asset(context,obj)
    except (OSError,ValueError,ImportError):skin=None
    fit_hand_widgets(obj,skin)
    fit_foot_widgets(obj,skin)
    for name in rig.NAMES:
        if not (rig.auxiliary(name) or name=='Jaw'):continue
        pb=obj.pose.bones[fk(name)];pb.custom_shape=None;pb.hide=True;pb.bone.hide=True;pb.select=False
        if obj.data.bones.active==pb.bone:obj.data.bones.active=None
    fit_head_widget(obj,skin)

def setup_alignment(obj):
    """These display bones only read the final pose, so neither solver can feed back."""
    for key,limb in LIMBS.items():
        target=obj.pose.bones[limb['target']]
        end=limb['bones'][-1]
        # The FK chain is independent of the IK solver, so the dormant IK
        # target can evaluate at the FK endpoint without closing a cycle.
        follow=target.constraints.new('COPY_TRANSFORMS')
        follow.name='Motion AI Follow FK'
        follow.target=obj;follow.subtarget=fk(end)
        follow.target_space='POSE';follow.owner_space='POSE'
        drive(follow,'influence',obj,target.name,'1-ik')
        items=[(aligned_fk(name),name,obj.pose.bones[fk(name)],True) for name in limb['bones']]
        items.append((aligned_ik(key),end,target,False))
        for name,source,style,show_in_ik in items:
            pb=obj.pose.bones[name]
            con=pb.constraints.new('COPY_TRANSFORMS')
            con.name='Motion AI Matched Pose'
            con.target=obj;con.subtarget=source
            con.target_space='POSE';con.owner_space='POSE'
            pb.bone.hide_select=True
            pb.custom_shape=style.custom_shape
            pb.use_custom_shape_bone_size=False
            pb.custom_shape_translation=style.custom_shape_translation
            pb.custom_shape_rotation_euler=style.custom_shape_rotation_euler
            pb.color.palette='CUSTOM'
            pb.color.custom.normal=(.48,.48,.48)
            show_in_mode(pb,obj,target.name,show_in_ik,sizes=style['_toyxyz_widget_size'])

def rest_pole_point(matrices,limb,units,rest):
    upper,mid,end=limb['bones']
    a,b,c=(matrices[name].translation for name in (upper,mid,end))
    # SOMA faces model +Z. Convert the anatomical bend direction into the
    # upper bone's rest frame, then carry it with the bone's posed rotation.
    forward=rig.C @ Vector((0,0,-1 if upper.endswith('Arm') else 1))
    reference=rest.to_quaternion().inverted()@forward
    reference.y=0.
    rotation=matrices[upper].to_quaternion()
    direction=rotation@reference.normalized()
    upper_axis=rotation@Vector((0,1,0))
    axis=(c-a).normalized() if (c-a).length>1e-8 else upper_axis
    # Swing onto the shoulder-to-wrist or hip-to-ankle axis without adding
    # twist. The pole stays on the same side as the limb approaches extension.
    direction=upper_axis.rotation_difference(axis)@direction
    lower_axis=matrices[mid].to_quaternion()@Vector((0,1,0))
    normal=upper_axis.cross(lower_axis)
    flexion=math.atan2(normal.length,upper_axis.dot(lower_axis))
    if flexion>.024:
        # A clearly flexed joint can carry off-axis motion in its rotation.
        # Read that orientation only beyond the near-straight range.
        oriented=axis.cross(normal).normalized()
        weight=min(1.,(flexion-.024)/.012)
        weight=weight*weight*(3.-2.*weight)
        angle=math.atan2(axis.dot(direction.cross(oriented)),direction.dot(oriented))
        direction=Quaternion(axis,weight*angle)@direction
    return a+axis*((b-a).dot(axis))+direction*.4*units


def snap_pole_point(matrices,limb,units,rest):
    """Match an existing pose exactly when the user switches controls."""
    upper,mid,end=limb['bones']
    a,b,c=(matrices[name].translation for name in (upper,mid,end))
    axis=(c-a).normalized()
    offset=b-a-axis*((b-a).dot(axis))
    if offset.length/units<.0001:
        return rest_pole_point(matrices,limb,units,rest)
    return b+offset.normalized()*.4*units

def update(context,obj):
    obj.update_tag(refresh={'OBJECT','DATA'});context.view_layer.update()

def calibrate(context,obj,key):
    limb=LIMBS[key];mid=obj.pose.bones[mch(limb['bones'][1])]
    con=mid.constraints['Motion AI IK'];target=obj.pose.bones[limb['target']]
    pole=obj.pose.bones[limb['pole']]
    fk_mid=obj.pose.bones[fk(limb['bones'][1])]
    saved=(fk_mid.matrix_basis.copy(),target.matrix_basis.copy(),pole.matrix_basis.copy())
    # A straight rest chain cannot determine its pole angle. Calibrate against
    # a temporary bent FK pose, then restore every channel before migration.
    fk_mid.rotation_quaternion=Quaternion((0,0,1),.6);update(context,obj)
    matrices={n:obj.pose.bones[fk(n)].matrix.copy() for n in rig.NAMES}
    target.matrix=matrices[limb['bones'][2]];update(context,obj)
    rest=obj.data.bones[limb['bones'][0]].matrix_local
    matrix=pole.matrix.copy();matrix.translation=snap_pole_point(matrices,limb,obj['toyxyz_units'],rest);pole.matrix=matrix
    wanted=matrices[limb['bones'][1]].translation.copy()
    target['ik']=1.;update(context,obj)
    def error(angle):
        con.pole_angle=angle;update(context,obj)
        actual=obj.evaluated_get(context.evaluated_depsgraph_get()).pose.bones[mid.name].head
        return (actual-wanted).length_squared
    count=24;step=math.tau/count
    best=min(((-math.pi+i*step) for i in range(count)),key=error)
    low=max(-math.pi,best-step);high=min(math.pi,best+step)
    for _ in range(22):
        a=low+(high-low)/3;b=high-(high-low)/3
        if error(a)<error(b):high=b
        else:low=a
    con.pole_angle=(low+high)/2;target['ik']=0.
    fk_mid.matrix_basis,target.matrix_basis,pole.matrix_basis=saved
    update(context,obj)

def remap_action(obj,action,slot,cache):
    if not action or not slot:return action,slot
    identity=(action.as_pointer(),slot.handle)
    if identity in cache:return cache[identity]
    paths={f'pose.bones["{n}"]':f'pose.bones["{fk(n)}"]' for n in rig.NAMES}
    if not any(any(fc.data_path.startswith(path+'.') for path in paths) for fc in action_curves(action,slot)):
        return action,slot
    work=action.copy();work.name=action.name+' · Controls';work.use_fake_user=False
    target_slot=rig.action_slot(work,slot.handle)
    for fc in action_curves(work,target_slot):
        for path,replacement in paths.items():
            if fc.data_path.startswith(path+'.'):
                fc.data_path=replacement+fc.data_path[len(path):];break
    if work.get('toyxyz_rotation_modes'):
        modes=json.loads(work['toyxyz_rotation_modes']);work['toyxyz_rotation_modes']=json.dumps({fk(n) if n in rig.NAMES else n:v for n,v in modes.items()})
    action.use_fake_user=True;work['toyxyz_controls_source_action']=action.name
    cache[identity]=(work,target_slot)
    return work,target_slot

def migrate_actions(obj):
    from . import nla_motion,control_layers
    ad=obj.animation_data
    if not ad:return
    cache={}
    action,slot=rig.pose_action(obj)
    if action:
        action,slot=remap_action(obj,action,slot,cache);rig.assign_action(obj,action,slot)
    for track in ad.nla_tracks:
        for strip in track.strips:
            if not strip.action or not strip.action_slot:continue
            action,slot=remap_action(obj,strip.action,strip.action_slot,cache)
            strip.action=action;strip.action_slot=slot
            if nla_motion.owned(obj,strip) and not strip.action.get(nla_motion.REQUEST):augment_action(obj,action,slot)
    for property in (rig.POSE_BASE,control_layers.DEFAULTS):
        if property in obj:
            base=json.loads(obj[property]);obj[property]=json.dumps({fk(n) if n in rig.NAMES else n:v for n,v in base.items()})

def setup(context,obj):
    from . import block_links
    with block_links.transaction(context.scene):
        return _setup(context,obj)


def parent_digit_controls(bones):
    # The existing read-only guides provide solved wrist/ankle pose space.
    # Keep those guides under the FK controls so Blender sees the digits as
    # descendants of the master when it filters a multi-bone transform.
    for name in EFFECTORS:
        bones[aligned_fk(name)].parent=bones[fk(name)]
    for name,effector in DIGIT_EFFECTORS.items():
        bones[name].parent=bones[aligned_fk(effector)]


def upgrade_digit_parents(context,obj):
    if obj.get(VERSION)!=1 or obj.mode not in {'OBJECT','POSE'}:return
    if not obj.is_editable or not obj.data.is_editable or obj.data.users!=1:return
    if obj.name not in context.view_layer.objects or not obj.visible_get(view_layer=context.view_layer):return
    if any(window.modal_operators for window in context.window_manager.windows):return
    from . import block_links,rig_store
    if rig_store.deletion_busy(obj) or (obj.animation_data and obj.animation_data.use_tweak_mode):return
    active=context.view_layer.objects.active
    if active and active!=obj and active.mode!='OBJECT':return
    bones=obj.data.bones
    if any(not bones.get(name) or bones[name].parent not in (bones.get(effector),bones.get(aligned_fk(effector)))
           for name,effector in DIGIT_EFFECTORS.items()):return
    if any(not bones.get(fk(name)) or not bones.get(aligned_fk(name))
           or bones[aligned_fk(name)].parent not in (None,bones[fk(name)]) for name in EFFECTORS):return
    selected=list(context.selected_objects);mode=obj.mode
    selected_bones={bone.name for bone in obj.pose.bones if bone.select}
    active_bone=bones.active.name if bones.active else None
    with block_links.transaction(context.scene):
        if mode=='POSE':bpy.ops.object.mode_set(mode='OBJECT')
        try:
            for other in context.selected_objects:other.select_set(False)
            obj.select_set(True);context.view_layer.objects.active=obj
            if bpy.ops.object.mode_set(mode='EDIT')!={'FINISHED'}:return
            parent_digit_controls(obj.data.edit_bones)
            obj[VERSION]=2
        finally:
            if obj.mode=='EDIT':bpy.ops.object.mode_set(mode='OBJECT')
            obj.select_set(False)
            for other in selected:other.select_set(True)
            context.view_layer.objects.active=active
            if mode=='POSE':bpy.ops.object.mode_set(mode='POSE')
            for bone in obj.pose.bones:bone.select=bone.name in selected_bones
            obj.data.bones.active=obj.data.bones.get(active_bone) if active_bone else None
    update(context,obj)


def _setup(context,obj):
    if enabled(obj):return obj
    rig.validate_rig(obj)
    from . import rig_store,keyframes,nla_motion
    if rig_store.deletion_busy(obj):raise ValueError('Finish or cancel generation for this actor before adding controls.')
    if obj.data.users>1:raise ValueError('Make the armature data single-user before adding controls.')
    reserved=[MASTER,*map(fk,rig.NAMES),*[v[k] for v in LIMBS.values() for k in ('target','pole')],
              *[mch(n) for limb in LIMBS.values() for n in limb['bones']],
              *[aligned_fk(n) for limb in LIMBS.values() for n in limb['bones']],*map(aligned_ik,LIMBS)]
    if any(obj.data.bones.get(name) for name in reserved):raise ValueError('Reserved control bone names already exist on this armature.')
    if rig.POSE_BASE in obj:json.loads(obj[rig.POSE_BASE])
    if obj.animation_data and obj.animation_data.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before adding controls.')
    if any(pb.constraints for pb in obj.pose.bones):raise ValueError('Remove custom SOMA bone constraints before adding controls.')
    animation=obj.animation_data
    # Existing FK curves can interpolate differently from aligned IK targets.
    has_motion=bool(keyframes.curves(obj) or (animation and any(
        strip.action and nla_motion.has_keys(strip.action)
        for track in animation.nla_tracks for strip in track.strips)))
    if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    for item in context.selected_objects:item.select_set(False)
    obj.select_set(True);context.view_layer.objects.active=obj
    state=rig.pose_state(obj);rest_hash=rig.fingerprint(obj);units=obj['toyxyz_units']
    rest={name:obj.data.bones[name].matrix_local.copy() for name in rig.NAMES}
    neutral={name:rest[name].copy() for name in rig.NAMES}
    arm=obj.data;main=arm.collections.new('Controls · Body');limbs=arm.collections.new('Controls · Limbs')
    iks=arm.collections.new('Controls · IK');detail=arm.collections.new(FINGER_CONTROLS)
    mechanism=arm.collections.new('Controls · Mechanism');mechanism.is_visible=False
    aligned=arm.collections.new(ALIGNMENT);aligned.is_visible=False
    bpy.ops.object.mode_set(mode='EDIT')
    master=arm.edit_bones.new(MASTER);master.head=(0,0,0);master.tail=(0,.2*units,0);master.use_deform=False;main.assign(master)
    for i,name in enumerate(rig.NAMES):
        source=arm.edit_bones[name];bone=arm.edit_bones.new(fk(name))
        bone.head=source.head.copy();bone.tail=source.tail.copy();bone.roll=source.roll;bone.use_deform=False
        parent=rig.NAMES[rig.PARENTS[i]] if rig.PARENTS[i]>=0 else None
        bone.parent=arm.edit_bones[fk(parent)] if parent else master
        if any(name in limb['bones'] for limb in LIMBS.values()):limbs.assign(bone)
        elif name in rig.SCHEMA['core_names']:main.assign(bone)
        else:detail.assign(bone)
    for key,limb in LIMBS.items():
        for index,name in enumerate(limb['bones']):
            source=arm.edit_bones[fk(name)];bone=arm.edit_bones.new(mch(name))
            bone.head=source.head.copy();bone.tail=source.tail.copy();bone.roll=source.roll;bone.use_deform=False
            bone.parent=arm.edit_bones[mch(limb['bones'][index-1])] if index else source.parent
            mechanism.assign(bone)
        end=arm.edit_bones[fk(limb['bones'][2])]
        target=arm.edit_bones.new(limb['target']);target.length=.12*units;target.matrix=end.matrix.copy()
        target.parent=master;target.use_deform=False;iks.assign(target)
        pole=arm.edit_bones.new(limb['pole']);pole.head=rest_pole_point(neutral,limb,units,neutral[limb['bones'][0]])
        pole.tail=pole.head+Vector((0,0,.08*units))
        pole.parent=target;pole.use_deform=False;iks.assign(pole)
        pairs=[(aligned_fk(name),arm.edit_bones[name]) for name in limb['bones']]
        pairs.append((aligned_ik(key),end))
        for name,source in pairs:
            display=arm.edit_bones.new(name)
            display.head=source.head.copy();display.tail=source.tail.copy();display.roll=source.roll
            display.use_deform=False;aligned.assign(display)
    parent_digit_controls(arm.edit_bones)
    bpy.ops.object.mode_set(mode='OBJECT')
    for name in rig.NAMES:
        pb=obj.pose.bones[fk(name)];original=obj.pose.bones[name]
        pb.rotation_mode=state[name]['mode'];pb.lock_scale=(True,)*3;pb.lock_location=(name!='Hips',)*3
        color=(.15,.65,1.) if name.startswith('Left') else (1.,.35,.12) if name.startswith('Right') else (.95,.75,.18)
        length=obj.data.bones[name].length
        if name=='Hips':shape(pb,'RingJoint',(.23*units,)*3,color)
        elif name in ('LeftHand','RightHand'):shape(pb,'Box',(.075*units,.15*units,.055*units),color)
        elif name=='Head':shape(pb,'Box',(.11*units,.20*units,.11*units),color)
        elif name.startswith('Neck'):shape(pb,'RingJoint',(.045*units,)*3,color)
        elif name.endswith('Shoulder'):shape(pb,'RingJoint',(.045*units,)*3,color)
        elif name.endswith(('Arm','ForeArm','Leg','Shin')):shape(pb,'Box',(.045*units,length,.045*units),color)
        elif name not in rig.FINGER_NAMES:shape(pb,'RingJoint',(.075*units,)*3,color)
        if rig.auxiliary(name) or name=='Jaw':pb.custom_shape=None;pb.hide=True;pb.bone.hide=True
        elif name=='Neck2':pb.bone.hide=True
        original.matrix_basis=Matrix.Identity(4)
    shape(obj.pose.bones[MASTER],'RingGround',(.65*units,)*3,(.95,.75,.18))
    obj.pose.bones[MASTER].rotation_mode='QUATERNION';obj.pose.bones[MASTER].lock_scale=(True,)*3
    for key,limb in LIMBS.items():
        color=(.15,.65,1.) if key.startswith('Left') else (1.,.35,.12)
        target=obj.pose.bones[limb['target']];target.rotation_mode='QUATERNION';target.lock_scale=(True,)*3
        target['ik']=0.;target.id_properties_ui('ik').update(min=0,max=1,default=0,description='0: FK, 1: IK. Use the snap buttons to switch without a pose jump.')
        shape(target,'Box',(.075*units,.15*units,.055*units),color)
        pole=obj.pose.bones[limb['pole']];pole.rotation_mode='QUATERNION';pole.lock_rotation=(True,)*3;pole.lock_scale=(True,)*3
        shape(pole,'Pole',(.04*units,)*3,color)
        show_in_mode(target,obj,target.name,True);show_in_mode(pole,obj,target.name,True)
        for name in limb['bones']:show_in_mode(obj.pose.bones[fk(name)],obj,target.name,False)
        mid=obj.pose.bones[mch(limb['bones'][1])];constraint=mid.constraints.new('IK');constraint.name='Motion AI IK'
        mid.rotation_mode='QUATERNION';mid.rotation_quaternion=Quaternion((0,0,1),.1)
        constraint.target=obj;constraint.subtarget=target.name;constraint.pole_target=obj;constraint.pole_subtarget=pole.name
        constraint.chain_count=2;constraint.use_stretch=False;constraint.iterations=128
        constraint=obj.pose.bones[mch(limb['bones'][2])].constraints.new('COPY_ROTATION');constraint.name='Motion AI End Rotation'
        constraint.target=obj;constraint.subtarget=target.name;constraint.target_space='POSE';constraint.owner_space='POSE'
        calibrate(context,obj,key)
    for name in rig.NAMES:
        pb=obj.pose.bones[name];constraint=pb.constraints.new('COPY_TRANSFORMS');constraint.name='Motion AI Control Output'
        constraint.target=obj;constraint.subtarget=fk(name)
        space='LOCAL' if follows_effector(name) else 'POSE'
        constraint.target_space=space;constraint.owner_space=space
    for limb in LIMBS.values():
        upper,mid,end=limb['bones'];target=limb['target']
        for name,aim in ((upper,mid),(mid,end)):
            pb=obj.pose.bones[name]
            if name==mid:
                constraint=pb.constraints.new('COPY_LOCATION');constraint.name='Motion AI IK Joint'
                constraint.target=obj;constraint.subtarget=mch(name);constraint.target_space='POSE';constraint.owner_space='POSE'
                drive(constraint,'influence',obj,target,'ik')
            constraint=pb.constraints.new('DAMPED_TRACK');constraint.name='Motion AI IK Direction'
            constraint.target=obj;constraint.subtarget=mch(aim);constraint.track_axis='TRACK_Y'
            drive(constraint,'influence',obj,target,'ik')
        constraint=obj.pose.bones[end].constraints.new('COPY_TRANSFORMS');constraint.name='Motion AI IK End'
        constraint.target=obj;constraint.subtarget=mch(end);constraint.target_space='POSE';constraint.owner_space='POSE'
        drive(constraint,'influence',obj,target,'ik')
    for collection in arm.collections:
        if collection.name in ('SOMA Body','SOMA Detail',rig.FINGER_COLLECTION):collection.is_visible=False
    obj[VERSION]=2
    fit_widgets(context,obj)
    fit_clavicle_widgets(obj)
    fit_finger_widgets(obj)
    setup_alignment(obj)
    migrate_actions(obj)
    for name,record in state.items():
        if name not in rig.NAMES:continue
        pb=obj.pose.bones[fk(name)]
        for channel in rig.TRANSFORM_CHANNELS:setattr(pb,channel,record[channel])
    context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe);update(context,obj)
    if not has_motion:
        solved=obj.evaluated_get(context.evaluated_depsgraph_get())
        matrices={name:solved.pose.bones[name].matrix.copy() for limb in LIMBS.values() for name in limb['bones']}
        for limb in LIMBS.values():
            align_ik(obj,limb,matrices)
        update(context,obj)
    assert rig.fingerprint(obj)==rest_hash
    from . import pose_preview
    keyframes.clear();pose_preview.clear()
    for bone in obj.pose.bones:bone.select=False
    obj.pose.bones[fk('Hips')].select=True;obj.data.bones.active=obj.data.bones[fk('Hips')]
    bpy.ops.object.mode_set(mode='POSE')
    return obj

def components_matrix(location,rotation,mode,scale=(1,1,1)):
    if mode=='QUATERNION':q=Quaternion(rotation);q.normalize()
    elif mode=='AXIS_ANGLE':q=Quaternion(Vector(rotation[1:]),rotation[0]) if Vector(rotation[1:]).length else Quaternion()
    else:q=Euler(rotation,mode).to_quaternion()
    return Matrix.LocRotScale(Vector(location),q,Vector(scale))

def master_matrix(obj,corrections,frame):
    from . import unified
    pb=obj.pose.bones[MASTER];channel='rotation_quaternion' if pb.rotation_mode=='QUATERNION' else 'rotation_axis_angle' if pb.rotation_mode=='AXIS_ANGLE' else 'rotation_euler'
    def read(prop):return unified.correction_value(pb.path_from_id(prop),prop,frame,getattr(pb,prop),corrections)
    return obj.data.bones[MASTER].matrix_local@components_matrix(read('location'),read(channel),pb.rotation_mode)

def control_matrices(obj,matrices,master=None):
    """Desired controller bases for a composed model-space result."""
    inverse=(master or Matrix.Identity(4)).inverted();global_matrices={n:inverse@m for n,m in zip(rig.NAMES,matrices)}
    result={fk(n):base for n,base in zip(rig.NAMES,rig.bases(obj,[global_matrices[n] for n in rig.NAMES]))}
    for limb in LIMBS.values():
        target=obj.data.bones[limb['target']];result[target.name]=target.matrix_local.inverted()@global_matrices[limb['bones'][2]]
        pole=obj.data.bones[limb['pole']];matrix=pole.matrix_local.copy()
        matrix.translation=rest_pole_point(global_matrices,limb,obj['toyxyz_units'],obj.data.bones[limb['bones'][0]].matrix_local)
        parent=global_matrices[limb['bones'][2]]@target.matrix_local.inverted()
        result[pole.name]=(parent@pole.matrix_local).inverted()@matrix
    return result


def add_curves(bag,path,index,coordinates):
    curve=bag.fcurves.new(data_path=path,index=index);curve.keyframe_points.add(len(coordinates)//2)
    curve.keyframe_points.foreach_set('co',coordinates)
    for point in curve.keyframe_points:point.interpolation='LINEAR'
    curve.update()

def augment_action(obj,action,slot):
    """Supply legacy generated FK clips with matching IK targets/poles."""
    curves={(fc.data_path,fc.array_index):fc for fc in action_curves(action,slot)}
    if (obj.pose.bones[LIMBS['LeftArm']['target']].path_from_id('location'),0) in curves:return
    times=sorted({float(p.co.x) for fc in curves.values() for p in fc.keyframe_points})
    if not times:return
    values={};previous={};bag=bags(action,slot)[0]
    for at in times:
        matrices={}
        for i,name in enumerate(rig.NAMES):
            pb=obj.pose.bones[fk(name)];mode=pb.rotation_mode;channel='rotation_quaternion' if mode=='QUATERNION' else 'rotation_axis_angle' if mode=='AXIS_ANGLE' else 'rotation_euler'
            def read(prop,defaults):return [curves[pb.path_from_id(prop),axis].evaluate(at) if (pb.path_from_id(prop),axis) in curves else default for axis,default in enumerate(defaults)]
            rotation=read(channel,(1,0,0,0) if channel=='rotation_quaternion' else (0,0,1,0) if channel=='rotation_axis_angle' else (0,0,0))
            basis=components_matrix(read('location',(0,0,0)),rotation,mode)
            parent=rig.PARENTS[i];bone=obj.data.bones[name]
            matrices[name]=(matrices[rig.NAMES[parent]]@obj.data.bones[rig.NAMES[parent]].matrix_local.inverted() if parent>=0 else Matrix.Identity(4))@bone.matrix_local@basis
        controls=control_matrices(obj,[matrices[n] for n in rig.NAMES])
        for limb in LIMBS.values():
            for role in ('target','pole'):
                name=limb[role];pb=obj.pose.bones[name];matrix=controls[name]
                channels=[('location',matrix.translation)]
                if role=='target':
                    q=matrix.to_quaternion()
                    if name in previous and q.dot(previous[name])<0:q.negate()
                    previous[name]=q
                    channels.append(('rotation_quaternion',q))
                for prop,components in channels:
                    for axis,value in enumerate(components):values.setdefault((pb.path_from_id(prop),axis),[]).extend((at,value))
    for (path,axis),coords in values.items():add_curves(bag,path,axis,coords)

def bake_action(obj,data,block,authored):
    from . import nla_motion,unified
    corrections=unified.correction_curves(obj);authored=unified.full_body_overrides(obj,block,authored or {})
    if block.get('root_path'):
        curve_start=block['start']+block['root_path'].get('start_index',0)*data['scene_fps']/data['fps']
        positions={obj.pose.bones[n].path_from_id('location') for n in [fk('Hips'),*[v[k] for v in LIMBS.values() for k in ('target','pole')]]}
        authored={frame:{path:value for path,value in channels.items() if path not in positions or frame<curve_start} for frame,channels in authored.items()}
    action=bpy.data.actions.new('Motion AI · '+data['engine']+' · '+block.get('name','Motion'))
    slot=action.slots.new(id_type='OBJECT',name=obj.name);layer=action.layers.new('Generated Controls');strip=layer.strips.new(type='KEYFRAME');bag=strip.channelbag(slot,ensure=True)
    all_names=[*map(fk,rig.GENERATED_NAMES),*[v[k] for v in LIMBS.values() for k in ('target','pole')]]
    modes={n:obj.pose.bones[n].rotation_mode for n in all_names};values={};previous={}
    try:
        for frame in range(block['start'],block['end']+1):
            root,local=nla_motion.sample_result(data,frame)
            matrices=control_matrices(obj,rig.desired_matrices(obj,local,root),master_matrix(obj,corrections,frame))
            for name,matrix in matrices.items():
                if name not in modes:continue
                pb=obj.pose.bones[name];mode=modes[name]
                prop='rotation_quaternion' if mode=='QUATERNION' else 'rotation_axis_angle' if mode=='AXIS_ANGLE' else 'rotation_euler'
                q=matrix.to_quaternion()
                if mode=='QUATERNION':
                    if name in previous and previous[name].dot(q)<0:q.negate()
                    previous[name]=q.copy();rotation=q
                elif mode=='AXIS_ANGLE':axis,angle=q.to_axis_angle();rotation=(angle,*axis)
                else:rotation=q.to_euler(mode,previous.get(name));previous[name]=rotation.copy()
                channels=[] if name.startswith('Pole_') else [(prop,rotation)]
                if name==fk('Hips') or name.startswith(('IK_','Pole_')):channels.append(('location',matrix.translation))
                for prop,components in channels:
                    components=unified.components(obj,name,prop,frame,components,corrections,authored)
                    for axis,value in enumerate(components):values.setdefault((pb.path_from_id(prop),axis),[]).extend((frame,value))
        for (path,axis),coordinates in values.items():add_curves(bag,path,axis,coordinates)
        action.use_frame_range=True;action.frame_start=block['start'];action.frame_end=block['end']
        nla_motion.mark(action,obj,data['engine'],block.get('prompt',''),False,block.get('uid'))
        action['toyxyz_job_id']=data.get('job_id','');action['toyxyz_rotation_modes']=json.dumps(modes)
        return action,slot
    except BaseException:
        if action.users==0:bpy.data.actions.remove(action)
        raise

def apply_snapshot(context,obj,data,keyframe=None):
    master=obj.pose.bones[MASTER]
    matrices=control_matrices(obj,rig.desired_matrices(obj,data['local_rotations'],data['root']),
                              master.matrix@master.bone.matrix_local.inverted())
    for name,matrix in matrices.items():
        pb=obj.pose.bones[name];pb.matrix_basis=matrix
        if keyframe is not None:
            channel='rotation_quaternion' if pb.rotation_mode=='QUATERNION' else 'rotation_axis_angle' if pb.rotation_mode=='AXIS_ANGLE' else 'rotation_euler'
            if not name.startswith('Pole_'):pb.keyframe_insert(channel,frame=keyframe,group=name)
            if name==fk('Hips') or name.startswith(('IK_','Pole_')):pb.keyframe_insert('location',frame=keyframe,group=name)
    update(context,obj)

def key_transform(pb,at,location=False):
    channel=rotation_channel(pb)
    if not pb.name.startswith('Pole_') and not pb.keyframe_insert(channel,frame=at,group=pb.name):
        raise ValueError('Cannot key the control rotation. Check the active Action and NLA settings.')
    if location and not pb.keyframe_insert('location',frame=at,group=pb.name):
        raise ValueError('Cannot key the control position. Check the active Action and NLA settings.')

def rotation_channel(pb):
    return 'rotation_quaternion' if pb.rotation_mode=='QUATERNION' else 'rotation_axis_angle' if pb.rotation_mode=='AXIS_ANGLE' else 'rotation_euler'

def align_ik(obj,limb,matrices):
    target=obj.pose.bones[limb['target']]
    pole=obj.pose.bones[limb['pole']]
    end=matrices[limb['bones'][-1]]
    master=target.parent
    target_rest=target.bone.matrix_local
    target.matrix_basis=(master.matrix@master.bone.matrix_local.inverted()@target_rest).inverted()@end
    point=snap_pole_point(matrices,limb,obj['toyxyz_units'],obj.data.bones[limb['bones'][0]].matrix_local)
    pole.location=(end@target_rest.inverted()@pole.bone.matrix_local).inverted()@point

def switch(context,obj,key,ik):
    from . import keyframes,rig_store
    if not enabled(obj):raise ValueError('Add the SOMA control rig first.')
    if obj.mode=='EDIT':raise ValueError('Exit Edit Mode before switching FK/IK.')
    if obj.animation_data and obj.animation_data.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before switching FK/IK.')
    if rig_store.deletion_busy(obj):raise ValueError('Finish or cancel generation for this actor before switching FK/IK.')
    limb=LIMBS[key];target=obj.pose.bones[limb['target']]
    update(context,obj)
    solved=obj.evaluated_get(context.evaluated_depsgraph_get())
    old=float(solved.pose.bones[target.name]['ik'])
    if abs(old-ik)<1e-6:return
    matrices={n:solved.pose.bones[n].matrix.copy() for n in limb['bones']}
    at=context.scene.frame_current+context.scene.frame_subframe
    action,slot=rig.pose_action(obj)
    pole=obj.pose.bones[limb['pole']]
    paths={mode_path(target)}
    if ik:
        paths.update((target.path_from_id('location'),target.path_from_id(rotation_channel(target)),pole.path_from_id('location')))
    else:
        for name in limb['bones']:
            pb=obj.pose.bones[fk(name)]
            paths.add(pb.path_from_id(rotation_channel(pb)))
    curves=action_curves(action,slot)
    if action and (not action.is_editable or any((fc.lock or (fc.group and fc.group.lock)) and fc.data_path in paths for fc in curves)):
        raise ValueError('Make the Action local and unlock the destination control curves before switching FK/IK.')
    if not any(fc.data_path==mode_path(target) and fc.keyframe_points for fc in curves):
        target['ik']=old
        if not target.keyframe_insert('["ik"]',frame=at-1,group=target.name):
            raise ValueError('Cannot create the FK/IK mode key. Check the active Action.')
    if ik:
        align_ik(obj,limb,matrices)
        key_transform(target,at,True);key_transform(pole,at,True)
    else:
        for name in limb['bones']:
            pb=obj.pose.bones[fk(name)];pb.matrix=matrices[name];update(context,obj);key_transform(pb,at)
    target['ik']=ik
    if not target.keyframe_insert('["ik"]',frame=at,group=target.name):
        raise ValueError('Cannot key the FK/IK mode. Check the active Action.')
    action,slot=rig.pose_action(obj)
    for fc in action_curves(action,slot):
        if fc.data_path==mode_path(target):
            for point in fc.keyframe_points:point.interpolation='CONSTANT'
            fc.update()
    context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe);update(context,obj)
    from . import pose_preview
    keyframes.clear();pose_preview.changed()

def panel(layout,context,obj):
    if not enabled(obj):return
    header,body=layout.panel('toyxyz_motion_ai_controls',default_closed=True)
    header.label(text='Control Rig')
    if not body:return
    evaluated=obj.evaluated_get(context.evaluated_depsgraph_get())
    for key,limb in LIMBS.items():
        row=body.row(align=True);row.label(text=key.replace('Left','Left ').replace('Right','Right '))
        active=evaluated.pose.bones[limb['target']]['ik']>=.5
        for mode in ('FK','IK'):
            op=row.operator('toyxyz_motion_ai_tool.switch_limb',text=mode,depress=active==(mode=='IK'));op.limb=key;op.mode=mode
    body.prop(obj.data.collections[ALIGNMENT],'is_visible',text='Show Matched Controls')

def selected_actor(context):
    from . import rig_store
    scene=context.scene
    if scene is None:return None
    roster=rig_store.entries(scene)
    index=rig_store.master(scene).active_rig
    if not 0<=index<len(roster):return None
    obj=roster[index].rig
    if obj and obj.type=='ARMATURE' and obj.get('toyxyz_soma') and obj.get('toyxyz_role')=='INPUT':
        return obj
    return None

class TOYXYZ_OT_setup_controls(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.setup_controls';bl_label='Add Control Rig';bl_options={'REGISTER','UNDO'}
    bl_description='Add FK and IK controls to the selected SOMA rig, with all limbs starting in FK'

    @classmethod
    def poll(cls,context):
        obj=selected_actor(context)
        if obj is None:
            cls.poll_message_set('Select a SOMA rig in the list.');return False
        if enabled(obj):
            cls.poll_message_set('This rig already has controls.');return False
        if not obj.visible_get(view_layer=context.view_layer):
            cls.poll_message_set('Show the selected SOMA rig in the current view layer.');return False
        return True

    def execute(self,context):
        try:setup(context,selected_actor(context));return {'FINISHED'}
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}

class TOYXYZ_OT_switch_limb(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.switch_limb';bl_label='Snap FK / IK';bl_options={'REGISTER','UNDO'}
    bl_description='Switch controls while preserving the current limb pose'
    limb:EnumProperty(items=[(key,key,'') for key in LIMBS])
    mode:EnumProperty(items=[('FK','FK',''),('IK','IK','')])
    @classmethod
    def description(cls,context,properties):
        if properties.mode=='FK':return 'Switch to joint rotation controls and match the current pose.'
        return 'Switch to hand or foot controls and match the current pose.'
    def execute(self,context):
        from . import rig_store
        try:switch(context,rig_store.settings(context.scene).rig,self.limb,float(self.mode=='IK'));return {'FINISHED'}
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}

CLASSES=(TOYXYZ_OT_setup_controls,TOYXYZ_OT_switch_limb)
