bl_info={
    'name':'toyxyz_motion_ai_tool','author':'toyxyz','version':(0,46,1),'blender':(5,2,0),
    'location':'Motion Timeline / 3D View > Sidebar > Motion AI',
    'description':'External motion generation with native NLA tracks and user pose keys',
    'category':'Animation',
}

import json
import os
from pathlib import Path
import subprocess
import textwrap
import uuid
import webbrowser
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty,CollectionProperty,EnumProperty,FloatProperty,IntProperty,PointerProperty,StringProperty
from . import client,rig,keyframes,nla_motion,model_limits,timeline,block_links,generation,curve_paths,kimodo_context,pose_constraints,legacy_scene,pose_edit,preview_mesh
from . import control_layers
from . import pose_preview,rig_store,clear_motion,lifetime,legacy_controls,control_rig,object_constraints,scene_sampling,final_motion
from . import agent_bridge

MODEL_ITEMS=(
    ('kimodo','Kimodo','Generate motion from text and pose constraints'),
    ('motionbricks','MotionBricks','Generate motion between full-body pose targets'),
    ('ardy','ARDY','Generate motion in successive chunks from text and pose constraints'),
)

def runtime_default():
    config=Path(__file__).with_name('app_location.json')
    if config.exists():
        try:return json.loads(config.read_text(encoding='utf-8'))['root']
        except Exception:pass
    candidate=Path(__file__).resolve().parents[2]
    return str(candidate) if (candidate/'runtime/entry.py').is_file() else ''


class TOYXYZ_Preferences(bpy.types.AddonPreferences):
    bl_idname=__package__
    runtime_root:StringProperty(name='External App Folder',description='Folder containing the companion app and its portable Python',subtype='DIR_PATH',default=runtime_default())
    port:IntProperty(name='Port',description='Local port used to connect to the companion app',default=8790,min=1024,max=65535)
    def draw(self,context):
        self.layout.prop(self,'runtime_root');self.layout.prop(self,'port')
        self.layout.label(text='AI packages run in the external app, using its bundled python_embeded folder.')


def block_model_changed(self,context):
    if rig_store._guard:return
    scene=self.id_data
    if isinstance(scene,bpy.types.Scene):
        rig_store.owner(self).engine=self.engine;timeline.limit(self)


def active_block_changed(self,context):
    if rig_store._guard:return
    self.selection='BLOCK'
    if self.blocks:
        self.engine=self.blocks[min(self.active_block,len(self.blocks)-1)].engine
        if not timeline._selection_guard:timeline.select(self,min(max(0,self.active_block),len(self.blocks)-1))


def block_selection_changed(self,context):
    if timeline._selection_guard or rig_store._guard:return
    s=rig_store.owner(self);s.block_selection_initialized=True
    if self.selected:
        index=next((i for i,b in enumerate(s.blocks) if b==self),None)
        if index is not None:timeline.focus(s,index)
    elif timeline.selected(s) and not timeline.active(s).selected:
        timeline.focus(s,next(i for i,b in enumerate(s.blocks) if b.selected))


def active_pose_changed(self,context):self.selection='POSE'

def block_start_changed(self,context):timeline.limit(self,'START')
def block_end_changed(self,context):timeline.limit(self,'END')


def current_engine(s):
    return timeline.active(s).engine if s.blocks else s.engine


class TOYXYZ_Prompt(bpy.types.PropertyGroup):
    uid:StringProperty()
    has_result:BoolProperty(default=False,options={'HIDDEN'})
    selected:BoolProperty(name='Selected',description='Include this block in Generate Motion',default=False,update=block_selection_changed)
    name:StringProperty(name='Block Name',default='Motion')
    engine:EnumProperty(name='Model',description='Choose the motion model for this block',items=MODEL_ITEMS,default='ardy',update=block_model_changed)
    start:IntProperty(name='Start',description='First frame of the motion block',default=1,min=-1000000,max=1000000,update=block_start_changed)
    end:IntProperty(name='End (exclusive)',description='First frame after the motion block',default=61,min=-1000000,max=1000000,update=block_end_changed)
    prompt:StringProperty(name='Prompt',description=timeline.PROMPT_TOOLTIP,default='A person walks forward.')
    path_curve:PointerProperty(name='Path Curve',type=bpy.types.Object,poll=curve_paths.poll,
        description=timeline.PATH_TOOLTIP)
    path_start_percent:FloatProperty(name='Curve Start (%)',min=0,max=100,precision=1,step=100,
        get=curve_paths.get_start_percent,set=curve_paths.set_start_percent,
        description=timeline.PATH_START_TOOLTIP)
    transition_frames:IntProperty(name='Transition Overlap (30 FPS)',default=5,min=1,max=300,soft_max=30,
        description=timeline.TRANSITION_TOOLTIP)
    enabled:BoolProperty(name='Enabled',description='Include this block when generating selected motion',default=True)


class TOYXYZ_Pose(bpy.types.PropertyGroup):
    # Read old .blend data without deleting it. Generation uses native keys only.
    uid:StringProperty()
    name:StringProperty(name='Pose Name',default='Pose')
    frame:IntProperty(name='Frame',default=1,min=-1000000,max=1000000)
    kind:EnumProperty(name='Type',items=[('FULL','Full Body',''),('ROOT','Root Position',''),('LEFT_HAND','Left Hand',''),('RIGHT_HAND','Right Hand',''),('LEFT_FOOT','Left Foot',''),('RIGHT_FOOT','Right Foot','')],default='FULL')
    snapshot:StringProperty(options={'HIDDEN'})
    enabled:BoolProperty(name='Enabled',default=True)


def input_poll(self,obj):return obj.type=='ARMATURE' and obj.get('toyxyz_role')=='INPUT'


