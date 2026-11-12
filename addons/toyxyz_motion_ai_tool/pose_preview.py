"""Object-free viewport drawing of the selected blocks' actual request targets."""
from . import rig_store
import math,time,textwrap
from contextlib import contextmanager
import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix,Vector
from . import rig,object_constraints,scene_sampling

COLORS={'FULL':(.32,.63,1.0),'LEFT_HAND':(.05,.9,1.0),'RIGHT_HAND':(1.0,.52,.12),
        'LEFT_FOOT':(.25,1.0,.35),'RIGHT_FOOT':(1.0,.28,.7),'ROOT':(1.0,.85,.15),'HIPS':(.7,.45,1.0)}
SHORT={'FULL':'FB','LEFT_HAND':'LH','RIGHT_HAND':'RH','LEFT_FOOT':'LF','RIGHT_FOOT':'RF','ROOT':'R2','HIPS':'Hips'}
LINE_WIDTH=1.5
LINE_OPACITY=.35
CORE=tuple(rig.SCHEMA['core_names']);_core=set(CORE)
PARENTS={}
for name in CORE:
    parent=rig.PARENTS[rig.NAMES.index(name)]
    while parent>=0 and rig.NAMES[parent] not in _core:parent=rig.PARENTS[parent]
    PARENTS[name]=rig.NAMES[parent] if parent>=0 else None
_cache={};_dirty=set();_changed_at={};_busy=False;_handlers=[];_serial=0

def changed(self=None,context=None):
    if _busy:return
    keys=[context.scene.as_pointer()] if context and context.scene else [s.as_pointer() for s in getattr(bpy.data,'scenes',())]
    for key in keys:_dirty.add(key);_changed_at[key]=time.monotonic()

def redraw_display(self,context):
    for window in context.window_manager.windows:
        if window.scene==context.scene:
            for area in window.screen.areas:
                if area.type=='VIEW_3D':area.tag_redraw()

def clear():
    _cache.clear();_dirty.clear();_changed_at.clear()

def fk(pose,engine,root):
    """Match native 77->30 local-rotation selection, including dropped fingers."""
    names=CORE if engine in ('kimodo','ardy') else rig.NAMES
    parent_map=PARENTS if engine in ('kimodo','ardy') else {n:rig.NAMES[p] if p>=0 else None for n,p in zip(rig.NAMES,rig.PARENTS)}
    positions={};rotations={};neutral={n:Vector(rig.SCHEMA['neutral_joints'][rig.NAMES.index(n)]) for n in names}
    for name in names:
        parent=parent_map[name];local=Matrix(pose['local_rotations'][rig.NAMES.index(name)])
        rotations[name]=rotations[parent]@local if parent else local
        positions[name]=positions[parent]+rotations[parent]@(neutral[name]-neutral[parent]) if parent else Vector(root)
    return positions,rotations

def path_point(data,frame):
    start=data['blocks'][0]['start'];count=round((data['blocks'][-1]['end']-start)*30/data['fps'])
    index=max(0,min(count-1,round((frame-start)*30/data['fps'])))
    for pose in data.get('poses',()):
        if pose['kind']!='ROOT' or 'object_goal' not in pose:continue
        target=max(0,min(count-1,round((pose['frame']-start)*30/data['fps'])))
        if target==index:return pose['object_goal']['position'][::2]
    for block in data['blocks']:
        path=block.get('root_path')
        if not path:continue
        first=round((block['start']-start)*30/data['fps'])+path.get('start_index',0)
        if first<=index<first+len(path['points']):return path['points'][index-first]
    return None

