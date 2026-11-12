"""Scene roster with persistent per-rig workspaces and scoped asynchronous routing."""
from contextlib import contextmanager
import uuid
import bpy

_overrides={}
_guard=False
_following=False


def master(scene):return scene.toyxyz_motion_ai_tool


def entries(scene):return getattr(scene,'toyxyz_motion_ai_rigs',())


def settings(scene):
    if scene.as_pointer() in _overrides:return _overrides[scene.as_pointer()]
    roster=entries(scene);index=master(scene).active_rig
    return roster[index].data if 0<=index<len(roster) else master(scene)


def for_rig(scene,obj):
    return next((entry.data for entry in entries(scene) if entry.rig==obj),None)


def owner(value):
    """Callbacks can belong to an inactive roster item, including Undo restoration."""
    scene=value.id_data;path=value.path_from_id()
    if path.startswith('toyxyz_motion_ai_rigs['):
        return scene.path_resolve(path.split('.data',1)[0]+'.data')
    return master(scene)


@contextmanager
def use(scene,data):
    key=scene.as_pointer();old=_overrides.get(key)
    _overrides[key]=data
    try:yield data
    finally:
        if old is None:_overrides.pop(key,None)
        else:_overrides[key]=old


def copy_settings(source,target):
    # Copy RNA values, retaining object/Action/curve pointers and original block IDs.
    for prop in source.bl_rna.properties:
        name=prop.identifier
        if name in {'rna_type','active_rig','rig_store_version'} or prop.is_readonly and prop.type!='COLLECTION':continue
        if getattr(prop,'is_skip_save',False):continue
        if prop.type=='COLLECTION':
            dest=getattr(target,name);dest.clear()
            for item in getattr(source,name):copy_settings(item,dest.add())
        else:setattr(target,name,getattr(source,name))
    for key in source.keys():
        if key in source.bl_rna.properties:continue
        value=source[key]
        if hasattr(value,'to_dict'):value=value.to_dict()
        elif hasattr(value,'to_list'):value=value.to_list()
        target[key]=value


def isolate_actor(obj, uid):
    """Give a duplicated actor its own editable Action and Motion AI clips."""
    from . import control_layers,nla_motion,preview_mesh,rig
    animation=obj.animation_data
    if not obj.is_editable or (animation and animation.use_tweak_mode):return
    replacement=uuid.uuid4().hex
    copies={}

    def copy_action(action,slot,editable=False):
        if not action:return action,slot
        owners=[key for key in (nla_motion.OWNER,control_layers.OWNER) if action.get(key)==uid]
        if not owners and not editable:return action,slot
        if action not in copies:
            clone=action.copy();clone.use_fake_user=False
            for key in owners:clone[key]=replacement
            copies[action]=clone
        return copies[action],rig.action_slot(copies[action],slot.handle) if slot else None

    if animation:
        action,slot=copy_action(animation.action,animation.action_slot,editable=True)
        rig.assign_action(obj,action,slot)
        for layer in animation.nla_tracks:
            for strip in layer.strips:
                action,slot=copy_action(strip.action,strip.action_slot)
                if action!=strip.action:
                    strip.action=action
                    if slot:strip.action_slot=slot
    for key in (rig.POSE_ACTION,rig.GENERATED_ACTION):
        if obj.get(key):obj[key]=copy_action(obj[key],None,editable=True)[0]
    preview=[child for child in obj.children if child.get(preview_mesh.OWNER)==uid]
    helper=next((child for child in preview if child.get(preview_mesh.ROLE)=='INFLUENCES'),None)
    for child in preview:
        child[preview_mesh.OWNER]=replacement
        for modifier in child.modifiers:
            if child==helper and modifier.type=='ARMATURE':modifier.object=obj
            group=modifier.node_group if modifier.type=='NODES' else None
            if helper and group and group.get(preview_mesh.ROLE)=='NODES':
                infos=[node for node in group.nodes if node.bl_idname=='GeometryNodeObjectInfo']
                if any(node.inputs['Object'].default_value!=helper for node in infos):
                    if group.users>1:
                        group=group.copy();modifier.node_group=group
                    for node in group.nodes:
                        if node.bl_idname=='GeometryNodeObjectInfo':node.inputs['Object'].default_value=helper
    obj['toyxyz_uuid']=replacement


