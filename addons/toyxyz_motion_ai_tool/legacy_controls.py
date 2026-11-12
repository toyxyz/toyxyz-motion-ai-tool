"""Discard the withdrawn control-rig extension. No animation conversion or solver."""
import bpy
from . import rig

MARK='toyxyz_control_rig_v1'
COLLECTIONS={'Controls · Body','Controls · Limbs','Controls · IK','Controls · Fingers','Controls · Mechanism'}
ADDED={'CTRL_Master',*('CTRL_'+name for name in rig.NAMES)}
for side in ('Left','Right'):
    for kind,parts in (('Arm',('Arm','ForeArm','Hand')),('Leg',('Leg','Shin','Foot'))):
        ADDED.update({'IK_'+side+parts[-1],'Pole_'+side+kind,'MCH_UnifiedPole_'+side+kind})
        ADDED.update('MCH_IK_'+side+part for part in parts)
PATHS=tuple('pose.bones["'+name+'"]' for name in ADDED)


def control_action(action):
    if not action:return False
    bags=[bag for layer in action.layers for strip in layer.strips if strip.type=='KEYFRAME' for bag in strip.channelbags] if action.is_action_layered else [action]
    return any(fc.data_path.startswith(PATHS) for bag in bags for fc in bag.fcurves)


def purge_widgets():
    collection=bpy.data.collections.get('Motion AI Widgets')
    if not collection:return
    used={pb.custom_shape for obj in bpy.data.objects if obj.type=='ARMATURE' for pb in obj.pose.bones if pb.custom_shape}
    for obj in list(collection.objects):
        if not obj.get('toyxyz_control_widget') or obj in used:continue
        users=bpy.data.user_map(subset={obj}).get(obj,set())
        if any(not isinstance(user,(bpy.types.Collection,bpy.types.Scene)) for user in users):continue
        data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
        if isinstance(data,bpy.types.Mesh) and data.users==0 and not data.use_fake_user:bpy.data.meshes.remove(data)
    if not collection.objects and not collection.children:bpy.data.collections.remove(collection)


def remove(context,obj):
    if not obj.get(MARK):return False
    from . import block_links
    # Mode/depsgraph updates must not interpret withdrawn clips as user deletion.
    with block_links.transaction(context.scene):return discard(context,obj)