class TOYXYZ_Settings(bpy.types.PropertyGroup):
    active_rig:IntProperty(default=-1,min=-1,update=rig_store.selected_changed)
    rig_store_version:IntProperty(default=0,options={'HIDDEN'})
    show_pose_targets:BoolProperty(name='Show Pose Targets',description='Preview the constraints sent to the model for selected motion blocks',default=True,update=pose_preview.changed)
    pose_targets_in_front:BoolProperty(name='Targets In Front',description='Draw pose targets on top of scene geometry',default=True,update=pose_preview.changed)
    pose_target_size:FloatProperty(name='Target Radius (m)',description='Radius of the point targets in metres',default=.035,min=.005,max=.2,precision=3,update=pose_preview.changed)
    pose_target_opacity:FloatProperty(name='Point Opacity',description='Opacity of the point targets',default=.5,min=.05,max=1,subtype='FACTOR',update=pose_preview.changed)
    pose_target_line_width:FloatProperty(name='Line Width',description='Thickness of the pose preview lines in pixels before UI scaling',
        default=pose_preview.LINE_WIDTH,min=.5,max=6,precision=1,step=10,update=pose_preview.redraw_display)
    pose_target_line_opacity:FloatProperty(name='Line Opacity',description='Opacity of the pose preview lines',default=pose_preview.LINE_OPACITY,min=0,max=1,
        subtype='FACTOR',update=pose_preview.redraw_display)
    pose_target_axes:BoolProperty(name='Target Rotation Axes',description='Show orientation axes for targets with a rotation',default=False,update=pose_preview.changed)
    pose_target_labels:BoolProperty(name='Target Frame Labels',description='Show the frame and constraint type beside each target',default=True,update=pose_preview.changed)
    scene_uid:StringProperty()
    last_applied_job:StringProperty()
    timeline_migrated:BoolProperty(default=False)
    block_selection_initialized:BoolProperty(default=False,options={'HIDDEN'})
    timeline_tree:PointerProperty(type=bpy.types.NodeTree)
    rig:PointerProperty(name='SOMA Input Rig',description='Rig whose pose keys and motion blocks are being edited',type=bpy.types.Object,poll=input_poll)
    show_soma_mesh:BoolProperty(name='Show SOMA Mesh',description='Show the active rig’s body mesh in the viewport',
        default=True,update=preview_mesh.visibility)
    blocks:CollectionProperty(type=TOYXYZ_Prompt)
    poses:CollectionProperty(type=TOYXYZ_Pose)
    object_constraints:CollectionProperty(type=object_constraints.TOYXYZ_ObjectConstraint)
    active_object_constraint:IntProperty(default=-1,min=-1)
    active_block:IntProperty(default=0,update=active_block_changed)
    active_pose:IntProperty(default=0,update=active_pose_changed)
    pose_key_frame:FloatProperty(default=1)
    constraint_kind:EnumProperty(name='Constraint Type',items=pose_constraints.ITEMS,get=pose_constraints.ui_get,set=pose_constraints.ui_set,
        options={'SKIP_SAVE'},description='Generation constraint for the native SOMA pose key at the current frame')
    constraint_kinds:EnumProperty(name='Constraint Types',items=pose_constraints.FLAGS,options={'ENUM_FLAG','SKIP_SAVE'},
        get=pose_constraints.ui_flags_get,set=pose_constraints.ui_flags_set,
        description='Combine hand, foot and root goals at this native key; Full Body is exclusive')
    root_heading:BoolProperty(name='Constrain Root Heading',options={'SKIP_SAVE'},
        get=pose_constraints.ui_heading_get,set=pose_constraints.ui_heading_set,
        description='Also constrain the facing direction of this keyed pose; available with Root Position (2D)')
    root_height:BoolProperty(name='Constrain Root Height',options={'SKIP_SAVE'},
        get=pose_constraints.ui_height_get,set=pose_constraints.ui_height_set,
        description='Use the visible keyed hips height as a soft model goal; accuracy varies, especially for large height changes')
    selection:EnumProperty(items=[('BLOCK','Block',''),('POSE','Pose',''),('CONSTRAINT','Constraint',''),('LAYER','Control Layer','')],default='BLOCK')
    timeline_lane_scroll:FloatProperty(default=0,min=0,options={'HIDDEN'})
    engine:EnumProperty(name='Model',description='Choose the default model for new motion blocks',items=MODEL_ITEMS,default='ardy')
    precision:EnumProperty(name='Text Encoder',description='Choose the encoder precision to balance VRAM use and quality',items=(
        ('bf16','BF16 · Default','Default encoder precision'),
        ('int8','INT8','8-bit encoder with reduced VRAM use'),
        ('nf4','NF4','4-bit encoder with the lowest encoder VRAM use'),
    ),default='bf16')
    seed:IntProperty(name='Seed',description='Change the random seed to generate a variation',default=0,min=0)
    steps:IntProperty(name='Denoising Steps',description='Number of Kimodo refinement steps per generation',default=30,min=1,max=200)
    ardy_steps:IntProperty(name='Denoising Steps',description='Number of ARDY refinement steps per chunk',default=10,min=1,max=10)
    text_weight:FloatProperty(name='Text Guidance',description='How strongly the motion follows the prompt',default=2,min=0,max=20)
    constraint_weight:FloatProperty(name='Constraint Guidance',description='How strongly the motion follows pose and path constraints',default=2,min=0,max=20)
    postprocess:BoolProperty(name='Motion Post-Processing',description='Apply the model’s motion cleanup after generation',default=True)
    timeline_show_channels:BoolProperty(name='Channels',description='Show the row labels beside the motion timeline',default=False)
    timeline_show_seconds:BoolProperty(name='Seconds',description='Show seconds on the ruler instead of frame numbers',default=False)
    view_start:FloatProperty(default=-8)
    pixels_per_frame:FloatProperty(default=7,min=.15,max=80)


def settings(context):
    value=rig_store.settings(context.scene)
    return value


class TOYXYZ_RigEntry(bpy.types.PropertyGroup):
    rig:PointerProperty(type=bpy.types.Object,poll=input_poll)
    data:PointerProperty(type=TOYXYZ_Settings)


def preferences(context):
    entry=context.preferences.addons.get(__package__)
    if entry:return entry.preferences
    return None


def endpoint(context):
    pref=preferences(context)
    return 'http://127.0.0.1:'+str(pref.port if pref else 8790)


@scene_sampling.transient
def request_data(context,engine=None,blocks=None,*,include_history=True,include_following=True):
    s=settings(context);obj=rig.validate_rig(s.rig)
    if obj.get('toyxyz_role')!='INPUT':raise ValueError('Select the editable input rig.')
    with control_layers.without_layers(context,obj,preserve_pose=True):
        return _request_data(context,s,obj,engine,blocks,include_history,include_following)