def ensure(scene):
    """Migrate the original scene workspace once and discover scene-owned SOMA rigs."""
    global _guard
    if _guard:return
    _guard=True
    try:
        from . import rig,legacy_controls,control_rig
        root=master(scene)
        if not root.scene_uid or any(other.session_uid<scene.session_uid and master(other).scene_uid==root.scene_uid
                                     for other in bpy.data.scenes):
            root.scene_uid=uuid.uuid4().hex
        roster=entries(scene)
        previous=roster[root.active_rig].rig if 0<=root.active_rig<len(roster) else None
        for index in reversed(range(len(roster))):
            if not roster[index].rig or roster[index].rig.name not in scene.objects:roster.remove(index)
        seen={entry.rig for entry in roster}
        candidates=[obj for obj in scene.objects if obj.type=='ARMATURE' and obj.get('toyxyz_soma') and obj.get('toyxyz_role')=='INPUT']
        if root.rig in candidates:candidates.remove(root.rig);candidates.insert(0,root.rig)
        first_by_uid={}
        if candidates:
            for obj in bpy.data.objects:
                uid=obj.get('toyxyz_uuid')
                if uid and obj.get('toyxyz_soma') and obj.get('toyxyz_role')=='INPUT':
                    first_by_uid[uid]=min(first_by_uid.get(uid,obj.session_uid),obj.session_uid)
        for obj in candidates:
            uid=obj.get('toyxyz_uuid')
            if not uid:obj['toyxyz_uuid']=uuid.uuid4().hex
            elif obj.session_uid!=first_by_uid[uid]:isolate_actor(obj,uid)
            rig.actor_names(obj)
            legacy_controls.remove(bpy.context,obj)
            rig.hide_auxiliary(obj)
            rig.ensure_finger_bones(obj,visible=not control_rig.enabled(obj))
            control_rig.fit_clavicle_widgets(obj)
            control_rig.fit_finger_widgets(obj)
            if bpy.context.scene==scene:
                control_rig.upgrade_digit_parents(bpy.context,obj)
            if obj in seen:continue
            item=roster.add();item.rig=obj
            try:
                with use(scene,item.data):
                    if not root.rig_store_version and obj==root.rig:copy_settings(root,item.data)
                    item.data.rig=obj;item.data.scene_uid=root.scene_uid
            except Exception:
                roster.remove(len(roster)-1);raise
            seen.add(obj)
        if roster:
            index=next((i for i,item in enumerate(roster) if item.rig==previous),min(max(0,root.active_rig),len(roster)-1))
            if root.active_rig!=index:root.active_rig=index
        else:
            if root.active_rig!=-1:root.active_rig=-1
            if root.rig_store_version:
                if root.rig:root.rig=None
                if root.blocks:root.blocks.clear()
                if root.poses:root.poses.clear()
                if root.last_applied_job:root.last_applied_job=''
        if root.rig_store_version!=1:root.rig_store_version=1
        # Session identity is global to the companion connection, not to selection.
        for item in roster:
            if item.data.scene_uid!=root.scene_uid:item.data.scene_uid=root.scene_uid
    finally:_guard=False


def selected_changed(self,context):
    if _guard:return
    from . import control_layers,keyframes,pose_preview,timeline,pose_edit
    scene=self.id_data;data=settings(scene);obj=data.rig
    if not obj:return
    if pose_edit.busy():pose_edit.cancel_live()
    if context and context.scene==scene:
        for entry in entries(scene):
            if entry.rig!=obj and control_layers.editing(entry.rig):
                control_layers.deselect(context,entry.data)
    if not _following and context and context.scene==scene and obj.name in context.view_layer.objects:
        active=context.view_layer.objects.active
        mode=active.mode if active else 'OBJECT'
        if active and active.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        for other in context.selected_objects:other.select_set(False)
        if obj.visible_get(view_layer=context.view_layer):
            obj.select_set(True);context.view_layer.objects.active=obj
            if mode=='POSE':bpy.ops.object.mode_set(mode='POSE')
    keyframes.clear();pose_preview.clear()
    timeline.redraw_regions(scene,bpy.context.window_manager.windows)


def follow_selection(context):
    """Follow the native active armature without altering selection or editing mode."""
    global _following
    scene=context.scene
    if _guard or _following or scene.as_pointer() in _overrides:return False
    from . import pose_edit
    if pose_edit.busy():return False
    obj=context.view_layer.objects.active
    if not obj or not obj.select_get(view_layer=context.view_layer):return False
    index=next((i for i,item in enumerate(entries(scene)) if item.rig==obj),None)
    if index is None or master(scene).active_rig==index:return False
    _following=True
    try:master(scene).active_rig=index
    finally:_following=False
    return True


