"""Block authoring surface; generated motion plays through native NLA."""
from . import rig_store
import time
import uuid
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty,EnumProperty,FloatProperty,IntProperty,StringProperty
from . import client,model_limits,timeline_style,block_links,control_layers,curve_paths,keyframes,pose_constraints,pose_edit,object_constraints

TREE='ToyxyzMotionAITimeline'
PROMPT_TOOLTIP='Describe the desired motion. MotionBricks keeps this as a note.'
PATH_TOOLTIP='Guide ground-plane travel. Adjacent blocks with the same model and curve share the path.'
PATH_START_TOOLTIP='When to reach the curve start. 0% is the first frame, 100% is the last.'
TRANSITION_TOOLTIP='Number of 30 FPS frames to use when joining motion at this Kimodo block. A shorter reference clip limits the overlap.'
_guard=False
_draw=None
_header=None
_keys=[]
BORDER=None
SELECT_BOX=None
_selection_guard=False


def ours(context):return context.area is not None and context.area.type=='NODE_EDITOR' and context.area.ui_type==TREE
def settings(context):return rig_store.settings(context.scene)
def fps(scene):return scene.render.fps/scene.render.fps_base
def active(s):return s.blocks[min(max(0,s.active_block),len(s.blocks)-1)] if s.blocks else None


def selected(s):return [b for b in s.blocks if b.selected]


def focus(s,index):
    global _selection_guard
    previous=_selection_guard;_selection_guard=True
    try:s.active_block=max(0,min(index,len(s.blocks)-1))
    finally:_selection_guard=previous


def selection_set(s,uids,active_index=None):
    global _selection_guard
    previous=_selection_guard;_selection_guard=True
    try:
        for block in s.blocks:block.selected=block.uid in uids
        s.block_selection_initialized=True
        if uids:
            indices=[i for i,b in enumerate(s.blocks) if b.selected]
            candidate=s.active_block if active_index is None else active_index
            if indices and candidate not in indices:active_index=indices[-1]
        if active_index is not None:focus(s,active_index)
    finally:_selection_guard=previous


def select(s,index,extend=False,toggle=False):
    ids={b.uid for b in selected(s)} if extend else set()
    block=s.blocks[index]
    if toggle and block.uid in ids:ids.remove(block.uid)
    else:ids.add(block.uid)
    selection_set(s,ids,index)


def ensure_selection(s):
    if s.blocks and not s.block_selection_initialized:select(s,min(max(0,s.active_block),len(s.blocks)-1))


def delete_target(context,requested='AUTO'):
    s=settings(context)
    if requested=='LAYER' or (requested=='AUTO' and s.selection=='LAYER'):
        return 'LAYER' if control_layers.editing(s.rig) else None
    if requested=='CONSTRAINT' or (requested=='AUTO' and s.selection=='CONSTRAINT'):
        return 'CONSTRAINT' if object_constraints.active(s) is not None else None
    if requested!='AUTO':return requested
    has_blocks=bool(selected(s))
    if s.selection=='BLOCK' and has_blocks:return 'BLOCK'
    if pose_edit.selected(s.rig):return 'POSE'
    if has_blocks:return 'BLOCK'
    return None


def set_range(block,start,end):
    global _guard
    previous=_guard;_guard=True
    try:block.start=round(start);block.end=round(end)
    finally:_guard=previous
    if not previous and not rig_store._guard:
        with rig_store.use(block.id_data,rig_store.owner(block)):block_links.push(block.id_data,block.uid)


def limit(block,side='END'):
    if _guard or rig_store._guard:return
    duration=model_limits.clamp(block.engine,fps(block.id_data),block.end-block.start)
    if side=='START':set_range(block,block.end-duration,block.end)
    else:set_range(block,block.start,block.start+duration)


def add(scene):
    s=rig_store.settings(scene);chosen=active(s);engine=chosen.engine if chosen else s.engine
    start=max((b.end for b in s.blocks),default=scene.frame_current)
    length=model_limits.clamp(engine,fps(scene),round(2*fps(scene)))
    block=s.blocks.add();block.uid=uuid.uuid4().hex;block.engine=engine
    set_range(block,start,start+length);block.name='Motion '+str(len(s.blocks));select(s,len(s.blocks)-1)
    return block


def generation_blocks(context):
    s=settings(context);ensure_selection(s)
    chosen=sorted(selected(s),key=lambda b:(b.start,b.end))
    if not chosen:raise ValueError('Select one or more motion blocks.')
    if any(not b.enabled for b in chosen):raise ValueError('Enable every selected motion block before generating.')
    engine=chosen[0].engine
    if any(b.engine!=engine for b in chosen):engine='mixed'
    if any(a.end!=b.start for a,b in zip(chosen,chosen[1:])):raise ValueError('Selected blocks must touch, without gaps or overlaps.')
    if len(chosen)>32 or (engine!='ardy' and (chosen[-1].end-chosen[0].start)/fps(context.scene)>60):raise ValueError('Select at most 32 blocks; non-ARDY selections may span at most 60 seconds.')
    candidates=[b for b in s.blocks if b.enabled]
    for block in chosen:
        low,high=model_limits.frames(block.engine,fps(context.scene))
        if not low<=block.end-block.start<=high:raise ValueError(f'{block.name}: length must be {low}–{high} frames.')
        if any(other!=block and other.start<block.end and other.end>block.start for other in candidates):
            raise ValueError('Separate overlapping motion blocks before generating.')
    return engine,[dict(start=b.start,end=b.end,prompt=b.prompt,name=b.name,uid=b.uid,engine=b.engine,transition_frames=b.transition_frames,
                        constraint_types=pose_constraints.signature(s.rig,b.start,b.end),
                        object_constraint_definitions=[list(m) for m in object_constraints.definitions(s,b.start,b.end)],
                        path_curve=b.path_curve.name_full if b.engine in ('kimodo','ardy') and b.path_curve else '') for b in chosen]


def migrate_blocks(scene):
    """Import v0.5 requests once; preserve generated and user-keyed Actions."""
    from . import nla_motion,legacy_scene
    legacy_scene.restore_foot_curves(scene)
    s=rig_store.settings(scene)
    ensure_selection(s)
    if s.timeline_migrated:return
    obj=s.rig
    if obj is None and not s.blocks:return
    for block in s.blocks:
        if not block.uid:block.uid=uuid.uuid4().hex
    items=nla_motion.strips(obj)
    requests=[(track,strip) for track,strip in items if strip.action.get(nla_motion.REQUEST)]
    sources=requests
    if not sources and not s.blocks and items:
        chosen=nla_motion.selected(obj);track=chosen[0] if chosen else items[-1][0]
        sources=[item for item in items if item[0]==track]
    by_uid={b.uid:b for b in s.blocks}
    for _,strip in sources:
        action=strip.action;engine=action.get(nla_motion.ENGINE)
        if engine not in model_limits.LIMITS:continue
        uid=action.get('toyxyz_block_uid') or uuid.uuid4().hex;block=by_uid.get(uid)
        if block is None:block=s.blocks.add();by_uid[uid]=block
        block.uid=uid;block.engine=engine;block.name=strip.name;block.prompt=action.get(nla_motion.PROMPT,'')
        set_range(block,strip.frame_start,strip.frame_end);limit(block)
    for track,strip in requests:
        if not nla_motion.has_keys(strip.action):
            track.strips.remove(strip)
            if not track.strips:obj.animation_data.nla_tracks.remove(track)
    s.timeline_migrated=True
    ensure_selection(s)