def materialize(data,worlds,units):
    """Canonical FK goals and world display data; no scene reads or mutations."""
    entries=[]
    for pose in data['poses']:
        root=list(pose['root']);point=path_point(data,pose['frame']);kind=pose['kind']
        goal=pose.get('object_goal')
        if goal and kind=='ROOT':root=list(goal['position'])
        if point is not None and kind in ('FULL','ROOT') and pose.get('source')!='previous_motion_end':root[0],root[2]=point
        positions,rotations=fk(pose,data['engine'],root);world=Matrix(worlds[pose['frame']])
        if goal and kind in object_constraints.BONES:
            joint=object_constraints.BONES[kind]
            secondary=joint+'MiddleEnd' if kind.endswith('HAND') else joint.replace('Foot','ToeBase')
            position=Vector(goal['position']);rotation=Matrix(goal['rotation'])
            delta=rotation @ rotations[joint].transposed()
            positions[secondary]=position+delta @ (positions[secondary]-positions[joint])
            positions[joint]=position;rotations[joint]=rotation
        def scene_point(value):return list(world@(rig.C@Vector(value)*units))
        scale=units*sum(world.to_scale())/3
        label=SHORT[kind]
        if kind=='ROOT':label=('R3' if pose.get('root_height') else 'R2')+('H' if pose.get('root_heading') else '')
        entry=dict(frame=pose['frame'],engine=data['engine'],kind=kind,label=label,source=pose.get('source','native_key'),
                   positions={n:list(p) for n,p in positions.items()},rotations={n:list(map(list,r)) for n,r in rotations.items()},
                   bones=[],points=[],axes=[],display_scale=scale)
        if kind=='FULL':
            for name in CORE:
                if rig.auxiliary(name):continue
                parent=PARENTS[name]
                if parent:entry['bones'].append((scene_point(positions[parent]),scene_point(positions[name])))
            anchor=positions['Hips'];entry['anchor']=scene_point(anchor)
        elif kind=='ROOT':
            value=Vector((root[0],root[1] if pose.get('root_height') else 0,root[2]))
            entry['points'].append(dict(position=scene_point(value),kind='ROOT',role='ROOT',scale=1.0))
            entry['anchor']=scene_point(value)
            if pose.get('root_heading'):
                if goal:heading=math.atan2(goal['heading'][1],goal['heading'][0])
                else:
                    diff=positions['RightLeg']-positions['LeftLeg'];heading=math.atan2(diff.z,-diff.x)
                end=value+Vector((math.sin(heading),0,math.cos(heading)))*.2
                entry['axes'].append((scene_point(value),scene_point(end),'ROOT'))
        else:
            side='Left' if kind.startswith('LEFT') else 'Right'
            joints=(side+'Hand',side+'HandMiddleEnd') if kind.endswith('HAND') else (side+'Foot',side+'ToeBase')
            for i,name in enumerate(joints):
                entry['points'].append(dict(position=scene_point(positions[name]),kind=kind,role=name,scale=1 if i==0 else .65))
            entry['anchor']=scene_point(positions[joints[0]])
            if data['engine']=='ardy':
                entry['points'].append(dict(position=scene_point(positions['Hips']),kind='HIPS',role='ARDY_HIPS',scale=.75))
            if data['engine']!='ardy' or point is not None:
                root_xz=point if point is not None else (root[0],root[2])
                entry['points'].append(dict(position=scene_point((root_xz[0],root[1],root_xz[1])),kind='ROOT',role='AUX_ROOT',scale=.6))
            # Axis directions reflect the actual native foot/wrist rotation.
            base=positions[joints[0]];rotation=rotations[joints[0]]
            for axis in range(3):
                end=base+rotation.col[axis]*.10
                entry['axes'].append((scene_point(base),scene_point(end),('X','Y','Z')[axis]))
        entries.append(entry)
    return entries

@scene_sampling.transient
def world_matrices(context,obj,poses):
    scene=context.scene;saved=(scene.frame_current,scene.frame_subframe);pose=rig.pose_state(obj)
    channels={n:tuple(getattr(obj,n)) for n in rig.TRANSFORM_CHANNELS};result={}
    try:
        for frame in sorted({p['frame'] for p in poses}):
            scene.frame_set(frame);context.view_layer.update()
            result[frame]=list(map(list,obj.evaluated_get(context.evaluated_depsgraph_get()).matrix_world))
    finally:
        scene.frame_set(saved[0],subframe=saved[1]);rig.restore_pose_state(obj,pose)
        for name,value in channels.items():setattr(obj,name,value)
        context.view_layer.update()
    return result

def signature(scene):
    from . import keyframes,pose_constraints
    s=rig_store.settings(scene);obj=s.rig;action,slot=rig.pose_action(obj) if obj else (None,None)
    blocks=tuple((b.uid,b.selected,b.enabled,b.engine,b.start,b.end,b.prompt,b.transition_frames,
                  b.path_curve.as_pointer() if b.path_curve else 0,b.path_start_percent) for b in s.blocks)
    curves=tuple((fc.data_path,fc.array_index,fc.mute,tuple((tuple(p.co),tuple(p.handle_left),tuple(p.handle_right),p.interpolation) for p in fc.keyframe_points)) for fc in keyframes.curves(obj))
    targets=object_constraints.definitions(s)
    return (obj.as_pointer() if obj else 0,action.as_pointer() if action else 0,slot.handle if slot else 0,blocks,curves,
            action.get(pose_constraints.KEY,'') if action else '',s.last_applied_job,scene.render.fps,scene.render.fps_base,targets)