def _request_data(context,s,obj,engine,blocks,include_history,include_following):
    timeline.migrate_blocks(context.scene)
    from . import correction_bounds
    correction_bounds.sync(context.scene,obj)
    if blocks is None:engine,blocks=timeline.generation_blocks(context)
    if engine=='mixed':raise ValueError('Use Generate Motion to generate the mixed-model selection in order.')
    blocks=curve_paths.attach(context,blocks)
    following=kimodo_context.following_clip(obj,s,blocks) if include_following else None
    goals=[]
    for block in blocks:
        targets=object_constraints.sample(context,s,block['start'],block['end'])
        block[object_constraints.SIGNATURE]=object_constraints.stamp(targets)
        goals.extend(targets)
    if goals:
        with pose_preview.preserve_edit_state(context,exclude=(obj,)):
            poses=keyframes.targets(context,obj,blocks,engine=engine,object_goals=goals,following=bool(following))
    else:poses=keyframes.targets(context,obj,blocks,engine=engine,following=bool(following))
    if blocks[0].get('root_path') and not blocks[0]['root_path'].get('start_index',0) and poses and poses[0].get('source')=='previous_motion_end':
        point=blocks[0]['root_path']['points'][0];root=poses[0]['root']
        if ((point[0]-root[0])**2+(point[1]-root[2])**2)**.5>.25:
            raise ValueError('Path Curve starts away from the previous motion. Increase Curve Start (%) for an approach, or move the curve start to the previous endpoint.')
    previous=kimodo_context.previous_motion(context,obj,blocks,history_frames=240 if engine=='ardy' else None) if include_history and engine in ('kimodo','ardy') else None
    next_motion=kimodo_context.following_motion(context,obj,blocks,engine,following) if following and include_history else None
    if include_history:
        inherited=next((pose for pose in poses if pose.get('source')=='previous_motion_end'),None)
        if previous:blocks[0]['previous_motion_signature']=kimodo_context.signature(previous)
        if inherited:blocks[0]['inherited_pose_signature']=kimodo_context.signature(inherited)
        if next_motion:blocks[-1]['following_motion_signature']=kimodo_context.signature(next_motion)
        stamps=keyframes.value_signatures(obj,blocks)
        for block in blocks:block['pose_keys_signature']=stamps[block['uid']]
    return dict(protocol=1,engine=engine,precision=s.precision,joint_names=rig.NAMES,previous_motion_context=previous,
                next_motion_context=next_motion,
                fps=context.scene.render.fps/context.scene.render.fps_base,blocks=blocks,poses=poses,
                seed=s.seed,steps=s.ardy_steps if engine=='ardy' else s.steps,postprocess=s.postprocess,text_weight=s.text_weight,constraint_weight=s.constraint_weight)