class TOYXYZ_TimelineTree(bpy.types.NodeTree):
    bl_idname=TREE;bl_label='toyxyz_motion_ai_tool';bl_icon='TIME'
    @classmethod
    def poll(cls,context):return True
    @classmethod
    def get_from_context(cls,context):return rig_store.master(context.scene).timeline_tree,context.scene,context.scene


def ensure_tree(scene):
    s=rig_store.master(scene)
    if not s.timeline_tree:s.timeline_tree=bpy.data.node_groups.new('toyxyz_motion_ai_tool',TREE)
    return s.timeline_tree


def convert_editors():pass  # Saved custom editors remain custom; native NLA is untouched.


def metrics(context):return timeline_style.metrics(context)


def frame_at(context,x):
    s=settings(context);return s.view_start+(x-metrics(context)['gutter'])/s.pixels_per_frame


def zoom_at_pointer(context,factor,x=None):
    s=settings(context);m=metrics(context);width=max(1,context.region.width-m['gutter'])
    anchor=max(0,min(width,x-m['gutter'])) if x is not None and context.preferences.inputs.use_zoom_to_mouse else width/2
    frame=s.view_start+anchor/s.pixels_per_frame
    s.pixels_per_frame=max(.15,min(80,s.pixels_per_frame*factor));s.view_start=frame-anchor/s.pixels_per_frame
    context.area.tag_redraw()


def drag_zoom_fraction(context,previous,current):
    pref=context.preferences.inputs
    if pref.view_zoom_method=='SCALE':
        center=context.region.width/2;delta=abs(current-center)-abs(previous-center)
    else:delta=current-previous
    return delta*.01/metrics(context)['scale']*(-1 if pref.invert_mouse_zoom else 1)


class TimelineOperator:
    @classmethod
    def poll(cls,context):return ours(context)


