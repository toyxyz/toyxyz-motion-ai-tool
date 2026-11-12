"""Exact SOMA joint transforms on ordinary Blender armatures; no ML dependencies."""
import hashlib
import json
from pathlib import Path
import uuid
import bpy
from mathutils import Matrix,Quaternion,Vector

SCHEMA=json.loads(Path(__file__).with_name('soma.json').read_text(encoding='utf-8'))
NAMES=SCHEMA['names'];PARENTS=SCHEMA['parents'];C=Matrix(SCHEMA['model_to_blender']);CI=C.transposed()
# The bridge supplies 77 joints. Finger pose belongs to the user Action, while
# the generated wrist still drives the entire hand through the rig hierarchy.
GENERATED_NAMES=tuple(name for name in NAMES
                      if name in ('LeftHand','RightHand') or not name.startswith(('LeftHand','RightHand')))
FINGER_NAMES=tuple(name for name in NAMES if name not in GENERATED_NAMES and not name.endswith('End'))
FINGER_COLLECTION='SOMA Fingers'
IDENTITY=Matrix.Identity(3)
POSE_ACTION='toyxyz_pose_action'
GENERATED_ACTION='toyxyz_generated_action'
POSE_BASE='toyxyz_pose_base'
TRANSFORM_CHANNELS=('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale')
AUX_VISIBILITY='toyxyz_aux_visibility_v1'
ACTOR_NAMES='toyxyz_actor_names_v1'


def next_actor_name():
    """Reserve a free object/data name family rather than Blender's .001 suffix."""
    number=1
    while True:
        name=f'actor_{number:02d}'
        if (not any(bpy.data.objects.get(name+suffix) for suffix in ('','_mesh','_skin'))
                and bpy.data.armatures.get(name) is None
                and not any(bpy.data.meshes.get(name+suffix) for suffix in ('_mesh','_skin'))):return name
        number+=1


def actor_names(obj):
    """Migrate tool defaults once, retaining subsequent user names and animation."""
    if obj.get(ACTOR_NAMES) or obj.get('toyxyz_role')!='INPUT':return
    if obj.name.startswith('toyxyz_motion_ai_tool_SOMA_Edit'):
        obj.name=next_actor_name()
        if obj.data.users==1:obj.data.name=obj.name
    for child in obj.children:
        role=child.get('toyxyz_soma_preview_role')
        if child.get('toyxyz_soma_preview_owner')!=obj.get('toyxyz_uuid'):continue
        if role=='MESH' and child.name.startswith('toyxyz_motion_ai_tool_SOMA_Mesh'):
            child.name=obj.name+'_mesh'
            if child.data.users==1:child.data.name=child.name
        elif role=='INFLUENCES' and child.name.startswith('SOMA Skin Influences'):
            child.name=obj.name+'_skin'
            if child.data.users==1:child.data.name=child.name
    obj[ACTOR_NAMES]=True


def auxiliary(name):return name.endswith('End') or name in ('LeftEye','RightEye')


def hide_auxiliary(obj):
    """Apply the display-only default once, including existing scene rigs."""
    if obj.get(AUX_VISIBILITY):return False
    for name in NAMES:
        if not auxiliary(name):continue
        bone=obj.data.bones.get(name);pose=obj.pose.bones.get(name)
        if bone:bone.hide=True
        if pose:pose.hide=True;pose.select=False
    if obj.data.bones.active and auxiliary(obj.data.bones.active.name):obj.data.bones.active=None
    obj[AUX_VISIBILITY]=True
    return True


def ensure_finger_bones(obj,*,visible):
    """Expose the editable SOMA digits separately from end markers."""
    arm=obj.data
    if arm.collections.get(FINGER_COLLECTION) or not arm.is_editable or obj.mode=='EDIT':return
    fingers=arm.collections.new(FINGER_COLLECTION)
    detail=arm.collections.get('SOMA Detail')
    for name in FINGER_NAMES:
        bone=arm.bones.get(name)
        if bone is None:continue
        fingers.assign(bone)
        if detail and detail in bone.collections.values():detail.unassign(bone)
    fingers.is_visible=visible


def action_slot(action,handle):
    return next((slot for slot in action.slots if slot.handle==handle),None) if action else None


def pose_action(obj):
    """Follow an explicitly assigned user Action; never use the generated bake as targets."""
    animation=obj.animation_data
    if animation and animation.action==obj.get(GENERATED_ACTION) and animation.action is not None:
        action=obj.get(POSE_ACTION)
        return action,action_slot(action,obj.get('toyxyz_pose_slot',0))
    if animation and animation.use_tweak_mode:
        from . import control_layers
        if control_layers.editing(obj):
            action=animation.action_tweak_storage
            return action,action_slot(action,animation.action_slot_handle_tweak_storage)
    return (animation.action,animation.action_slot) if animation else (None,None)