@contextmanager
def preserve_edit_state(context,exclude=()):
    """Frame sampling also evaluates other characters; preserve all live transforms."""
    scene=context.scene;frame=(scene.frame_current,scene.frame_subframe);saved=[]
    with scene_sampling.scope(scene_sampling.SAMPLING,scene,True):
        for obj in scene.objects:
            if obj in exclude:continue
            if obj.type!='ARMATURE' and not obj.animation_data and obj!=context.view_layer.objects.active:continue
            saved.append((obj,obj.rotation_mode,{name:tuple(getattr(obj,name)) for name in rig.TRANSFORM_CHANNELS},
                          rig.pose_state(obj) if obj.type=='ARMATURE' and obj.pose else None))
        try:yield
        finally:
            if (scene.frame_current,scene.frame_subframe)!=frame:scene.frame_set(frame[0],subframe=frame[1])
            for obj,mode,channels,pose in saved:
                if obj.rotation_mode!=mode:obj.rotation_mode=mode
                for name,value in channels.items():
                    if tuple(getattr(obj,name))!=value:setattr(obj,name,value)
                if pose is not None:rig.restore_pose_state(obj,pose,only_changed=True)
            context.view_layer.update()


def interacting(context):
    obj=context.view_layer.objects.active
    return bool(obj and obj.mode=='EDIT') or any(len(window.modal_operators) for window in context.window_manager.windows)

def build(context):
    from . import request_data,timeline,generation
    s=rig_store.settings(context.scene);obj=rig.validate_rig(s.rig)
    timeline.migrate_blocks(context.scene);_,blocks=timeline.generation_blocks(context)
    entries=[];requests=[]
    for group in generation.groups(blocks):
        data=request_data(context,group['engine'],group['blocks'],include_history=False);requests.append(data)
        entries.extend(materialize(data,world_matrices(context,obj,data['poses']),obj['toyxyz_units']))
    return dict(entries=entries,requests=requests,error='',selected=tuple(b['uid'] for b in blocks))

def refresh(context,force=False):
    from . import control_layers
    global _busy,_serial
    scene=context.scene;s=rig_store.settings(scene);key=scene.as_pointer()
    if _busy or interacting(context):return False
    if not s.show_pose_targets or control_layers.editing(s.rig):
        return _cache.pop(key,None) is not None
    old=_cache.get(key);now=time.monotonic()
    if not force and old and now-_changed_at.get(key,0)<.18:return False
    stamp=signature(scene)
    if not force and old and old.get('signature')==stamp and key not in _dirty:return False
    if not force and old and now-old['time']<.3:return False
    _busy=True
    try:
        try:
            with preserve_edit_state(context):
                result=build(context) if s.rig else dict(entries=[],requests=[],error='',selected=())
        except Exception as exc:result=dict(entries=[],requests=[],error=str(exc),selected=())
        _serial+=1;result.update(signature=signature(scene),time=now,serial=_serial)
        _cache[key]=result;_dirty.discard(key)
    finally:_busy=False
    return True

def tick():
    from . import pose_edit
    if _busy or pose_edit.busy():return False
    if any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows):return False
    changed_any=False;seen=set()
    for window in bpy.context.window_manager.windows:
        scene=window.scene
        if scene.as_pointer() in seen:continue
        seen.add(scene.as_pointer())
        if not any(a.type=='VIEW_3D' for a in window.screen.areas):continue
        with bpy.context.temp_override(window=window,scene=scene,view_layer=window.view_layer):
            changed_any=refresh(bpy.context) or changed_any
    return changed_any

@persistent
def on_update(scene,depsgraph):
    if _busy or any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows):return
    s=rig_store.settings(scene) if hasattr(scene,'toyxyz_motion_ai_tool') else None
    if not s or not s.show_pose_targets:return
    watched={s.rig} if s.rig else set()
    watched.update(b.path_curve for b in s.blocks if b.path_curve)
    watched.update(marker.target for marker in s.object_constraints if marker.target)
    for obj in tuple(watched):
        while obj and obj.parent:watched.add(obj.parent);obj=obj.parent
    for update in depsgraph.updates:
        value=update.id.original
        if isinstance(value,(bpy.types.Action,bpy.types.Armature,bpy.types.Curve)) or value in watched:
            key=scene.as_pointer();_dirty.add(key);_changed_at[key]=time.monotonic();return

def sphere(center,radius):
    center=Vector(center);vertices=[];colors=[]
    for latitude in range(8):
        for longitude in range(12):
            corners=[]
            for a,b in ((latitude,longitude),(latitude+1,longitude),(latitude+1,longitude+1),(latitude,longitude+1)):
                phi=math.pi*a/8;theta=2*math.pi*b/12
                corners.append(Vector((math.sin(phi)*math.cos(theta),math.sin(phi)*math.sin(theta),math.cos(phi))))
            for tri in ((0,1,2),(0,2,3)):
                for i in tri:
                    normal=corners[i];vertices.append(list(center+normal*radius))
                    colors.append(.45+.55*max(0,normal.dot(Vector((-.3,-.4,.866)))))
    return vertices,colors