def select(scene,obj,context=None):
    ensure(scene)
    index=next((i for i,item in enumerate(entries(scene)) if item.rig==obj),None)
    if index is None:raise ValueError('The SOMA rig is not in this scene.')
    master(scene).active_rig=index
    return settings(scene)


def scene_for_job(uid,session_uid=None):
    matches=[scene for scene in bpy.data.scenes if master(scene).scene_uid==uid
             and (session_uid is None or scene.session_uid==session_uid)]
    return matches[0] if len(matches)==1 else None


def job(scene,rig_uuid,session_uid=None):
    matches=[item.data for item in entries(scene) if item.rig and item.rig.get('toyxyz_uuid')==rig_uuid
             and (session_uid is None or item.rig.session_uid==session_uid)]
    return matches[0] if len(matches)==1 else None


def sync(scene):
    from . import block_links
    for item in entries(scene):
        if item.rig:
            with use(scene,item.data):block_links.sync(scene)


def deletion_busy(obj):
    from . import client
    state=client.state;uid=obj.get('toyxyz_uuid') if obj else None
    return bool(uid and ((state.get('pending_connect') or {}).get('rig_uuid')==uid or
        (state.get('input_uuid')==uid and (state.get('sequence') or state.get('auto_apply_pending') or state['job_status'] in ('queued','running') or
            (state['job_status']=='succeeded' and state.get('job_id') and state.get('result') is None and state.get('applied_job')!=state['job_id'])))))


def delete_selected(context):
    from . import control_layers,preview_mesh,block_links,pose_edit,keyframes,pose_preview
    scene=context.scene;ensure(scene);follow_selection(context);obj=settings(scene).rig
    if obj is None:raise ValueError('Select a SOMA rig to delete.')
    if deletion_busy(obj):raise ValueError('Finish or cancel generation for this rig before deleting it.')
    control_layers.deselect(context,settings(scene))
    if obj.animation_data and obj.animation_data.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before deleting this rig.')
    pose_edit.cancel_live()
    victims=preview_mesh.owned(obj,'MESH')+preview_mesh.owned(obj,'INFLUENCES')+[obj]
    meshes={other.data for other in victims if other.type=='MESH'};armature=obj.data
    groups={modifier.node_group for other in victims for modifier in other.modifiers
        if modifier.type=='NODES' and modifier.node_group and modifier.node_group.get(preview_mesh.ROLE)=='NODES'}
    children={child:child.matrix_world.copy() for other in victims for child in other.children if child not in victims}
    active=context.view_layer.objects.active;was_active=active in victims;mode=active.mode if active else 'OBJECT';name=obj.name
    if was_active and mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    pose_preview.clear()
    with block_links.transaction(scene):
        # Only tool-owned skin objects are removed; preserve unrelated attachments.
        for child,world in children.items():child.parent=None;child.matrix_world=world
        for other in victims:bpy.data.objects.remove(other,do_unlink=True)
        for mesh in meshes:
            if mesh.users==0 and not mesh.use_fake_user:bpy.data.meshes.remove(mesh)
        for group in groups:
            if group.users==0 and not group.use_fake_user:bpy.data.node_groups.remove(group)
        if armature.users==0 and not armature.use_fake_user:bpy.data.armatures.remove(armature)
        ensure(scene)
        survivor=settings(scene).rig
        if was_active and survivor:
            select(scene,survivor,context)
            if mode=='POSE' and survivor.visible_get(view_layer=context.view_layer):bpy.ops.object.mode_set(mode='POSE')
    block_links.clear();keyframes.clear()
    from . import timeline
    timeline.redraw_regions(scene,bpy.context.window_manager.windows)
    return name


class TOYXYZ_UL_soma_rigs(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index=0,flt_flag=0):
        if item.rig:layout.prop(item.rig,'name',text='',emboss=False,icon='ARMATURE_DATA')
        else:layout.label(text='Missing Rig',icon='ERROR')


def panel(layout,context):
    scene=context.scene;root=master(scene)
    layout.label(text='SOMA Rigs')
    layout.template_list('TOYXYZ_UL_soma_rigs','',scene,'toyxyz_motion_ai_rigs',root,'active_rig',rows=3)
    row=layout.row(align=True)
    row.operator('toyxyz_motion_ai_tool.add_soma',text='Add',icon='ADD')
    row.operator('toyxyz_motion_ai_tool.delete_soma',text='Delete',icon='REMOVE')
    layout.operator('toyxyz_motion_ai_tool.setup_controls',icon='ARMATURE_DATA')
