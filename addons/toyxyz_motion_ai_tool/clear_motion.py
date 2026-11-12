"""Remove selected generated clips while retaining native user keys and blocks."""
import json
import bpy
from mathutils import Matrix
from . import rig,rig_store,timeline,nla_motion,block_links,continuity,client,keyframes,pose_preview


def matches(scene):
    s=rig_store.settings(scene);uids={b.uid for b in timeline.selected(s)}
    return [(track,strip) for track,strip in nla_motion.strips(s.rig)
            if not strip.action.get(nla_motion.REQUEST) and strip.action.get(block_links.UID) in uids]


def reset_base(obj):
    """Clear evaluated generated channels before native authoring/NLA re-evaluation."""
    try:base=json.loads(obj.get(rig.POSE_BASE,'{}'))
    except (TypeError,ValueError):base={}
    from . import control_rig
    bones=(obj.pose.bones[name] for name in control_rig.names(obj)) if control_rig.enabled(obj) else obj.pose.bones
    for bone in bones:
        original_mode=bone.rotation_mode;record=base.get(bone.name)
        if record:
            bone.rotation_mode=record['mode']
            for channel in rig.TRANSFORM_CHANNELS:setattr(bone,channel,record[channel])
            matrix=bone.matrix_basis.copy();bone.rotation_mode=original_mode;bone.matrix_basis=matrix
        else:bone.matrix_basis=Matrix.Identity(4)


def clear(context):
    from . import control_layers
    obj=rig_store.settings(context.scene).rig
    with control_layers.without_layers(context,obj):
        return _clear(context)


def _clear(context):
    from . import unified
    scene=context.scene;s=rig_store.settings(scene);obj=rig.validate_rig(s.rig)
    if rig_store.deletion_busy(obj):raise ValueError('Finish or cancel generation for this rig before clearing motion.')
    if obj.mode=='EDIT':raise ValueError('Exit Edit Mode before clearing motion.')
    ad=obj.animation_data
    if ad and ad.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before clearing motion.')
    source,slot=rig.pose_action(obj)
    selected=timeline.selected(s);items=matches(scene)
    if not items:raise ValueError('Select blocks with generated motion to clear.')
    actions={strip.action for _,strip in items};tracks={track for track,_ in items}
    with block_links.transaction(scene),pose_preview.preserve_edit_state(context,exclude={obj}):
        if ad.action!=source:rig.assign_action(obj,source,slot)
        # Clear every linked version, including inactive legacy tracks, so no old
        # generated clip can reappear. Native authoring Actions are never changed.
        for block in selected:block.has_result=False
        for track,strip in items:track.strips.remove(strip)
        for track in tracks:
            if not track.strips:ad.nla_tracks.remove(track)
        remaining=[(track,strip) for track,strip in nla_motion.strips(obj) if not strip.action.get(nla_motion.REQUEST)]
        if not remaining:
            obj[unified.ENABLED]=False;obj['toyxyz_nla_preview']=False
            obj[continuity.READY]=False
            if continuity.TRACK in obj:del obj[continuity.TRACK]
            ad.use_nla=any(track.strips for track in ad.nla_tracks)
            ad.action_influence=float(obj.get('toyxyz_author_influence',1))
            ad.action_blend_type='COMBINE' if ad.action and ad.action.get(unified.OFFSETS) else 'REPLACE'
            s.last_applied_job=''
        continuity.authoring_prefix(scene,obj)
        reset_base(obj)
        scene.frame_set(scene.frame_current,subframe=scene.frame_subframe);context.view_layer.update()
        if not remaining and rig.POSE_BASE in obj:del obj[rig.POSE_BASE]
    for action in actions:
        if action.users==0 and not action.use_fake_user:bpy.data.actions.remove(action)
    if client.state.get('input_uuid')==obj.get('toyxyz_uuid'):
        client.state.update(result=None,auto_apply_pending=False,auto_apply_error=False,applied_job=None,
                            job_id='',job_status='',progress=None,message='Selected generated motion cleared. User pose keys retained.')
    keyframes.clear();pose_preview.clear()
    timeline.redraw_regions(scene,bpy.context.window_manager.windows)
    return len(items)


class TOYXYZ_OT_clear_motion(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.clear_motion';bl_label='Clear Motion';bl_options={'REGISTER','UNDO'}
    bl_description='Remove all generated motion for selected blocks, keeping their settings and native user pose keys'
    @classmethod
    def poll(cls,context):
        if not context.scene:return False
        s=rig_store.settings(context.scene)
        return bool(s.rig and not rig_store.deletion_busy(s.rig) and matches(context.scene))
    def execute(self,context):
        try:
            clear(context);self.report({'INFO'},'Generated motion cleared. Blocks and user pose keys retained.');return {'FINISHED'}
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