def discard(context,obj):
    """One-shot removal on the actor's next safe scene update; no keys are baked."""
    if not obj.get(MARK):return False
    from . import rig_store,nla_motion,continuity,unified,keyframes,pose_preview,block_links
    if context.scene not in obj.users_scene or obj.name not in context.view_layer.objects:return False
    if obj.library or obj.mode=='EDIT' or rig_store.deletion_busy(obj):return False
    if any(window.modal_operators for window in context.window_manager.windows):return False
    ad=obj.animation_data
    if ad and ad.use_tweak_mode:return False
    active=context.view_layer.objects.active;mode=active.mode if active else 'OBJECT'
    selected=list(context.selected_objects)
    context.view_layer.update()
    evaluated=obj.evaluated_get(context.evaluated_depsgraph_get())
    # Preserve only the visible static pose, never old controller animation.
    matrices=[evaluated.pose.bones[name].matrix.copy() for name in rig.NAMES]
    if active and mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    if obj.data.users>1:obj.data=obj.data.copy()
    removed_uids=set()
    if ad:
        for track in list(ad.nla_tracks):
            removed=False
            for strip in list(track.strips):
                if nla_motion.owned(obj,strip) and control_action(strip.action):
                    removed_uids.add(strip.action.get('toyxyz_block_uid',''))
                    track.strips.remove(strip);removed=True
            if removed and not track.strips:ad.nla_tracks.remove(track)
        if control_action(ad.action):ad.action=None
        for fc in list(ad.drivers):
            targets=[target for var in fc.driver.variables for target in var.targets]
            if fc.data_path.startswith(PATHS) or any(target.id==obj and (target.data_path.startswith(PATHS) or target.bone_target in ADDED) for target in targets):
                ad.drivers.remove(fc)
    for pb in obj.pose.bones:
        if pb.name not in rig.NAMES:continue
        for con in list(pb.constraints):
            if (con.name in {'Motion AI Control Output','Motion AI IK Joint','Motion AI IK Direction','Motion AI IK End'}
                    or (getattr(con,'target',None)==obj and getattr(con,'subtarget','') in ADDED)):
                con.driver_remove('influence');pb.constraints.remove(con)
    for other in context.selected_objects:other.select_set(False)
    obj.select_set(True);context.view_layer.objects.active=obj
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in list(obj.data.edit_bones):
            if bone.name in ADDED:obj.data.edit_bones.remove(bone)
    finally:
        if obj.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    for collection in list(obj.data.collections):
        if collection.name in COLLECTIONS:obj.data.collections.remove(collection)
    core=obj.data.collections.get('SOMA Body');detail=obj.data.collections.get('SOMA Detail')
    if core:core.is_visible=True
    if detail:detail.is_visible=False
    obj.pose.use_auto_ik=False;obj.data.display_type='OCTAHEDRAL';obj.show_in_front=True
    obj.data.show_names=False;obj.data.show_bone_custom_shapes=True;obj.data.show_bone_colors=True
    for pb in obj.pose.bones:
        if pb.name not in rig.NAMES:continue
        pb.custom_shape=None;pb.bone.hide_select=False
        pb.hide=pb.bone.hide=rig.auxiliary(pb.name);pb.select=False
        pb.lock_location=(pb.name!='Hips',)*3;pb.lock_rotation=(False,)*3;pb.lock_rotation_w=False
        pb.lock_scale=(True,)*3;pb.lock_ik_x=pb.lock_ik_y=pb.lock_ik_z=False
        pb.color.palette='THEME03'
    for name,matrix in zip(rig.NAMES,rig.bases(obj,matrices)):obj.pose.bones[name].matrix_basis=matrix
    for key in list(obj.keys()):
        if key.startswith(('toyxyz_control_','toyxyz_unified_controls_','toyxyz_unified_pole_','toyxyz_free_pole_')) or key in (rig.POSE_BASE,rig.POSE_ACTION,rig.GENERATED_ACTION,'toyxyz_pose_slot'):
            del obj[key]
    obj[rig.AUX_VISIBILITY]=True
    if not nla_motion.strips(obj):
        obj[continuity.READY]=False;obj[unified.ENABLED]=False;obj['toyxyz_nla_preview']=False
        if continuity.TRACK in obj:del obj[continuity.TRACK]
        if ad:ad.action_influence=1;ad.action_blend_type='REPLACE'
    settings=[]
    for scene in obj.users_scene:
        data=rig_store.for_rig(scene,obj)
        if data:settings.append(data)
        if rig_store.master(scene).rig==obj:settings.append(rig_store.master(scene))
    for data in settings:
        for block in data.blocks:
            if block.uid in removed_uids:block.has_result=False
        if removed_uids:data.last_applied_job=''
    # Intentional clip removal must not be interpreted as deleting prompt blocks.
    block_links.clear()
    obj.update_tag(refresh={'OBJECT','DATA'});context.view_layer.update()
    obj.select_set(False)
    for other in selected:
        if other.name in context.view_layer.objects:other.select_set(True)
    context.view_layer.objects.active=active
    if active and mode!='OBJECT':bpy.ops.object.mode_set(mode=mode)
    keyframes.clear();pose_preview.clear();purge_widgets()
    return True


def restore_tools():
    """Replace the withdrawn saved toolbar entry with Blender's normal Move."""
    if bpy.app.background:return
    for window in bpy.context.window_manager.windows:
        if window.modal_operators:continue
        for area in window.screen.areas:
            if area.type!='VIEW_3D':continue
            with bpy.context.temp_override(window=window,area=area):
                if bpy.context.mode!='POSE':continue
                tool=bpy.context.workspace.tools.from_space_view3d_mode('POSE',create=False)
                if tool and tool.idname=='toyxyz_motion_ai_tool.pole_move':bpy.ops.wm.tool_set_by_id(name='builtin.move')