class TOYXYZ_OT_zoom(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_zoom';bl_label='Zoom Timeline'
    bl_description='Change the horizontal zoom of the motion timeline'
    direction:IntProperty(default=1);pan:BoolProperty(default=False)
    def invoke(self,context,event):
        direction=self.direction
        if event.type in ('WHEELINMOUSE','WHEELOUTMOUSE') and event.is_direction_inverted:direction=-direction
        return self.run(context,direction,event.mouse_region_x)
    def run(self,context,direction,x=None):
        if self.pan:settings(context).view_start+=direction*40*metrics(context)['scale']/settings(context).pixels_per_frame
        else:zoom_at_pointer(context,(1/.925)**direction,x)
        context.area.tag_redraw();return {'FINISHED'}
    def execute(self,context):return self.run(context,self.direction)


class TOYXYZ_OT_navigate(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_navigate';bl_label='Navigate Timeline';bl_options={'BLOCKING'}
    bl_description='Pan or zoom the motion timeline'
    mode:EnumProperty(items=[('PAN','Pan',''),('ZOOM','Zoom','')],default='PAN')
    def invoke(self,context,event):
        self.mouse_x=event.mouse_region_x;self.previous=self.mouse_x;self.anchor=self.mouse_x;self.timer=None;self.last_time=time.monotonic()
        self.previous_y=getattr(event,'mouse_region_y',0)
        if event.type in ('TRACKPADPAN','TRACKPADZOOM'):
            delta=event.mouse_x-event.mouse_prev_x
            if self.mode=='PAN':
                settings(context).view_start-=delta/settings(context).pixels_per_frame
                pan_rows(context,getattr(event,'mouse_y',0)-getattr(event,'mouse_prev_y',0))
            else:zoom_at_pointer(context,1/max(.05,1-2*drag_zoom_fraction(context,0,delta)),self.anchor)
            context.area.tag_redraw();return {'FINISHED'}
        if self.mode=='ZOOM' and context.preferences.inputs.view_zoom_method=='CONTINUE':
            self.timer=context.window_manager.event_timer_add(.01,window=context.window)
        context.window.cursor_modal_set('SCROLL_X');context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def finish(self,context):
        if self.timer:context.window_manager.event_timer_remove(self.timer);self.timer=None
        context.window.cursor_modal_restore();return {'FINISHED'}
    def cancel(self,context):self.finish(context)
    def modal(self,context,event):
        if event.type in ('ESC','RIGHTMOUSE') or (event.type=='MIDDLEMOUSE' and event.value=='RELEASE'):return self.finish(context)
        if event.type=='MOUSEMOVE':
            self.mouse_x=event.mouse_region_x
            if self.mode=='PAN':
                settings(context).view_start-=(self.mouse_x-self.previous)/settings(context).pixels_per_frame
                mouse_y=getattr(event,'mouse_region_y',0)
                pan_rows(context,mouse_y-self.previous_y)
                self.previous_y=mouse_y
            elif not self.timer:zoom_at_pointer(context,1/max(.05,1-2*drag_zoom_fraction(context,self.previous,self.mouse_x)),self.anchor)
            self.previous=self.mouse_x;context.area.tag_redraw()
        if event.type=='TIMER' and self.timer and event.timer==self.timer:
            now=time.monotonic();fraction=drag_zoom_fraction(context,self.anchor,self.mouse_x)*5*(now-self.last_time);self.last_time=now
            zoom_at_pointer(context,1/max(.05,1-2*fraction),self.anchor)
        return {'RUNNING_MODAL'}


def pan_rows(context,delta):
    if not delta:return
    _,_,offset,limit=timeline_style.lane_layout(context)
    if limit:settings(context).timeline_lane_scroll=max(0,min(limit,offset+delta/metrics(context)['row']))


class TOYXYZ_OT_frame(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_frame';bl_label='Frame Timeline Items'
    bl_description='Fit motion timeline items in view'
    selected:BoolProperty(default=False);current:BoolProperty(default=False)
    @classmethod
    def description(cls,context,properties):
        if properties.current:return 'Center the view on the playhead.'
        if properties.selected:return 'Fit the selected timeline items in view.'
        return cls.bl_description
    def execute(self,context):
        s=settings(context);width=max(1,context.region.width-metrics(context)['gutter'])
        if self.current:s.view_start=context.scene.frame_current-width/(2*s.pixels_per_frame)
        else:
            if s.selection=='LAYER' and self.selected:
                item=control_layers.editing(s.rig)
                if not item:return {'CANCELLED'}
                start,end=item[1].frame_start,item[1].frame_end
            elif s.selection=='CONSTRAINT' and self.selected:
                marker=object_constraints.active(s)
                if marker is None:return {'CANCELLED'}
                start=end=marker.frame
            elif s.selection=='POSE':
                values=pose_edit.selected(s.rig) if self.selected else keyframes.frames(s.rig)
                if self.selected and not values:return {'CANCELLED'}
                start=min(values,default=context.scene.frame_start);end=max(values,default=context.scene.frame_end)
            else:
                blocks=selected(s) if self.selected else list(s.blocks)
                if self.selected and not blocks:return {'CANCELLED'}
                start=min((b.start for b in blocks),default=context.scene.frame_start);end=max((b.end for b in blocks),default=context.scene.frame_end)
            if not self.selected and s.object_constraints:
                start=min(start,*(m.frame for m in s.object_constraints));end=max(end,*(m.frame for m in s.object_constraints))
            if not self.selected:
                for _,strip in control_layers.rows(s.rig):
                    start=min(start,strip.frame_start);end=max(end,strip.frame_end)
            margin=max(4,(end-start)*.08);s.pixels_per_frame=width/max(1,end-start+2*margin);s.view_start=start-margin
        context.area.tag_redraw();return {'FINISHED'}


def match_native_view(context):
    """Copy a native Timeline view once; subsequent navigation remains independent."""
    for area in context.screen.areas:
        if area==context.area or area.type!='DOPESHEET_EDITOR' or area.spaces.active.mode!='TIMELINE':continue
        region=next((r for r in area.regions if r.type=='WINDOW' and r.width>1),None)
        if region is None:continue
        left=region.view2d.region_to_view(0,0)[0];right=region.view2d.region_to_view(region.width-1,0)[0]
        if right<=left:continue
        s=settings(context);s.pixels_per_frame=(region.width-1)/(right-left);s.view_start=left
        context.area.tag_redraw();return True
    return False


class TOYXYZ_OT_match_native(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_match_native';bl_label='Match Blender Timeline'
    bl_description='Match the visible native Timeline start and zoom for a direct comparison'
    def execute(self,context):
        if not match_native_view(context):
            self.report({'INFO'},'Keep a native Blender Timeline open in the same window.');return {'CANCELLED'}
        return {'FINISHED'}


class TOYXYZ_OT_prompt(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.edit_prompt';bl_label='Edit Motion Block';bl_options={'UNDO'}
    bl_description='Edit the active block’s prompt, notes or path settings'
    prompt:StringProperty(name='Prompt',description=PROMPT_TOOLTIP)
    curve_name:StringProperty(name='Path Curve',description=PATH_TOOLTIP,search=curve_paths.search)
    path_start_percent:FloatProperty(name='Curve Start (%)',min=0,max=100,precision=1,step=100,
        description=PATH_START_TOOLTIP)
    transition_frames:IntProperty(name='Transition Overlap (30 FPS)',default=5,min=1,max=300,soft_max=30,
        description=TRANSITION_TOOLTIP)
    def invoke(self,context,event):
        block=active(settings(context))
        if block is None:return {'CANCELLED'}
        self.prompt=block.prompt
        curve=block.path_curve
        self.curve_name=curve.name_full if curve else ''
        self.path_start_percent=block.path_start_percent
        self.transition_frames=block.transition_frames
        return context.window_manager.invoke_props_dialog(self,width=560)
    def draw(self,context):
        block=active(settings(context))
        self.layout.prop(self,'prompt',text='Notes' if block.engine=='motionbricks' else 'Prompt')
        if block.engine in ('kimodo','ardy'):self.layout.prop(self,'curve_name',icon='CURVE_DATA')
        if block.engine in ('kimodo','ardy') and self.curve_name:self.layout.prop(self,'path_start_percent')
        if block.engine=='kimodo':self.layout.prop(self,'transition_frames')
        if block.engine=='motionbricks':self.layout.label(text='MotionBricks uses pose targets; notes are not model input.')
    def execute(self,context):
        block=active(settings(context))
        if block is None:return {'CANCELLED'}
        if block.engine in ('kimodo','ardy'):
            name=getattr(self,'curve_name','');curve=next((o for o in context.scene.objects if o.type=='CURVE' and o.name_full==name),None)
            if name and curve is None:
                self.report({'ERROR'},'Choose a Path Curve from this scene.');return {'CANCELLED'}
            block.path_curve=curve
            block.path_start_percent=getattr(self,'path_start_percent',block.path_start_percent)
            block.transition_frames=getattr(self,'transition_frames',block.transition_frames)
        block.prompt=self.prompt;return {'FINISHED'}


def motion_top(context,m):
    layers,top,_,_=timeline_style.lane_layout(context)
    return top-len(layers)*m['row']


def hit(context,x,y):
    m=metrics(context);lane=int((motion_top(context,m)-y)//m['row'])
    if x<m['gutter'] or y>=context.region.height-m['ruler'] or lane!=0:return None
    frame=frame_at(context,x);s=settings(context)
    indices=list(reversed(range(len(s.blocks))))
    if s.blocks and 0<=s.active_block<len(s.blocks):indices.remove(s.active_block);indices.insert(0,s.active_block)
    for index in indices:
        b=s.blocks[index]
        if b.start-5/s.pixels_per_frame<=frame<=b.end+5/s.pixels_per_frame:
            side='START' if abs(frame-b.start)*s.pixels_per_frame<7*m['scale'] else 'END' if abs(frame-b.end)*s.pixels_per_frame<7*m['scale'] else 'MOVE'
            return index,side
    return None


def block_rect(context,block):
    m=metrics(context);s=settings(context)
    top=motion_top(context,m);y=top-m['row']
    return (m['gutter']+(block.start-s.view_start)*s.pixels_per_frame,y+2*m['scale'],
            m['gutter']+(block.end-s.view_start)*s.pixels_per_frame,y+m['row']-2*m['scale'])


def keyframe_hit(context,x,y):
    m=metrics(context);top=motion_top(context,m);center=top-1.5*m['row'];s=settings(context)
    if x<m['gutter'] or y>=context.region.height-m['ruler'] or abs(y-center)>8*m['scale']:return None
    values=keyframes.frames(s.rig)
    if not values:return None
    frame=min(values,key=lambda f:abs(m['gutter']+(f-s.view_start)*s.pixels_per_frame-x))
    return frame if abs(m['gutter']+(frame-s.view_start)*s.pixels_per_frame-x)<=8*m['scale'] else None


def row_at(context,y):
    m=metrics(context)
    if not m['scroll']<=y<context.region.height-m['ruler']:return None
    top=motion_top(context,m);lane=int((top-y)//m['row'])
    if lane==1 and abs(y-(top-1.5*m['row']))>m['row']/2-2*m['scale']:return None
    return ('BLOCK','POSE','CONSTRAINT')[lane] if 0<=lane<3 else None


def layer_hit(context,x,y):
    m=metrics(context)
    if not m['scroll']<=y<context.region.height-m['ruler']:return None
    layers,top,_,_=timeline_style.lane_layout(context)
    lane=int((top-y)//m['row'])
    if not 0<=lane<len(layers):return None
    item=layers[lane]
    if x<m['gutter']:
        return item,x>=m['gutter']-28*m['scale'],'LAYER_MOVE'
    frame=frame_at(context,x);strip=item[1]
    if strip.frame_start-5/settings(context).pixels_per_frame<=frame<=strip.frame_end+5/settings(context).pixels_per_frame:
        edge=min(('START','END'),key=lambda side:abs(frame-(strip.frame_start if side=='START' else strip.frame_end)))
        distance=abs(frame-(strip.frame_start if edge=='START' else strip.frame_end))*settings(context).pixels_per_frame
        mode='LAYER_'+edge if distance<7*m['scale'] else 'LAYER_MOVE'
        return item,False,mode
    return None


class TOYXYZ_OT_add_control_layer(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.add_control_layer'
    bl_label='Add Control Layer'
    bl_description='Add a keyable correction layer above the selected motion range'
    bl_options={'UNDO'}

    @classmethod
    def poll(cls,context):
        return ours(context) and settings(context).rig is not None

    def execute(self,context):
        s=settings(context);blocks=selected(s)
        start=context.scene.frame_current
        end=start+max(1,round(2*fps(context.scene)))
        if blocks:
            start=min(block.start for block in blocks);end=max(block.end for block in blocks)
        try:
            control_layers.add(context,s,start,end)
        except ValueError as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        s.timeline_lane_scroll=0
        if not start<=context.scene.frame_current<=end:
            context.scene.frame_set(start)
        return {'FINISHED'}


class TOYXYZ_OT_toggle_control_layer(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.toggle_control_layer'
    bl_label='Toggle Control Layer'
    bl_description='Enable or mute the selected layer during playback'
    bl_options={'UNDO'}

    @classmethod
    def poll(cls,context):
        return ours(context) and control_layers.editing(settings(context).rig) is not None

    def execute(self,context):
        s=settings(context)
        control_layers.toggle(context,s,control_layers.editing(s.rig))
        return {'FINISHED'}


def constraint_hits(context,x):
    s=settings(context);m=metrics(context)
    if x<m['gutter'] or not s.object_constraints:return []
    clicked=frame_at(context,x)
    frame=min((marker.frame for marker in s.object_constraints),key=lambda f:abs(f-clicked))
    if abs(frame-clicked)*s.pixels_per_frame>8*m['scale']:return []
    return [i for i,marker in enumerate(s.object_constraints) if marker.frame==frame]


class TOYXYZ_OT_add_object_constraint(TimelineOperator,bpy.types.Operator):
    bl_description='Add a marker at the playhead that takes its target from an object'
    bl_idname='toyxyz_motion_ai_tool.add_object_constraint';bl_label='Add Constraint';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):return ours(context) and settings(context).rig is not None
    def execute(self,context):
        s=settings(context);frame=context.scene.frame_current
        used={marker.kind for marker in s.object_constraints if marker.frame==frame}
        kind=next((item[0] for item in object_constraints.ITEMS if item[0] not in used),None)
        if kind is None:
            self.report({'WARNING'},'This frame already has all object constraint types.');return {'CANCELLED'}
        marker=s.object_constraints.add();marker.frame=frame;marker.kind=kind
        object_constraints.select(s,len(s.object_constraints)-1)
        context.space_data.show_region_ui=True
        object_constraints.changed(None,context)
        return {'FINISHED'}


def pose_box_hits(context,rectangle):
    x1,y1,x2,y2=rectangle;left,right=sorted((x1,x2));bottom,top=sorted((y1,y2))
    m=metrics(context);s=settings(context);center=motion_top(context,m)-1.5*m['row'];radius=5*m['scale']
    if not m['scroll']<=center<context.region.height-m['ruler']:return set()
    if top<center-radius or bottom>center+radius:return set()
    left=max(left,m['gutter'])
    return {frame for frame in keyframes.frames(s.rig) if left-radius<=m['gutter']+(frame-s.view_start)*s.pixels_per_frame<=right+radius}


class TOYXYZ_OT_constraint_type(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.constraint_type';bl_label='Set Pose Constraint Type';bl_options={'REGISTER','UNDO'}
    bl_description='Choose which part of the keyed pose guides generation'
    frame:FloatProperty(name='Frame',description='Frame of the pose key to edit')
    kind:EnumProperty(name='Constraint Type',description='Part of the keyed pose used as a target',items=pose_constraints.ITEMS)
    def execute(self,context):
        try:pose_constraints.set_kind(settings(context).rig,self.frame,self.kind)
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        redraw_regions(context.scene,context.window_manager.windows);return {'FINISHED'}


class TOYXYZ_OT_constraint_menu(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.constraint_menu';bl_label='Pose Constraint Types';bl_options={'REGISTER','UNDO'}
    bl_description='Choose one or more constraints for this pose key'
    frame:FloatProperty(name='Frame')
    root_heading:BoolProperty(name='Constrain Root Heading',default=False,
        description='Also constrain the keyed facing direction when Root Position (2D) is selected')
    root_height:BoolProperty(name='Constrain Root Height',default=False,
        description='Use the keyed hips height as a soft model goal; accuracy varies')
    kinds:EnumProperty(name='Constraint Types',description='Parts of the keyed pose to use as model targets',items=pose_constraints.FLAGS,options={'ENUM_FLAG'},
        get=pose_constraints.dialog_get,set=pose_constraints.dialog_set)
    def invoke(self,context,event):
        frame=keyframe_hit(context,event.mouse_region_x,event.mouse_region_y)
        s=settings(context)
        if frame not in keyframes.frames(s.rig,model_only=True):return {'CANCELLED'}
        control_layers.deselect(context,s)
        s.selection='POSE';pose_edit.select(s.rig,{frame})
        self.frame=frame;self.kinds=set(pose_constraints.kinds(s.rig,frame))
        self.root_heading=pose_constraints.uses_heading(s.rig,frame)
        self.root_height=pose_constraints.uses_height(s.rig,frame)
        return context.window_manager.invoke_props_dialog(self,width=300)
    def draw(self,context):
        self.layout.label(text=f'Keyframe {self.frame:g}')
        pose_constraints.draw_options(self.layout,self,'kinds')
    def execute(self,context):
        try:pose_constraints.set_kind(settings(context).rig,self.frame,pose_constraints.with_options(self.kinds,self.root_heading,self.root_height))
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        redraw_regions(context.scene,context.window_manager.windows)
        return {'FINISHED'}


def box_hits(context,rectangle):
    x1,y1,x2,y2=rectangle;left,right=sorted((x1,x2));bottom,top=sorted((y1,y2))
    m=metrics(context);left=max(left,m['gutter']);right=min(right,context.region.width)
    bottom=max(bottom,m['scroll']);top=min(top,context.region.height-m['ruler'])
    if right<=left or top<=bottom:return set()
    return {b.uid for b in settings(context).blocks for x,y,r,t in [block_rect(context,b)] if x<right and r>left and y<top and t>bottom}


def set_ranges(scene,ranges):
    with block_links.transaction(scene):
        blocks={b.uid:b for b in rig_store.settings(scene).blocks}
        moving=[uid for uid in ranges if uid in blocks]
        right=sum(ranges[uid][0]-blocks[uid].start for uid in moving)>0
        moving.sort(key=lambda uid:blocks[uid].start,reverse=right)
        for uid,(start,end) in ranges.items():
            if uid in blocks:set_range(blocks[uid],start,end)
        # Make room at the leading edge first; native NLA otherwise clamps an
        # earlier strip against its still-unmoved neighbor during a group drag.
        obj=rig_store.settings(scene).rig
        if not (obj and obj.animation_data and obj.animation_data.use_tweak_mode):
            for uid in moving:block_links.push_range(scene,blocks[uid])


def clear_select_box(context):
    global SELECT_BOX
    SELECT_BOX=None;context.area.tag_redraw()


class TOYXYZ_OT_edit(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_edit';bl_label='Select or Move Timeline Items';bl_options={'UNDO','BLOCKING'}
    bl_description='Select, move or resize motion blocks and control layers, or edit pose keys and markers'
    box:BoolProperty(default=False,options={'HIDDEN'})
    def invoke(self,context,event):
        s=settings(context);ensure_selection(s)
        self.before_domain=s.selection;self.pose_move=None;self.before_pose_selection=None
        self.before_selection={b.uid for b in selected(s)};self.before_active=s.active_block
        self.dragged=False;self.ranges={};self.collapse=False
        self.extend=getattr(event,'shift',False);self.subtract=getattr(event,'ctrl',False)
        self.x=event.mouse_region_x;self.y=event.mouse_region_y
        row=row_at(context,self.y)
        layer=layer_hit(context,self.x,self.y) if not getattr(self,'box',False) else None
        if layer:
            if event.value=='DOUBLE_CLICK':return {'CANCELLED'}
            self.layer,hit_toggle,self.mode=layer
            if hit_toggle:
                control_layers.toggle(context,s,self.layer);return {'FINISHED'}
            self.layer_rig=s.rig
            strip=self.layer[1];self.original=(strip.frame_start,strip.frame_end)
            self.layer_source=(strip.action_frame_start,strip.scale,strip.frame_start)
            context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
        self.pose_domain=row=='POSE' or (row is None and s.selection=='POSE')
        if row=='CONSTRAINT' and not getattr(self,'box',False) and self.y>=metrics(context)['scroll']:
            control_layers.deselect(context,s)
            indices=constraint_hits(context,self.x)
            self.before_constraint=s.active_object_constraint
            if not indices:
                object_constraints.select(s,-1);context.area.tag_redraw();return {'FINISHED'}
            index=self.before_constraint if self.before_constraint in indices else indices[0]
            object_constraints.select(s,index)
            self.constraint_marker=s.object_constraints[index];self.original=(self.constraint_marker.frame,)
            self.mode='CONSTRAINT_MOVE'
            context.area.tag_redraw();context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
        if getattr(self,'box',False):
            control_layers.deselect(context,s)
            if self.pose_domain:
                s.selection='POSE';self.before_pose_selection=pose_edit.selection_snapshot(s.rig);self.before_poses=pose_edit.selected(s.rig)
            else:s.selection='BLOCK'
            self.index=-1;self.mode='BOX';self.anchor=False
            context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
        if event.mouse_region_y<metrics(context)['scroll']:
            bpy.ops.toyxyz_motion_ai_tool.timeline_scroll('INVOKE_DEFAULT')
            return {'CANCELLED'}
        frame=keyframe_hit(context,self.x,self.y)
        if frame is not None:
            control_layers.deselect(context,s)
            self.before_pose_selection=pose_edit.selection_snapshot(s.rig);self.before_poses=pose_edit.selected(s.rig)
            s.selection='POSE';self.pose_domain=True
            if self.extend or self.subtract:
                chosen=self.before_poses-{frame} if self.subtract else self.before_poses^{frame}
                pose_edit.select(s.rig,chosen);context.area.tag_redraw();return {'FINISHED'}
            self.collapse=frame in self.before_poses and len(self.before_poses)>1
            if frame not in self.before_poses:pose_edit.select(s.rig,{frame})
            self.pose_frame=frame;self.index=-1;self.mode='POSE_MOVE'
            try:self.pose_move=pose_edit.Move(context,s.rig,pose_edit.selected(s.rig))
            except ValueError as exc:
                pose_edit.restore_selection(s.rig,self.before_pose_selection);s.selection=self.before_domain
                self.report({'ERROR'},str(exc));return {'CANCELLED'}
            context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
        found=hit(context,event.mouse_region_x,event.mouse_region_y);s=settings(context)
        if event.value=='DOUBLE_CLICK':
            if found:
                control_layers.deselect(context,s)
                select(s,found[0]);bpy.ops.toyxyz_motion_ai_tool.edit_prompt('INVOKE_DEFAULT')
            return {'CANCELLED'}
        self.index,self.mode=found if found else (-1,'SCRUB' if self.y>=context.region.height-metrics(context)['ruler'] else 'BOX')
        if found:
            control_layers.deselect(context,s)
            s.selection='BLOCK';self.pose_domain=False
            if self.extend or self.subtract:
                select(s,self.index,extend=True,toggle=True);context.area.tag_redraw();return {'FINISHED'}
            b=s.blocks[self.index];self.collapse=b.selected and len(selected(s))>1
            if not b.selected:select(s,self.index)
            else:focus(s,self.index)
            self.original=(b.start,b.end)
            self.ranges={other.uid:(other.start,other.end) for other in selected(s)} if self.mode=='MOVE' else {b.uid:self.original}
        elif self.mode=='SCRUB':self.original=(context.scene.frame_current,);self.update(context,event)
        else:
            self.anchor=True
            if self.pose_domain:
                self.before_pose_selection=pose_edit.selection_snapshot(s.rig);self.before_poses=pose_edit.selected(s.rig);s.selection='POSE'
                if not self.extend and not self.subtract:pose_edit.select(s.rig,set())
            else:
                control_layers.deselect(context,s)
                s.selection='BLOCK'
                if not self.extend and not self.subtract:selection_set(s,set())
        context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def update(self,context,event):
        global SELECT_BOX
        s=settings(context)
        if self.mode=='SCRUB':context.scene.frame_set(round(frame_at(context,event.mouse_region_x)));return
        if self.mode.startswith('LAYER_'):
            distance=event.mouse_region_x-self.x
            if not self.dragged and abs(distance)<3*metrics(context)['scale']:return
            self.dragged=True;delta=round(distance/s.pixels_per_frame)
            start,end=self.original
            if self.mode=='LAYER_MOVE':
                control_layers.place(self.layer[1],start+delta,end+delta)
            else:
                if self.mode=='LAYER_START':start=min(end-1,start+delta)
                else:end=max(start+1,end+delta)
                control_layers.resize(self.layer[1],start,end,*self.layer_source)
            context.area.tag_redraw();return
        if self.mode=='CONSTRAINT_MOVE':
            if not self.dragged and abs(event.mouse_region_x-self.x)<3*metrics(context)['scale']:return
            self.dragged=True
            self.constraint_marker.frame=self.original[0]+round((event.mouse_region_x-self.x)/s.pixels_per_frame)
            return
        if self.mode=='POSE_MOVE':
            if not self.dragged and abs(event.mouse_region_x-self.x)<3*metrics(context)['scale']:return
            self.dragged=True;delta=round((event.mouse_region_x-self.x)/s.pixels_per_frame)
            self.pose_move.preview(delta)
            pose_edit.header(context,self.pose_move.error or f'Move Pose Keys · {delta:+d} frames · Release: confirm · Esc: cancel')
            return
        if self.mode=='BOX':
            if not self.anchor:return
            self.dragged=self.dragged or max(abs(event.mouse_region_x-self.x),abs(event.mouse_region_y-self.y))>3*metrics(context)['scale']
            if not self.dragged:return
            rectangle=(self.x,self.y,event.mouse_region_x,event.mouse_region_y)
            if self.pose_domain:
                hits=pose_box_hits(context,rectangle)
                chosen=self.before_poses-hits if self.subtract else self.before_poses|hits if self.extend else hits
                pose_edit.select(s.rig,chosen);SELECT_BOX=(context.area.as_pointer(),rectangle);context.area.tag_redraw();return
            hits=box_hits(context,rectangle)
            ids=self.before_selection-hits if self.subtract else self.before_selection|hits if self.extend else hits
            indices=[i for i,b in enumerate(s.blocks) if b.uid in ids]
            selection_set(s,ids,s.active_block if s.active_block in indices else indices[-1] if indices else None)
            SELECT_BOX=(context.area.as_pointer(),rectangle);context.area.tag_redraw();return
        if self.index>=len(s.blocks):return
        if not getattr(self,'dragged',False) and abs(event.mouse_region_x-self.x)<3*metrics(context)['scale']:return
        self.dragged=True
        b=s.blocks[self.index];delta=round((event.mouse_region_x-self.x)/s.pixels_per_frame);start,end=self.original
        low,high=model_limits.frames(b.engine,fps(context.scene))
        if self.mode=='MOVE':start+=delta;end+=delta
        elif self.mode=='START':start=max(end-high,min(end-low,start+delta))
        else:end=max(start+low,min(start+high,end+delta))
        if not getattr(event,'shift',False):
            moving=getattr(self,'ranges',{b.uid:self.original})
            edges=[v for other in s.blocks if other.uid not in moving for v in (other.start,other.end)]
            offsets=[v-edge for edge in ((start,end) if self.mode=='MOVE' else (start,) if self.mode=='START' else (end,)) for v in edges]
            if offsets:
                snap=min(offsets,key=abs)
                if abs(snap)*s.pixels_per_frame<8*metrics(context)['scale']:
                    if self.mode=='MOVE':start+=snap;end+=snap
                    elif self.mode=='START':start=max(end-high,min(end-low,start+snap))
                    else:end=max(start+low,min(start+high,end+snap))
        if self.mode=='MOVE':
            delta=start-self.original[0]
            set_ranges(context.scene,{uid:(a+delta,z+delta) for uid,(a,z) in getattr(self,'ranges',{b.uid:self.original}).items()})
        else:set_range(b,start,end)
        context.area.tag_redraw()
    def modal(self,context,event):
        if self.mode=='POSE_MOVE' and self.pose_move.closed:
            pose_edit.header(context);clear_select_box(context);return {'CANCELLED'}
        if event.type in ('ESC','RIGHTMOUSE'):
            TOYXYZ_OT_edit.cancel(self,context);return {'CANCELLED'}
        if self.mode=='BOX' and not self.anchor and event.type=='LEFTMOUSE' and event.value=='PRESS':
            self.x=event.mouse_region_x;self.y=event.mouse_region_y;self.anchor=True
            self.extend=getattr(event,'shift',False);self.subtract=getattr(event,'ctrl',False)
            if not self.extend and not self.subtract:
                if self.pose_domain:pose_edit.select(settings(context).rig,set())
                else:selection_set(settings(context),set())
        elif event.type=='LEFTMOUSE' and event.value=='RELEASE':
            if self.mode.startswith('LAYER_'):
                s=settings(context)
                try:
                    if s.rig!=self.layer_rig:raise ValueError('The active SOMA actor changed.')
                    if control_layers.editing(s.rig)==self.layer:
                        if self.dragged:control_layers.refresh(context,s.rig)
                        else:control_layers.deselect(context,s)
                    else:control_layers.select(context,s,self.layer)
                except (ValueError,ReferenceError) as exc:
                    TOYXYZ_OT_edit.cancel(self,context)
                    self.report({'WARNING'},str(exc));return {'CANCELLED'}
                return {'FINISHED'}
            if self.mode=='CONSTRAINT_MOVE':
                context.area.tag_redraw();return {'FINISHED'}
            if self.mode=='POSE_MOVE':
                message=self.pose_move.error;self.pose_move.finish(not message);pose_edit.header(context)
                if message:
                    TOYXYZ_OT_edit.cancel(self,context)
                    self.report({'WARNING'},message);return {'CANCELLED'}
                if self.collapse and not self.dragged:pose_edit.select(settings(context).rig,{self.pose_frame})
                clear_select_box(context);return {'FINISHED'}
            if self.mode!='BOX' and self.mode!='SCRUB' and self.collapse and not self.dragged:select(settings(context),self.index)
            clear_select_box(context);return {'FINISHED'}
        if event.type=='MOUSEMOVE':
            try:self.update(context,event)
            except (ValueError,ReferenceError) as exc:
                TOYXYZ_OT_edit.cancel(self,context);self.report({'WARNING'},str(exc));return {'CANCELLED'}
        return {'RUNNING_MODAL'}
    def cancel(self,context):
        if self.mode.startswith('LAYER_'):
            if self.dragged:
                try:
                    if self.mode=='LAYER_MOVE':control_layers.place(self.layer[1],*self.original)
                    else:control_layers.resize(self.layer[1],*self.original,*self.layer_source)
                    control_layers.refresh(context,self.layer_rig)
                except ReferenceError:pass
            return
        if self.mode=='SCRUB':context.scene.frame_set(self.original[0])
        elif self.mode=='POSE_MOVE':self.pose_move.finish(False);pose_edit.header(context)
        elif self.mode=='CONSTRAINT_MOVE':
            self.constraint_marker.frame=self.original[0];settings(context).active_object_constraint=self.before_constraint
        elif self.mode!='BOX':
            if getattr(self,'ranges',None):set_ranges(context.scene,self.ranges)
            elif self.index<len(settings(context).blocks):set_range(settings(context).blocks[self.index],*self.original)
        if hasattr(self,'before_selection'):selection_set(settings(context),self.before_selection,self.before_active)
        if getattr(self,'before_pose_selection',None) is not None:pose_edit.restore_selection(settings(context).rig,self.before_pose_selection)
        if hasattr(self,'before_domain'):settings(context).selection=self.before_domain
        clear_select_box(context)


class TOYXYZ_OT_select_all(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.select_blocks';bl_label='Select Timeline Items';bl_options={'UNDO'}
    bl_description='Change the selection in the active timeline row'
    action:EnumProperty(items=[('ALL','All',''),('NONE','None',''),('INVERT','Invert','')],default='ALL')
    @classmethod
    def description(cls,context,properties):
        return {
            'ALL':'Select all items in the active row.',
            'NONE':'Deselect all items in the active row.',
            'INVERT':'Select unselected items and deselect selected items.',
        }.get(properties.action,cls.bl_description)
    def execute(self,context):
        s=settings(context)
        if s.selection=='LAYER':
            if self.action=='NONE':control_layers.deselect(context,s);return {'FINISHED'}
            return {'CANCELLED'}
        if s.selection=='CONSTRAINT':
            if self.action=='NONE':s.active_object_constraint=-1;context.area.tag_redraw();return {'FINISHED'}
            return {'CANCELLED'}
        if s.selection=='POSE':
            values=set(keyframes.frames(s.rig));chosen=pose_edit.selected(s.rig)
            pose_edit.select(s.rig,values if self.action=='ALL' else values-chosen if self.action=='INVERT' else set())
            context.area.tag_redraw();return {'FINISHED'}
        ids={b.uid for b in s.blocks if self.action=='ALL' or (self.action=='INVERT' and not b.selected)}
        selection_set(s,ids);context.area.tag_redraw();return {'FINISHED'}


class TOYXYZ_OT_zoom_border(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_zoom_border';bl_label='Zoom Region';bl_options={'BLOCKING'}
    bl_description='Drag a box around the frame range to zoom into'
    def invoke(self,context,event):
        self.start=None;context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def finish(self,context):
        global BORDER
        BORDER=None;context.area.tag_redraw();return {'FINISHED'}
    def cancel(self,context):self.finish(context)
    def modal(self,context,event):
        global BORDER
        if event.type=='ESC':self.finish(context);return {'CANCELLED'}
        if event.type in ('LEFTMOUSE','RIGHTMOUSE'):
            if event.value=='PRESS':self.start=event.mouse_region_x;self.button=event.type
            elif event.value=='RELEASE' and self.start is not None:
                width=max(1,context.region.width-metrics(context)['gutter']);span=abs(event.mouse_region_x-self.start)
                if span>3:
                    s=settings(context)
                    if self.button=='LEFTMOUSE':
                        start=frame_at(context,min(self.start,event.mouse_region_x));s.pixels_per_frame*=width/span;s.view_start=start
                    else:zoom_at_pointer(context,(span/width)**2)
                BORDER=None;context.area.tag_redraw();return {'FINISHED'}
        if self.start is not None:BORDER=(self.start,event.mouse_region_x);context.area.tag_redraw()
        return {'RUNNING_MODAL'}


class TOYXYZ_OT_scroll(TimelineOperator,bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.timeline_scroll';bl_label='Scroll Timeline';bl_options={'BLOCKING'}
    bl_description='Drag the scrollbar to pan or its ends to zoom'
    def invoke(self,context,event):
        self.bar=timeline_style.scrollbar(context);self.x=event.mouse_region_x
        s=settings(context);self.original=(s.view_start,s.pixels_per_frame)
        if self.x<self.bar['a'] or self.x>self.bar['b']:
            s.view_start+=self.bar['visible']*.9*(-1 if self.x<self.bar['a'] else 1)
            context.area.tag_redraw();return {'FINISHED'}
        grip=6*metrics(context)['scale']
        self.mode='LEFT' if self.x-self.bar['a']<grip else 'RIGHT' if self.bar['b']-self.x<grip else 'PAN'
        context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def modal(self,context,event):
        s=settings(context)
        if event.type in ('ESC','RIGHTMOUSE'):
            s.view_start,s.pixels_per_frame=self.original;context.area.tag_redraw();return {'CANCELLED'}
        if event.type=='LEFTMOUSE' and event.value=='RELEASE':return {'FINISHED'}
        if event.type=='MOUSEMOVE':
            delta=(event.mouse_region_x-self.x)*(self.bar['right']-self.bar['left'])/self.bar['width']
            start,ppf=self.original;width=max(1,context.region.width-metrics(context)['gutter']);visible=width/ppf
            if self.mode=='PAN':s.view_start=start+delta
            else:
                length=visible-delta if self.mode=='LEFT' else visible+delta
                s.pixels_per_frame=max(.15,min(80,width/max(.001,length)))
                s.view_start=start+visible-width/s.pixels_per_frame if self.mode=='LEFT' else start
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}


class TOYXYZ_MT_view(bpy.types.Menu):
    bl_label='View'
    bl_description='Set the visible frame range and timeline display'
    def draw(self,context):
        l=self.layout;l.operator('toyxyz_motion_ai_tool.timeline_frame',text='Frame All');l.operator('toyxyz_motion_ai_tool.timeline_frame',text='Frame Selected').selected=True
        l.operator('toyxyz_motion_ai_tool.timeline_frame',text='Go to Current Frame').current=True
        l.operator('toyxyz_motion_ai_tool.timeline_match_native',text='Match Blender Timeline')
        l.operator('toyxyz_motion_ai_tool.timeline_zoom_border',text='Zoom Region');l.separator()
        l.prop(settings(context),'timeline_show_channels',text='Channels');l.prop(settings(context),'timeline_show_seconds',text='Seconds')
        l.prop(context.space_data,'show_region_ui',text='Sidebar')


class TOYXYZ_MT_block(bpy.types.Menu):
    bl_label='Block'
    bl_description='Edit, delete or generate motion blocks'
    def draw(self,context):
        l=self.layout
        l.operator('toyxyz_motion_ai_tool.edit_prompt',text='Edit Prompt',icon='GREASEPENCIL')
        l.operator('toyxyz_motion_ai_tool.delete_item',text='Delete Selected Blocks',icon='X').target='BLOCK';l.separator()
        l.operator('toyxyz_motion_ai_tool.generate',text='Generate Motion',icon='PLAY')
        # Generated results apply automatically; no manual Apply command in this menu.


class TOYXYZ_MT_key(bpy.types.Menu):
    bl_label='Key'
    bl_description='Move or delete selected pose keys'
    def draw(self,context):
        l=self.layout;l.operator('toyxyz_motion_ai_tool.move_pose_keys',text='Move Pose Keys')
        l.operator('toyxyz_motion_ai_tool.delete_item',text='Delete Selected Pose Keys',icon='X').target='POSE'


class TOYXYZ_MT_constraint(bpy.types.Menu):
    bl_label='Constraint'
    bl_description='Add or remove object target markers'
    def draw(self,context):
        layout=self.layout
        layout.operator('toyxyz_motion_ai_tool.add_object_constraint',icon='ADD')
        row=layout.row();row.enabled=object_constraints.active(settings(context)) is not None
        row.operator('toyxyz_motion_ai_tool.delete_item',text='Delete Constraint',icon='X').target='CONSTRAINT'


class TimelineContext:
    # Reuse the installed Timeline widget layout without exposing node-editor keying controls.
    def __init__(self,context):
        from types import SimpleNamespace
        self.context=context;self.space_data=SimpleNamespace(type='DOPESHEET_EDITOR',mode='TIMELINE')
    def __getattr__(self,name):return getattr(self.context,name)


def draw_motion_controls(layout,s,*,inline=False):
    state=client.state
    busy=(state['job_status'] in ('queued','running') or any(
        state.get(key) for key in ('auto_apply_pending','sequence','pending_connect','stopping')))
    row=layout.row(align=True)
    generate=row.row(align=True)
    generate.enabled=bool(selected(s)) and not busy
    generate.operator('toyxyz_motion_ai_tool.generate',icon='PLAY')
    row.operator('toyxyz_motion_ai_tool.app_control',text='Cancel').command='cancel'
    clear=row if inline else layout
    clear.operator('toyxyz_motion_ai_tool.clear_motion',text='Clear Motion',icon='X')


def draw_header(self,context):
    if not ours(context):return _header(self,context)
    from bl_ui.space_time import playback_controls
    l=self.layout;l.template_header();l.menu('TOYXYZ_MT_view');l.menu('TOYXYZ_MT_block')
    l.menu('TOYXYZ_MT_key',icon='KEY_HLT' if settings(context).selection=='POSE' else 'NONE')
    l.menu('TOYXYZ_MT_constraint')
    l.operator('toyxyz_motion_ai_tool.add_block',text='Add Block',icon='ADD')
    row=l.row(align=True)
    row.operator('toyxyz_motion_ai_tool.add_control_layer',icon='ADD')
    layer=control_layers.editing(settings(context).rig)
    if layer:
        row.operator('toyxyz_motion_ai_tool.toggle_control_layer',text='',icon='HIDE_ON' if layer[0].mute else 'HIDE_OFF')
    l.separator()
    draw_motion_controls(l,settings(context),inline=True)
    playback_controls(l,TimelineContext(context))


def rgba(color,alpha=1):return tuple(color[:3])+(alpha,)


def draw():
    context=bpy.context
    if ours(context) and context.region.type=='WINDOW':
        box=SELECT_BOX[1] if SELECT_BOX and SELECT_BOX[0]==context.area.as_pointer() else None
        timeline_style.draw(context,BORDER,box)


def redraw_regions(scene,windows):
    for window in windows:
        if window.scene!=scene:continue
        for area in window.screen.areas:
            if area.type=='NODE_EDITOR' and area.ui_type==TREE:
                for region in area.regions:
                    if region.type in ('WINDOW','HEADER','UI'):region.tag_redraw()
            elif area.type=='VIEW_3D':
                for region in area.regions:
                    if region.type=='UI':region.tag_redraw()


@persistent
def redraw(scene,*_):redraw_regions(scene,bpy.context.window_manager.windows)


CLASSES=(TOYXYZ_TimelineTree,TOYXYZ_OT_zoom,TOYXYZ_OT_navigate,TOYXYZ_OT_frame,TOYXYZ_OT_match_native,TOYXYZ_OT_prompt,TOYXYZ_OT_constraint_type,TOYXYZ_OT_constraint_menu,TOYXYZ_OT_add_object_constraint,TOYXYZ_OT_add_control_layer,TOYXYZ_OT_toggle_control_layer,TOYXYZ_OT_edit,TOYXYZ_OT_select_all,TOYXYZ_OT_zoom_border,TOYXYZ_OT_scroll,TOYXYZ_MT_view,TOYXYZ_MT_block,TOYXYZ_MT_key,TOYXYZ_MT_constraint)


def register():
    global _draw,_header
    for cls in CLASSES:bpy.utils.register_class(cls)
    _header=bpy.types.NODE_HT_header.draw;bpy.types.NODE_HT_header.draw=draw_header
    _draw=bpy.types.SpaceNodeEditor.draw_handler_add(draw,(),'WINDOW','POST_PIXEL')
    bpy.app.handlers.frame_change_post.append(redraw)
    config=bpy.context.window_manager.keyconfigs.addon
    if config:
        km=config.keymaps.new(name='View2D',space_type='EMPTY',region_type='WINDOW')
        def bind(operator,key,value='PRESS',properties=None,**mods):
            item=km.keymap_items.new('toyxyz_motion_ai_tool.'+operator,key,value,**mods)
            for name,v in (properties or {}).items():setattr(item.properties,name,v)
            _keys.append((km,item))
        bind('timeline_edit','LEFTMOUSE');bind('timeline_edit','LEFTMOUSE','DOUBLE_CLICK')
        bind('constraint_menu','RIGHTMOUSE')
        bind('timeline_edit','LEFTMOUSE',shift=True);bind('timeline_edit','LEFTMOUSE',ctrl=True)
        bind('timeline_edit','B',properties={'box':True})
        bind('move_pose_keys','G')
        bind('select_blocks','A');bind('select_blocks','A',alt=True,properties={'action':'NONE'})
        bind('select_blocks','I',ctrl=True,properties={'action':'INVERT'})
        bind('timeline_navigate','MIDDLEMOUSE');bind('timeline_navigate','MIDDLEMOUSE',shift=True)
        bind('timeline_navigate','MIDDLEMOUSE',properties={'mode':'ZOOM'},ctrl=True)
        bind('timeline_navigate','TRACKPADPAN','ANY');bind('timeline_navigate','TRACKPADPAN','ANY',ctrl=True,properties={'mode':'ZOOM'});bind('timeline_navigate','TRACKPADZOOM','ANY',properties={'mode':'ZOOM'})
        for key,direction in (('WHEELINMOUSE',1),('WHEELOUTMOUSE',-1),('NUMPAD_PLUS',1),('NUMPAD_MINUS',-1)):
            bind('timeline_zoom',key,properties={'direction':direction},repeat=key.startswith('NUMPAD'))
        for key,direction in (('WHEELUPMOUSE',-1),('WHEELDOWNMOUSE',1)):
            bind('timeline_zoom',key,ctrl=True,properties={'direction':direction,'pan':True})
        for key,direction in (('WHEELUPMOUSE',-1),('WHEELDOWNMOUSE',1)):
            bind('timeline_zoom',key,shift=True,properties={'direction':direction,'pan':True})
        bind('timeline_zoom','WHEELLEFTMOUSE',properties={'direction':-1,'pan':True});bind('timeline_zoom','WHEELRIGHTMOUSE',properties={'direction':1,'pan':True})
        bind('timeline_frame','BUTTON4MOUSE');bind('timeline_frame','HOME');bind('timeline_frame','NUMPAD_PERIOD',properties={'selected':True})
        bind('timeline_frame','NUMPAD_0',properties={'current':True});bind('timeline_zoom_border','B',shift=True)
        bind('delete_item','X',properties={'confirm':True,'target':'AUTO'})
        bind('delete_item','DEL',properties={'confirm':False,'target':'AUTO'})


def unregister():
    global _draw,_header,SELECT_BOX
    SELECT_BOX=None
    for km,item in _keys:km.keymap_items.remove(item)
    _keys.clear()
    if redraw in bpy.app.handlers.frame_change_post:bpy.app.handlers.frame_change_post.remove(redraw)
    if _draw:bpy.types.SpaceNodeEditor.draw_handler_remove(_draw,'WINDOW');_draw=None
    if _header:bpy.types.NODE_HT_header.draw=_header;_header=None
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