class TOYXYZ_OT_open_timeline(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.open_timeline';bl_label='Open Motion Timeline';bl_description='Add, move and edit generation blocks in the dedicated timeline'
    def execute(self,context):
        area=context.area
        if area.type=='VIEW_3D':
            other=next((a for a in context.screen.areas if a.type=='NLA_EDITOR' or (a.type=='NODE_EDITOR' and a.ui_type=='ToyxyzMotionAITimeline')),None)
            if other is None:other=next((a for a in context.screen.areas if a.type=='DOPESHEET_EDITOR'),None)
            if other:area=other
        timeline.migrate_blocks(context.scene)
        tree=timeline.ensure_tree(context.scene)
        area.type='NODE_EDITOR';area.ui_type=timeline.TREE
        area.spaces.active.pin=False;area.spaces.active.node_tree=tree
        area.spaces.active.show_region_ui=True;area.tag_redraw()
        return {'FINISHED'}


class TOYXYZ_OT_rig(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.create_soma';bl_label='Create SOMA Rig + Mesh';bl_options={'REGISTER','UNDO'}
    bl_description='Set up a SOMA rig with a body preview mesh'
    def execute(self,context):
        rig_store.ensure(context.scene)
        s=settings(context)
        obj=s.rig or next((o for o in context.scene.objects if input_poll(s,o)),None)
        if obj is None:obj=rig.make_rig(context)
        else:
            rig.validate_rig(obj)
            if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            for other in context.selected_objects:other.select_set(False)
            obj.select_set(True);context.view_layer.objects.active=obj
            rig.show_action(context,obj,generated=any(not strip.action.get(nla_motion.REQUEST) for _,strip in nla_motion.strips(obj)))
        if rig_store.for_rig(context.scene,obj) is None:
            rig_store.ensure(context.scene)
        s=rig_store.select(context.scene,obj,context);s.rig=obj
        try:preview_mesh.ensure(context,obj)
        except (OSError,ValueError) as exc:self.report({'WARNING'},'Rig ready; mesh unavailable: '+str(exc))
        rig.consolidate_results(context,obj)
        from .timeline import ensure_tree
        ensure_tree(context.scene)
        if not s.scene_uid:s.scene_uid=uuid.uuid4().hex
        timeline.migrate_blocks(context.scene)
        if not s.blocks:timeline.add(context.scene)
        bpy.ops.object.mode_set(mode='POSE');self.report({'INFO'},'SOMA rig ready. Pose the bones and insert keyframes; pose targets are detected automatically.')
        return {'FINISHED'}


class TOYXYZ_OT_add_rig(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.add_soma';bl_label='Add SOMA Rig';bl_options={'REGISTER','UNDO'}
    bl_description='Create an independent SOMA rig, body preview and motion timeline'
    def execute(self,context):
        try:
            rig_store.ensure(context.scene)
            obj=rig.make_rig(context);s=rig_store.select(context.scene,obj,context)
            # The cursor provides an explicit placement for each new character.
            obj.location=context.scene.cursor.location
            try:preview_mesh.ensure(context,obj)
            except (OSError,ValueError) as exc:self.report({'WARNING'},'Rig ready; mesh unavailable: '+str(exc))
            timeline.ensure_tree(context.scene);timeline.migrate_blocks(context.scene)
            if not s.blocks:timeline.add(context.scene)
            bpy.ops.object.mode_set(mode='POSE')
            self.report({'INFO'},'Independent SOMA rig added.');return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class TOYXYZ_OT_delete_rig(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.delete_soma';bl_label='Delete SOMA Rig';bl_options={'REGISTER','UNDO'}
    bl_description='Delete the selected SOMA rig, its preview mesh and skin helper; undo with Ctrl+Z'
    @classmethod
    def poll(cls,context):
        obj=settings(context).rig if context.scene else None
        if obj is None:return False
        if rig_store.deletion_busy(obj):
            cls.poll_message_set('Finish or cancel generation for this rig before deleting it.');return False
        return True
    def execute(self,context):
        try:
            name=rig_store.delete_selected(context)
            self.report({'INFO'},'Deleted SOMA rig and mesh: '+name);return {'FINISHED'}
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class TOYXYZ_OT_block(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.add_block';bl_label='Add Motion Block';bl_options={'REGISTER','UNDO'}
    bl_description='Add a motion block to the active rig’s timeline'
    @classmethod
    def poll(cls,context):return context.scene is not None and rig_store.settings(context.scene).rig is not None
    def execute(self,context):
        s=settings(context);rig.validate_rig(s.rig)
        control_layers.deselect(context,s)
        timeline.add(context.scene)
        return {'FINISHED'}


class TOYXYZ_OT_delete(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.delete_item';bl_label='Delete Selected Items';bl_options={'REGISTER','UNDO'}
    bl_description='Delete the selection in the active timeline row'
    confirm:BoolProperty(default=False,options={'SKIP_SAVE'})
    target:EnumProperty(items=[('AUTO','Active Row',''),('BLOCK','Motion Blocks',''),('POSE','Pose Keys',''),
                               ('CONSTRAINT','Object Constraint',''),('LAYER','Control Layer','')],default='AUTO',options={'HIDDEN','SKIP_SAVE'})
    @classmethod
    def description(cls,context,properties):
        return {
            'BLOCK':'Delete the selected motion blocks and their linked NLA strips.',
            'POSE':'Delete the selected pose keys and their constraint settings.',
            'CONSTRAINT':'Delete the selected object constraint marker.',
            'LAYER':'Delete the selected Control Layer and its keys.',
        }.get(properties.target,cls.bl_description)
    @classmethod
    def poll(cls,context):return timeline.ours(context) and bool(timeline.delete_target(context))
    def invoke(self,context,event):
        target=timeline.delete_target(context,self.target)
        if target is None:return {'CANCELLED'}
        self.target=target
        if self.confirm:return context.window_manager.invoke_confirm(self,event)
        return self.execute(context)
    def execute(self,context):
        s=settings(context)
        try:
            target=timeline.delete_target(context,self.target)
            if target is None:raise ValueError('Select motion blocks, pose keys or a Control Layer to delete.')
            if target=='CONSTRAINT':object_constraints.remove(s);object_constraints.changed(None,context)
            elif target=='POSE':pose_edit.delete(context,s.rig,pose_edit.selected(s.rig))
            elif target=='LAYER':control_layers.delete(context,s)
            else:
                control_layers.deselect(context,s)
                block_links.delete_selected(context.scene)
            context.view_layer.update()
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        return {'FINISHED'}


class TOYXYZ_OT_remove_block(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.remove_block';bl_label='Delete Motion Block';bl_options={'UNDO'}
    bl_description='Delete the selected motion blocks and their linked NLA strips'
    @classmethod
    def poll(cls,context):return context.scene is not None and bool(timeline.selected(settings(context)))
    def execute(self,context):
        try:
            control_layers.deselect(context,settings(context))
            block_links.delete_selected(context.scene);return {'FINISHED'}
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class TOYXYZ_OT_connect(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.connect';bl_label='Reconnect';bl_description='Reconnect to the running companion app without launching another process'
    def execute(self,context):
        rig_store.ensure(context.scene)
        s=settings(context)
        if client.state.get('stopping'):
            self.report({'ERROR'},'Wait for the app to stop before reconnecting.');return {'CANCELLED'}
        if client.state.get('sequence') or client.state['job_status'] in ('queued','running'):
            self.report({'ERROR'},'Finish or cancel generation before reconnecting.');return {'CANCELLED'}
        if not s.scene_uid:s.scene_uid=uuid.uuid4().hex
        client.state.update(app_running=client.state.get('app_running',False) or client.state['connected'],
                            connected=False,connecting=True,stopping=False,scene_uid=s.scene_uid,message='Connecting to external app...')
        pref=preferences(context)
        root=Path(bpy.path.abspath(pref.runtime_root if pref else runtime_default())).resolve()
        client.start(endpoint(context),s.scene_uid,root);return {'FINISHED'}


_launched_app=None


class TOYXYZ_OT_launch(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.launch_app';bl_label='Start';bl_description='Start the companion app and connect, or connect to it if already running'
    def execute(self,context):
        global _launched_app
        try:
            if client.state.get('stopping'):raise ValueError('Wait for the app to stop before starting it again.')
            if client.state.get('sequence') or client.state['job_status'] in ('queued','running'):
                raise ValueError('Finish or cancel generation before reconnecting.')
            base=endpoint(context)
            pref=preferences(context);root=Path(bpy.path.abspath(pref.runtime_root if pref else runtime_default())).resolve()
            owner_job=lifetime.prepare(root)
            env=dict(os.environ);env[lifetime.ENV]=owner_job
            needs_update=False
            try:
                info=client.request(base,'/health',timeout=.6)
                if info.get('app')!=client.APP or info.get('protocol')!=1:raise ValueError('A different or incompatible app is using this port.')
                capabilities=set(info.get('capabilities',[]))
                needs_update=not {'blender_process_lifetime','object_constraints','next_motion_context','atomic_cancel'}<=capabilities or 'image_pose_capture' in capabilities
                if needs_update and not (_launched_app and _launched_app[0]==base and _launched_app[1].poll() is None):
                    helper=root/'runtime/ensure_companion_service.py'
                    if not helper.is_file():raise ValueError('Update the companion app files first.')
                    with (root/'logs/toyxyz_motion_ai_tool_app.log').open('ab') as log:
                        process=subprocess.Popen([str(root/'python_embeded/python.exe'),'-X','utf8','-u',str(helper),
                            '--port',str(pref.port if pref else 8790)],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
                    _launched_app=(base,process)
            except (OSError,TimeoutError):
                # A second click during startup must not launch another process.
                if not (_launched_app and _launched_app[0]==base and _launched_app[1].poll() is None):
                    exe=root/'python_embeded/python.exe';entry=root/'runtime/entry.py'
                    if not exe.is_file() or not entry.is_file():raise ValueError('Set the external app folder in the addon preferences.')
                    (root/'logs').mkdir(exist_ok=True)
                    with (root/'logs/toyxyz_motion_ai_tool_app.log').open('ab') as log:
                        process=subprocess.Popen([str(exe),'-X','utf8','-u',str(entry),'bridge','--port',str(pref.port if pref else 8790),'--no-browser'],
                                                 cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                                                 creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
                    _launched_app=(base,process)
            client.state['app_running']=True
            return bpy.ops.toyxyz_motion_ai_tool.connect()
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class TOYXYZ_OT_browser(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.open_app';bl_label='App Dashboard'
    bl_description='Open the companion app dashboard in the browser'
    def execute(self,context):webbrowser.open(endpoint(context));return {'FINISHED'}


class TOYXYZ_OT_generate(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.generate';bl_label='Generate Motion'
    bl_description='Generate selected blocks and connect their motion to adjacent generated clips'
    def execute(self,context):
        try:
            rig_store.ensure(context.scene);rig_store.follow_selection(context)
            if client.state.get('stopping'):raise ValueError('Wait for the app to stop before generating.')
            if client.state['job_status'] in ('queued','running') or client.state.get('auto_apply_pending') or client.state.get('sequence') or client.state.get('pending_connect'):raise ValueError('Finish or cancel the active job first.')
            client.state.update(progress=None,job_progress=0)
            if not client.state['connected'] or client.state['scene_uid']!=settings(context).scene_uid:
                generation.connect_then_start(context)
            else:generation.start(context)
            return {'FINISHED'}
        except Exception as exc:
            client.state['message']=str(exc)
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class TOYXYZ_OT_control(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.app_control';bl_label='App Control'
    bl_description='Manage the companion app and its models'
    COMMANDS=(
        ('cancel','Cancel Job','Cancel generation or discard its pending result'),
        ('release','Release GPU','Unload the motion models and text encoders from GPU memory'),
        ('shutdown','Stop App','Stop the companion app and free its GPU memory'),
    )
    command:EnumProperty(items=COMMANDS)
    @classmethod
    def description(cls,context,properties):
        return next((help_text for command,_,help_text in cls.COMMANDS if command==properties.command),cls.bl_description)
    def execute(self,context):
        if self.command=='shutdown' and client.state.get('stopping'):return {'FINISHED'}
        if client.state.get('pending_connect'):
            client.state.update(pending_connect=None,job_status='cancelled',message='Pending generation cancelled.')
        if self.command in ('cancel','shutdown','release'):client.state['sequence']=None
        if self.command in ('cancel','shutdown'):
            state=client.state
            if state['job_status'] in ('connecting','queued','running') or state.get('auto_apply_pending') or (
                state['job_status']=='succeeded' and state.get('applied_job')!=state.get('job_id')
            ):
                state.update(cancel_requested=True,job_status='cancelled',auto_apply_pending=False,result=None,
                             progress=None,message='Generation cancelled.')
        if self.command=='shutdown':
            client.state.update(stopping=True,connecting=False,auto_apply_pending=False,progress=None,message='Stopping app...')
        client.send(self.command);return {'FINISHED'}


def validate_neighbor_samples(context,s,data,live,following):
    blocks=[dict(block) for block in data['blocks']]
    first,last=blocks[0],blocks[-1];obj=s.rig;engine=data['engine']
    check_previous=first.get('previous_motion_signature') or first.get('inherited_pose_signature')
    check_following=last.get('following_motion_signature')
    if not (check_previous or check_following):return
    with pose_preview.preserve_edit_state(context),control_layers.without_layers(context,obj,preserve_pose=True):
        if check_previous:
            from . import continuity
            block=live.get(first['uid'])
            message='The preceding motion or block timing changed. Generate again to join the updated clips.'
            if not block or not block.enabled or block.start!=first['start']:raise ValueError(message)
            if 'previous_motion_signature' in first:
                if 'requested_transition_frames' in first:
                    first['transition_frames']=first['requested_transition_frames']
                previous=kimodo_context.previous_motion(context,obj,blocks,history_frames=240 if engine=='ardy' else None)
                if kimodo_context.signature(previous)!=first['previous_motion_signature']:raise ValueError(message)
            if 'inherited_pose_signature' in first:
                previous=continuity.predecessor(obj,first['start'],{item['uid'] for item in blocks})
                if not previous:raise ValueError(message)
                with nla_motion.authoring(context,obj):
                    pose=keyframes.inherited_pose(context,obj,previous,first['start'],engine)
                if kimodo_context.signature(pose)!=first['inherited_pose_signature']:raise ValueError(message)
        if check_following:
            samples=kimodo_context.following_motion(context,obj,blocks,engine,following) if following else None
            if kimodo_context.signature(samples)!=check_following:
                raise ValueError('The following motion changed. Generate again to join the updated clips.')


def prepare_result(context):
    s=settings(context);data=client.state['result']
    if not data:raise ValueError('No completed result is available.')
    state=client.state
    if (rig_store.scene_for_job(state['scene_uid'],state.get('job_scene_session_uid'))!=context.scene
        or rig_store.job(context.scene,state['input_uuid'],state.get('job_rig_session_uid'))!=s
        or not s.rig):
        raise ValueError('The original scene or SOMA input rig is no longer available.')
    live=block_links.blocks(context.scene);valid=[]
    reference=data.get('next_motion_reference')
    following=None
    if reference:
        last=data['blocks'][-1];block=live.get(last['uid'])
        following=kimodo_context.following_clip(s.rig,s,data['blocks'])
        if (not block or (block.start,block.end)!=(last['start'],last['end']) or not following
            or kimodo_context.following_reference(following,data['blocks'],data['engine'])!=reference):
            raise ValueError('The following motion or block timing changed. Generate again to join the updated clips.')
    if data.get('blocks'):validate_neighbor_samples(context,s,data,live,following)
    submitted=[b for b in data.get('blocks',[]) if 'pose_keys_signature' in b and b.get('uid') in live]
    stamps=keyframes.value_signatures(s.rig,submitted) if submitted else {}
    for source in data.get('blocks',[]):
        block=live.get(source.get('uid'))
        if (block and block.enabled and 'foot_contact' not in source and block.engine==data['engine'] and block.prompt==source.get('prompt','')
            and (block.engine!='kimodo' or block.transition_frames==source.get('requested_transition_frames',source.get('transition_frames',5)))
            and ('constraint_types' not in source or pose_constraints.signature(s.rig,source['start'],source['end'])==source['constraint_types'])
            and ('pose_keys_signature' not in source or stamps.get(block.uid)==source['pose_keys_signature'])
            and object_constraints.matches(context,s,block,source)
            and curve_paths.matches(context.scene,block,source)):
            valid.append(source)
    return dict(data,blocks=valid) if valid else None


def auto_apply():
    state=client.state
    if state.get('cancel_requested') or not state.get('auto_apply_pending') or not state.get('result'):return
    if pose_edit.busy():state['message']='Finish moving pose keys to apply the generated motion.';return
    scene=rig_store.scene_for_job(state['scene_uid'],state.get('job_scene_session_uid'))
    if scene is None:
        state.update(auto_apply_pending=False,auto_apply_error=True,message='Automatic application failed: the original scene was removed.');return
    s=rig_store.job(scene,state['input_uuid'],state.get('job_rig_session_uid'))
    if s is None:
        state.update(auto_apply_pending=False,auto_apply_error=True,message='Automatic application failed: the original SOMA rig was removed.');return
    obj=s.rig
    if s.last_applied_job==state['result']['job_id']:
        state.update(auto_apply_pending=False,auto_apply_error=False,applied_job=s.last_applied_job,message='Generated motion applied.');return
    if not obj or obj.get('toyxyz_uuid')!=state['input_uuid']:
        state.update(auto_apply_pending=False,auto_apply_error=True,message='Automatic application failed: the original SOMA rig was removed.');return
    if obj.mode=='EDIT' or (obj.animation_data and obj.animation_data.use_tweak_mode):
        state['message']='Generation complete. Exit Edit/Tweak Mode to apply automatically.';return
    if pose_preview.interacting(bpy.context):
        state['message']='Generation complete. Finish the current edit to apply motion.';return
    if abs(scene.render.fps/scene.render.fps_base-state['result']['scene_fps'])>.001:
        state['message']='Restore the submitted scene FPS to apply automatically.';return
    try:
        view_layer=scene.view_layers.get(state.get('view_layer','')) or scene.view_layers[0]
        with rig_store.use(scene,s),bpy.context.temp_override(scene=scene,view_layer=view_layer):
            result=bpy.ops.toyxyz_motion_ai_tool.apply_result('EXEC_DEFAULT')
        if result!={'FINISHED'}:raise ValueError('The result could not be applied. See the Blender report.')
    except Exception as exc:
        state.update(auto_apply_pending=False,auto_apply_error=True,message='Automatic application failed: '+str(exc))


class TOYXYZ_OT_apply(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.apply_result';bl_label='Apply Generated Motion';bl_options={'REGISTER','UNDO'}
    bl_description='Apply the completed motion to the SOMA rig used for generation'
    def execute(self,context):
        owner=rig_store.job(context.scene,client.state.get('input_uuid',''),client.state.get('job_rig_session_uid'))
        if owner is not None:
            with rig_store.use(context.scene,owner):return self.apply_to_rig(context)
        return self.apply_to_rig(context)
    def apply_to_rig(self,context):
        try:
            if pose_edit.busy():raise ValueError('Finish moving pose keys before applying motion.')
            s=settings(context);data=prepare_result(context)
            if s.last_applied_job==client.state['result']['job_id']:
                client.state.update(auto_apply_pending=False,auto_apply_error=False);return {'FINISHED'}
            if data is not None:
                rig.import_result(context,s.rig,data)
            s.last_applied_job=client.state['result']['job_id'];client.state['applied_job']=s.last_applied_job
            client.state.update(auto_apply_pending=False,auto_apply_error=False,
                                message=('Generated motion applied. Removed or changed blocks were skipped.'
                                         if data and len(data['blocks'])<len(client.state['result']['blocks']) else
                                         'Generated motion applied.' if data else 'Generation finished. Removed or changed blocks were skipped.'))
            if data and client.state['result'].get('root_height_errors'):
                error=max(item['error_m'] for item in client.state['result']['root_height_errors'])
                client.state['message']+=f' Root height deviation: {error*100:.1f} cm.'
            keyframes.clear()
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


def status_lines(message,width):
    return [line for paragraph in str(message).splitlines() for line in textwrap.wrap(paragraph,width=max(16,width))]


def panel(layout,context):
    s=settings(context);state=client.state
    controls=layout.row(align=True);main=controls.row(align=True)
    main.enabled=not state.get('connecting') and not state.get('stopping')
    if state['connected'] or state.get('app_running'):
        main.operator('toyxyz_motion_ai_tool.app_control',text='Stop',icon='CANCEL').command='shutdown'
    else:main.operator('toyxyz_motion_ai_tool.launch_app',text='Start',icon='PLAY')
    reconnect=controls.row(align=True)
    reconnect.enabled=not (state.get('connecting') or state.get('stopping') or state.get('sequence') or state.get('pending_connect') or state.get('auto_apply_pending') or state['job_status'] in ('queued','running'))
    reconnect.operator('toyxyz_motion_ai_tool.connect',text='',icon='LINKED')
    layout.label(text='Connected' if state['connected'] else 'Disconnected',icon='CHECKMARK' if state['connected'] else 'UNLINKED')
    if state['connected'] and state.get('resident_motion'):
        motion=state['resident_motion'];label={'kimodo':'Kimodo','motionbricks':'MotionBricks','ardy':'ARDY'}[motion['engine']]
        layout.label(text='GPU Model: '+label,icon='INFO')
    rig_store.panel(layout,context)
    if state['job_status'] in ('queued','running','connecting') or state.get('sequence') or state.get('auto_apply_pending'):
        job_uuid=(state.get('pending_connect') or {}).get('rig_uuid') or state.get('input_uuid','')
        job_data=rig_store.job(context.scene,job_uuid)
        if job_data and job_data.rig!=s.rig:layout.label(text='Generating for: '+job_data.rig.name,icon='INFO')
    if s.rig:layout.prop(s,'show_soma_mesh')
    if s.rig:control_rig.panel(layout,context,s.rig)
    if s.rig:pose_preview.panel(layout,context)
    layout.operator('toyxyz_motion_ai_tool.open_timeline',icon='TIME')
    if s.rig and any(not strip.action.get(nla_motion.REQUEST) for _,strip in nla_motion.strips(s.rig)):
        layout.label(text='User Corrections · Combine',icon='KEY_HLT')
        layout.label(text='Pose and key over generated motion.')
    block=timeline.active(s)
    if block:
        box=layout.box();box.prop(block,'enabled');box.prop(block,'engine')
        if block.engine in ('kimodo','ardy'):
            box.prop(s,'precision');box.prop(block,'prompt');box.prop(block,'path_curve')
            if block.path_curve:box.prop(block,'path_start_percent')
            if block.engine=='kimodo':box.prop(block,'transition_frames')
        else:
            box.prop(block,'prompt',text='Notes')
            box.label(text='Pose targets only; notes are not model input.',icon='INFO')
            box.label(text='Target: the next generated clip or the last SOMA pose key.')
        try:
            _,blocks=timeline.generation_blocks(context)
            box.label(text=f'Selected: {len(blocks)} block(s)')
        except ValueError as exc:box.label(text=str(exc),icon='ERROR')
    else:layout.prop(s,'engine')
    layout.label(text='Motion blocks and NLA strips stay linked.',icon='INFO')
    layout.separator();layout.label(text='Unkeyed start continues previous motion.',icon='KEY_HLT')
    layout.label(text='Finger motion is keyed manually.',icon='INFO')
    advanced_header,advanced_body=layout.panel('toyxyz_motion_ai_advanced',default_closed=True)
    advanced_header.label(text='Advanced')
    if advanced_body:
        advanced_body.prop(s,'seed')
        model_settings=advanced_body.column();model_settings.enabled=current_engine(s) in ('kimodo','ardy')
        model_settings.prop(s,'ardy_steps' if current_engine(s)=='ardy' else 'steps');model_settings.prop(s,'postprocess')
        model_settings.prop(s,'text_weight');model_settings.prop(s,'constraint_weight')
        advanced_body.separator();advanced_body.label(text='Pose Target Display')
        for name in ('pose_targets_in_front','pose_target_line_width','pose_target_line_opacity','pose_target_size',
                     'pose_target_opacity','pose_target_axes','pose_target_labels'):
            advanced_body.prop(s,name)
    timeline.draw_motion_controls(layout,s)
    layout.operator('toyxyz_motion_ai_tool.export_soma',icon='EXPORT')
    agent_enabled=agent_bridge.enabled()
    layout.operator('toyxyz_motion_ai_tool.agent_bridge',text='Disable Agent Control' if agent_enabled else 'Enable Agent Control',
                    icon='LINKED' if agent_enabled else 'UNLINKED')
    if state.get('progress') is not None:
        layout.progress(factor=state['progress']/100,type='BAR',text=f'Generation {state["progress"]:.0f}%')
    width=int((getattr(context.region,'width',360) or 360)/(7*(context.preferences.system.ui_scale or 1)))-5
    for line in status_lines(state['message'],width):layout.label(text=line)
    if state.get('auto_apply_error'):layout.operator('toyxyz_motion_ai_tool.apply_result',text='Retry Motion Application',icon='FILE_REFRESH')
    layout.operator('toyxyz_motion_ai_tool.app_control',text='Release GPU').command='release'


class TOYXYZ_PT_view(bpy.types.Panel):
    bl_label='toyxyz_motion_ai_tool';bl_idname='TOYXYZ_PT_view';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Motion AI'
    def draw(self,context):panel(self.layout,context)


class TOYXYZ_PT_timeline(bpy.types.Panel):
    bl_label='toyxyz_motion_ai_tool';bl_idname='TOYXYZ_PT_timeline';bl_space_type='NODE_EDITOR';bl_region_type='UI';bl_category='Motion AI'
    @classmethod
    def poll(cls,context):return timeline.ours(context)
    def draw(self,context):
        object_constraints.draw_sidebar(self.layout,context)
        panel(self.layout,context)


_seen_timeline_areas=set()
_seen_pose_keys={}


def timer():
    legacy_controls.restore_tools()
    global _launched_app
    from .timeline import convert_editors
    convert_editors()
    for scene in bpy.data.scenes:
        legacy_scene.restore(scene)
        legacy_scene.restore_foot_curves(scene)
        rig_store.ensure(scene)
        window=bpy.context.window if bpy.context.window and bpy.context.window.scene==scene else next((w for w in bpy.context.window_manager.windows if w.scene==scene),None)
        if window:
            with bpy.context.temp_override(window=window):rig_store.follow_selection(bpy.context)
        s=rig_store.settings(scene)
        rig_store.sync(scene)
        if not pose_edit.busy():
            from . import correction_bounds
            for entry in rig_store.entries(scene):
                if entry.rig:correction_bounds.sync(scene,entry.rig)
        pointer=scene.as_pointer()
        markers=keyframes.markers(s.rig,force=True)
        keyframes.frames(s.rig,force=True,model_only=True)
        signature=tuple((f,selected,pose_constraints.label(s.rig,f)) for f,selected in markers)
        if _seen_pose_keys.get(pointer)!=signature:
            _seen_pose_keys[pointer]=signature
            timeline.redraw_regions(scene,bpy.context.window_manager.windows)
    pose_constraints.flush()
    visible=set()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='NODE_EDITOR' and area.ui_type==timeline.TREE:
                timeline.ensure_tree(window.scene)
                pointer=area.as_pointer();visible.add(pointer)
                if pointer not in _seen_timeline_areas:
                    region=next((r for r in area.regions if r.type=='UI'),None)
                    if region:
                        try:region.active_panel_category='Motion AI';_seen_timeline_areas.add(pointer)
                        except (AttributeError,TypeError,ValueError):pass
    _seen_timeline_areas.intersection_update(visible)
    dirty=False
    while True:
        try:kind,scene_uid,payload,*tokens=client.events.get_nowait()
        except client.queue.Empty:break
        if scene_uid!=client.state['scene_uid']:continue
        if tokens and tokens[0] is not None and tokens[0]!=client.submission_token:continue
        if kind in ('job','job_error','result') and client.state.get('cancel_requested'):continue
        dirty=True
        if kind=='health':
            capabilities=payload.get('capabilities',[])
            if not {'object_constraints','next_motion_context','atomic_cancel'}<=set(capabilities) and _launched_app and _launched_app[1].poll() is None:
                continue
            was_connected=client.state['connected']
            client.state.update(connected=True,app_running=True,connecting=False,connection_error='',instance=payload['instance'],resident_motion=payload.get('resident_motion'),encoder_precision=payload.get('encoder_precision'),capabilities=capabilities)
            if not was_connected and not client.state['job_status']:client.state['message']='Connected. Author motion blocks and key the SOMA bones.'
        elif kind=='released':client.state.update(resident_motion=None,encoder_precision=None,message='GPU models released. The next generation loads them again.')
        elif kind=='error':
            starting=bool(_launched_app and _launched_app[1].poll() is None)
            if client.state.get('pending_connect') or (client.state.get('connecting') and starting):
                client.state.update(connected=False,app_running=starting,connecting=True,connection_error=payload,
                                    message='Waiting for the companion app to start and connect...')
            else:client.state.update(connected=False,app_running=False,connecting=False,stopping=False,connection_error=payload,message=payload)
        elif kind=='stopped':
            client.stop();_launched_app=None
            client.state.update(connected=False,app_running=False,connecting=False,stopping=False,result=None,job_id='',job_status='',
                resident_motion=None,encoder_precision=None,sequence=None,pending_connect=None,auto_apply_pending=False,auto_apply_error=False,progress=None,message='App stopped.')
        elif kind=='job_error':client.state.update(job_status='failed',message=payload,progress=None)
        elif kind=='job':
            client.state.update(job_id=payload['id'],job_status=payload['status'],message=payload['message'])
            if payload['status'] in ('failed','cancelled'):client.state['progress']=None
            else:generation.update_progress(payload.get('progress',100 if payload['status']=='succeeded' else 0),payload['message'])
        elif kind=='result':
            client.state.update(result=payload,message='Applying generated motion...',job_status='succeeded',auto_apply_pending=True,auto_apply_error=False)
            generation.update_progress(100,'Applying generated motion')
        elif kind=='reset':client.state.update(result=None,job_id='',job_status='',message='The external app restarted.',auto_apply_pending=False,auto_apply_error=False,sequence=None,pending_connect=None,progress=None)
    editing=pose_preview.interacting(bpy.context)
    if not editing and generation.advance_connection():dirty=True
    if client.state.get('auto_apply_pending'):
        previous=(client.state['auto_apply_pending'],client.state['message'])
        auto_apply()
        dirty=dirty or previous!=(client.state['auto_apply_pending'],client.state['message'])
    if not editing and generation.advance():dirty=True
    if pose_preview.tick():dirty=True
    if dirty:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type=='VIEW_3D' or (area.type=='NODE_EDITOR' and area.ui_type==timeline.TREE):area.tag_redraw()
    agent_bridge.tick(bpy.context)
    return .2


@persistent
def on_load(_):
    agent_bridge.stop()
    pose_preview.clear()
    pose_edit.abandon()
    keyframes.clear();pose_constraints.clear();_seen_pose_keys.clear()
    client.stop();client.state.update(connected=False,app_running=False,connecting=False,stopping=False,result=None,job_id='',job_status='',scene_uid=None,message='Reconnect to the external app.',auto_apply_pending=False,auto_apply_error=False,sequence=None,pending_connect=None,progress=None,
                                      job_scene_session_uid=None,job_rig_session_uid=None,cancel_requested=False)
    for scene in bpy.data.scenes:
        legacy_scene.restore(scene);legacy_scene.restore_foot_curves(scene)
        rig_store.ensure(scene)


def menu(self,context):self.layout.operator('toyxyz_motion_ai_tool.open_timeline',icon='TIME')


CLASSES=pose_edit.CLASSES+control_rig.CLASSES+final_motion.CLASSES+agent_bridge.CLASSES+(TOYXYZ_Preferences,TOYXYZ_Prompt,TOYXYZ_Pose,object_constraints.TOYXYZ_ObjectConstraint,TOYXYZ_Settings,TOYXYZ_RigEntry,rig_store.TOYXYZ_UL_soma_rigs,object_constraints.TOYXYZ_UL_object_constraints,TOYXYZ_OT_open_timeline,TOYXYZ_OT_rig,TOYXYZ_OT_add_rig,TOYXYZ_OT_delete_rig,
         TOYXYZ_OT_block,TOYXYZ_OT_delete,TOYXYZ_OT_remove_block,TOYXYZ_OT_connect,TOYXYZ_OT_launch,
         TOYXYZ_OT_browser,TOYXYZ_OT_generate,TOYXYZ_OT_control,TOYXYZ_OT_apply,clear_motion.TOYXYZ_OT_clear_motion,TOYXYZ_PT_view,TOYXYZ_PT_timeline)


def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.toyxyz_motion_ai_tool=PointerProperty(type=TOYXYZ_Settings)
    bpy.types.Scene.toyxyz_motion_ai_rigs=CollectionProperty(type=TOYXYZ_RigEntry)
    block_links.register()
    pose_constraints.register()
    nla_motion.register()
    from . import timeline
    timeline.register()
    pose_preview.register()
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.timers.register(timer,persistent=True)


def unregister():
    agent_bridge.stop()
    client.stop()
    lifetime.close_all()
    pose_preview.unregister()
    pose_edit.cancel_live()
    for scene in bpy.data.scenes:
        context=bpy.context if bpy.context.scene==scene and bpy.context.screen else None
        for entry in rig_store.entries(scene):
            if control_layers.leave(entry.rig,context):
                entry.data.selection='BLOCK'
    nla_motion.unregister()
    block_links.unregister()
    pose_constraints.unregister()
    keyframes.clear();_seen_pose_keys.clear()
    if bpy.app.timers.is_registered(timer):bpy.app.timers.unregister(timer)
    if on_load in bpy.app.handlers.load_post:bpy.app.handlers.load_post.remove(on_load)
    from . import timeline
    timeline.unregister()
    del bpy.types.Scene.toyxyz_motion_ai_tool
    del bpy.types.Scene.toyxyz_motion_ai_rigs
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