def drawing_buffers(entries,size,point_opacity,axes=False,line_opacity=LINE_OPACITY):
    faces=[];face_colors=[];lines=[];line_colors=[]
    def triangles(points,color,alpha,shade=None):
        faces.extend(points);face_colors.extend([(*(v*(shade[i] if shade else 1) for v in color),alpha) for i in range(len(points))])
    def edges(points,color,alpha):lines.extend(points);line_colors.extend([(*color,alpha)]*len(points))
    for entry in entries:
        color=COLORS[entry['kind']]
        for a,b in entry['bones']:
            edges([a,b],color,line_opacity)
        for point in entry['points']:
            points,shade=sphere(point['position'],size*entry['display_scale']*point['scale'])
            triangles(points,COLORS[point['kind']],min(1,point_opacity+.25),shade)
        for a,b,axis in entry['axes']:
            if axis=='ROOT' or axes:
                color={'X':(1,.25,.2),'Y':(.25,1,.3),'Z':(.3,.55,1)}.get(axis,COLORS['ROOT'])
                edges([a,b],color,line_opacity)
    return dict(faces=faces,face_colors=face_colors,lines=lines,line_colors=line_colors)

def visible(context):
    space=context.space_data;s=rig_store.settings(context.scene)
    return bool(space and space.type=='VIEW_3D' and space.overlay.show_overlays and s.show_pose_targets and s.rig and s.rig.visible_get(view_layer=context.view_layer))

def draw_buffers(buffers,in_front=True,line_width=LINE_WIDTH):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader=gpu.shader.from_builtin('SMOOTH_COLOR')
    shader.bind()
    gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE' if in_front else 'LESS_EQUAL');gpu.state.depth_mask_set(False)
    try:
        if buffers['faces']:
            batch_for_shader(shader,'TRIS',{'pos':buffers['faces'],'color':buffers['face_colors']}).draw(shader)
        if buffers['lines']:
            shader=gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR');shader.bind()
            shader.uniform_float('viewportSize',gpu.state.viewport_get()[2:])
            shader.uniform_float('lineWidth',line_width*(bpy.context.preferences.system.ui_scale or 1.0))
            batch_for_shader(shader,'LINES',{'pos':buffers['lines'],'color':buffers['line_colors']}).draw(shader)
    finally:gpu.state.depth_mask_set(True);gpu.state.depth_test_set('NONE');gpu.state.blend_set('NONE')

def draw_3d():
    context=bpy.context
    if not visible(context):return
    s=rig_store.settings(context.scene);data=_cache.get(context.scene.as_pointer())
    if not data:return
    style=(s.pose_target_size,s.pose_target_opacity,s.pose_target_axes,s.pose_target_line_opacity)
    if data.get('style')!=style:
        data['buffers']=drawing_buffers(data['entries'],*style);data['style']=style
    draw_buffers(data['buffers'],s.pose_targets_in_front,s.pose_target_line_width)

def draw_labels():
    import blf
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    context=bpy.context
    if not visible(context):return
    s=rig_store.settings(context.scene);data=_cache.get(context.scene.as_pointer())
    if not data or not s.pose_target_labels:return
    font=0;blf.size(font,12*context.preferences.system.ui_scale)
    for entry in data['entries']:
        at=location_3d_to_region_2d(context.region,context.region_data,Vector(entry['anchor']))
        if at is None:continue
        blf.color(font,*COLORS[entry['kind']],.95);blf.position(font,at.x+6,at.y+7,0)
        label=f"F {entry['frame']} · {entry['label']}"
        if entry['source']=='previous_motion_end':label+=' · Previous'
        blf.draw(font,label)

def panel(layout,context):
    s=rig_store.settings(context.scene)
    layout.prop(s,'show_pose_targets')
    if not s.show_pose_targets:return
    data=_cache.get(context.scene.as_pointer())
    if data:
        if data['error']:
            for line in textwrap.wrap(data['error'],width=40):layout.label(text=line)
        else:layout.label(text=f"Pose targets: {len(data['entries'])} · Selected blocks")

def register():
    _handlers.extend([bpy.types.SpaceView3D.draw_handler_add(draw_3d,(),'WINDOW','POST_VIEW'),
                      bpy.types.SpaceView3D.draw_handler_add(draw_labels,(),'WINDOW','POST_PIXEL')])
    bpy.app.handlers.depsgraph_update_post.append(on_update)

def unregister():
    for handler in _handlers:bpy.types.SpaceView3D.draw_handler_remove(handler,'WINDOW')
    _handlers.clear()
    if on_update in bpy.app.handlers.depsgraph_update_post:bpy.app.handlers.depsgraph_update_post.remove(on_update)
    clear()