def pose_state(obj):
    return {bone.name:dict(mode=bone.rotation_mode,
                          **{name:list(getattr(bone,name)) for name in TRANSFORM_CHANNELS}) for bone in obj.pose.bones}



def restore_pose_state(obj,state,*,only_changed=False):
    changed=False
    for name,channels in state.items():
        bone=obj.pose.bones.get(name)
        if bone:
            if not only_changed or bone.rotation_mode!=channels['mode']:
                bone.rotation_mode=channels['mode'];changed=True
            for channel in TRANSFORM_CHANNELS:
                if not only_changed or list(getattr(bone,channel))!=channels[channel]:
                    setattr(bone,channel,channels[channel]);changed=True
    if changed:obj.update_tag(refresh={'OBJECT','DATA'})


def assign_action(obj,action,slot):
    animation=obj.animation_data_create();animation.action=action
    if action and slot:animation.action_slot=slot


def show_action(context,obj,generated=False):
    from . import nla_motion
    nla_motion.preview(context,obj,generated)


def legacy_results(scene,obj):
    return [other for other in scene.objects if other!=obj and other.type=='ARMATURE'
            and other.get('toyxyz_soma') and other.get('toyxyz_role')=='RESULT'
            and other.get('toyxyz_source_rig')==obj.get('toyxyz_uuid')]


def consolidate_results(context,obj):
    """Remove only this input's obsolete output objects; retain their Actions as history."""
    removed=[];kept=[]
    for other in legacy_results(context.scene,obj):
        # Keep customized/externally referenced rigs instead of breaking their users.
        users=bpy.data.user_map(subset={other}).get(other,set())
        external=[user for user in users if not isinstance(user,(bpy.types.Collection,bpy.types.Scene))]
        changed_rest=len(other.data.bones)!=len(NAMES)
        try:changed_rest=changed_rest or fingerprint(other)!=other.get('toyxyz_rest_hash')
        except ValueError:changed_rest=True
        animation=other.animation_data
        custom_animation=animation and (len(animation.nla_tracks) or len(animation.drivers))
        if (external or other.children or other.constraints or other.modifiers or changed_rest or custom_animation
                or any(bone.constraints for bone in other.pose.bones) or other.data.users>1
                or len(other.users_scene)>1 or other.library):
            kept.append(other.name);continue
        if other.animation_data and other.animation_data.action:other.animation_data.action.use_fake_user=True
        data=other.data;removed.append(other.name)
        if context.object==other and other.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        if context.view_layer.objects.active==other:context.view_layer.objects.active=obj
        bpy.data.objects.remove(other,do_unlink=True)
        if data.users==0:bpy.data.armatures.remove(data)
    return removed,kept


def fingerprint(obj):
    values=[]
    for i,name in enumerate(NAMES):
        bone=obj.data.bones.get(name)
        if bone is None:raise ValueError('Missing SOMA bone: '+name)
        parent=NAMES[PARENTS[i]] if PARENTS[i]>=0 else None
        if (bone.parent.name if bone.parent else None)!=parent:raise ValueError('SOMA hierarchy changed: '+name)
        values.append([name,*[round(v,7) for row in bone.matrix_local for v in row],round(bone.length,7)])
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def validate_rig(obj):
    if obj is None or obj.type!='ARMATURE' or not obj.get('toyxyz_soma'):raise ValueError('Create a SOMA input rig with this tool first.')
    if fingerprint(obj)!=obj.get('toyxyz_rest_hash'):raise ValueError('The SOMA rest bones were edited. Create a new input rig.')
    return obj


def make_rig(context,result=False):
    if context.object is not None and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    collection=next((c for c in context.scene.collection.children_recursive if c.name=='toyxyz_motion_ai_tool' or c.name.startswith('toyxyz_motion_ai_tool.')),None)
    if collection is None:
        collection=bpy.data.collections.new('toyxyz_motion_ai_tool');context.scene.collection.children.link(collection)
    label='toyxyz_motion_ai_tool_SOMA_Result' if result else next_actor_name()
    arm=bpy.data.armatures.new(label);obj=bpy.data.objects.new(label,arm);collection.objects.link(obj)
    for other in context.selected_objects:other.select_set(False)
    obj.select_set(True);context.view_layer.objects.active=obj
    units=1/max(context.scene.unit_settings.scale_length,1e-6)
    neutral=[Vector(v) for v in SCHEMA['neutral_joints']]
    root=Vector((0,SCHEMA['root_height'],0))
    bpy.ops.object.mode_set(mode='EDIT')
    core=arm.collections.new('SOMA Body');detail=arm.collections.new('SOMA Detail')
    for i,name in enumerate(NAMES):
        bone=arm.edit_bones.new(name);bone.head=C@(neutral[i]+root)*units
        children=[j for j,p in enumerate(PARENTS) if p==i]
        preferred=next((j for j in children if NAMES[j] in SCHEMA['core_names']),children[0] if children else None)
        direction=(C@(neutral[preferred]-neutral[i])) if preferred is not None else Vector((0,0,.035))
        if direction.length<.008:direction=Vector((0,0,.035))
        bone.tail=bone.head+direction*units;bone.use_connect=False
        if PARENTS[i]>=0:bone.parent=arm.edit_bones[NAMES[PARENTS[i]]]
        (core if name in SCHEMA['core_names'] else detail).assign(bone)
    bpy.ops.object.mode_set(mode='OBJECT')
    detail.is_visible=False;arm.display_type='OCTAHEDRAL';obj.show_in_front=True
    arm.show_names=False;arm.show_bone_custom_shapes=True;arm.show_bone_colors=True
    obj['toyxyz_soma']=True;obj['toyxyz_role']='RESULT' if result else 'INPUT';obj['toyxyz_uuid']=uuid.uuid4().hex
    if not result:obj[ACTOR_NAMES]=True
    obj['toyxyz_units']=units;obj['toyxyz_rest_hash']=fingerprint(obj)
    for pb in obj.pose.bones:
        pb.rotation_mode='QUATERNION';pb.lock_scale=(True,True,True)
        if pb.parent:pb.lock_location=(True,True,True)
        pb.color.palette='THEME04' if result else 'THEME03'
    obj.pose.use_auto_ik=False
    hide_auxiliary(obj)
    if not result:ensure_finger_bones(obj,visible=True)
    return obj


def snapshot(context,obj,*,model_only=False):
    validate_rig(obj)
    evaluated=obj.evaluated_get(context.evaluated_depsgraph_get())
    rotations=[];locals=[]
    for name,parent in zip(NAMES,PARENTS):
        if model_only and name not in GENERATED_NAMES:
            # Keep the 77-joint bridge format with neutral finger rotations.
            rotations.append(None);locals.append(IDENTITY)
            continue
        pb=evaluated.pose.bones[name]
        if any(abs(float(v)-1)>.0001 for v in pb.scale):raise ValueError('Keep pose-bone scale at 1.')
        if pb.parent and pb.location.length>1e-4:raise ValueError('Rotate non-root bones; use Hips for translation.')
        rest=obj.data.bones[name].matrix_local.to_3x3()
        rotation=CI@pb.matrix.to_3x3().normalized()@rest.inverted()@C
        rotations.append(rotation)
        locals.append(rotations[parent].transposed()@rotation if parent>=0 else rotation)
    root=CI@evaluated.pose.bones[NAMES[0]].matrix.translation/obj['toyxyz_units']
    return dict(root=list(root),local_rotations=[list(map(list,m)) for m in locals])


def model_snapshot(context,obj):
    return snapshot(context,obj,model_only=True)


def desired_matrices(obj,local_rotations,root):
    units=obj['toyxyz_units'];neutral=[Vector(v) for v in SCHEMA['neutral_joints']]
    global_rot=[];positions=[];matrices=[]
    for j,parent in enumerate(PARENTS):
        local=Matrix(local_rotations[j])
        if parent<0:g=local;position=Vector(root)
        else:g=global_rot[parent]@local;position=positions[parent]+global_rot[parent]@(neutral[j]-neutral[parent])
        global_rot.append(g);positions.append(position)
        rotation=C@g@CI@obj.data.bones[NAMES[j]].matrix_local.to_3x3()
        m=rotation.to_4x4();m.translation=C@position*units;matrices.append(m)
    return matrices


def bases(obj,matrices):
    result=[]
    for j,name in enumerate(NAMES):
        bone=obj.data.bones[name];parent=PARENTS[j]
        if parent<0:base=bone.matrix_local.inverted()@matrices[j]
        else:base=(matrices[parent]@obj.data.bones[NAMES[parent]].matrix_local.inverted()@bone.matrix_local).inverted()@matrices[j]
        result.append(base)
    return result


def set_snapshot(context,obj,data,keyframe=None):
    validate_rig(obj)
    from . import control_rig
    if control_rig.enabled(obj):
        return control_rig.apply_snapshot(context,obj,data,keyframe)
    values=bases(obj,desired_matrices(obj,data['local_rotations'],data['root']))
    for name,matrix in zip(NAMES,values):
        pb=obj.pose.bones[name];pb.matrix_basis=matrix
        if keyframe is not None:
            pb.keyframe_insert('rotation_quaternion',frame=keyframe,group=name)
            if pb.parent is None:pb.keyframe_insert('location',frame=keyframe,group=name)
    context.view_layer.update()


def import_result(context,input_rig,data):
    from . import nla_motion
    return nla_motion.apply(context,input_rig,data)
