"""Sample a block's scene curve into a dense canonical SOMA ground-plane path."""
from . import rig_store
import bisect
import hashlib
import json
import math
import bpy
from mathutils import Vector
from . import rig,scene_sampling


def poll(self,obj):return obj.type=='CURVE'


def search(self,context,text):return [o.name_full for o in context.scene.objects if o.type=='CURVE']


def get_start_percent(block):
    legacy=100*block.get('toyxyz_curve_start_offset',0)/max(1,block.end-block.start-1)
    return max(0.0,min(100.0,float(block.get('toyxyz_curve_start_percent',legacy))))


def set_start_percent(block,value):
    block['toyxyz_curve_start_percent']=max(0.0,min(100.0,float(value)))
    if 'toyxyz_curve_start_offset' in block:del block['toyxyz_curve_start_offset']


def get_start_frame(block):
    return block.start+max(0,block.end-block.start-1)*get_start_percent(block)/100


def start_index(block,fps,count=None):
    count=round((block.end-block.start)*30/fps) if count is None else count
    # Snap forward on the model clock; 100% targets only its final sample.
    return max(0,min(count-1,math.ceil((get_start_frame(block)-block.start)*30/fps-1e-7)))


@scene_sampling.transient
def sample(context,obj,curve,frame,count,span=(0.0,1.0)):
    if curve.type!='CURVE' or curve.name not in context.scene.objects:raise ValueError('Choose a Path Curve linked to this scene.')
    scene=context.scene;saved_frame=(scene.frame_current,scene.frame_subframe)
    saved_pose=rig.pose_state(obj);saved_objects=[(o,{c:tuple(getattr(o,c)) for c in rig.TRANSFORM_CHANNELS}) for o in (obj,curve)]
    data=None;temp=None;evaluated=None
    try:
        whole=math.floor(frame);scene.frame_set(whole,subframe=frame-whole);context.view_layer.update()
        source=curve.evaluated_get(context.evaluated_depsgraph_get())
        if len(source.data.splines)!=1:raise ValueError('Path Curve must contain one continuous spline.')
        data=source.data.copy();data.animation_data_clear();data.dimensions='3D'
        data.bevel_depth=0;data.bevel_object=None;data.extrude=0;data.offset=0;data.resolution_u=max(64,data.resolution_u)
        temp=bpy.data.objects.new('toyxyz_motion_ai_tool_PathSample',data)
        scene.collection.objects.link(temp);temp.matrix_world=source.matrix_world.copy();context.view_layer.update()
        evaluated=temp.evaluated_get(context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
        if not mesh or len(mesh.vertices)<2:raise ValueError('Path Curve needs at least two different points.')
        neighbors={v.index:[] for v in mesh.vertices}
        for edge in mesh.edges:
            a,b=edge.vertices;neighbors[a].append(b);neighbors[b].append(a)
        if any(len(n) not in (1,2) for n in neighbors.values()):raise ValueError('Path Curve must be a single unbranched centerline.')
        ends=[i for i,n in neighbors.items() if len(n)==1]
        if len(ends) not in (0,2):raise ValueError('Path Curve must be a single continuous centerline.')
        start=min(ends) if ends else min(neighbors);order=[start];visited={start};previous=None;current=start
        while True:
            choices=sorted(n for n in neighbors[current] if n!=previous)
            if not choices:break
            nxt=choices[0]
            if nxt==start:
                order.append(start);break
            if nxt in visited:raise ValueError('Path Curve contains an unsupported branch.')
            order.append(nxt);visited.add(nxt);previous,current=current,nxt
        if len(visited)!=len(mesh.vertices):raise ValueError('Path Curve has disconnected geometry.')
        inverse=obj.evaluated_get(context.evaluated_depsgraph_get()).matrix_world.inverted()
        points=[]
        for index in order:
            p=rig.CI@(inverse@(evaluated.matrix_world@mesh.vertices[index].co))/obj['toyxyz_units']
            point=Vector((p.x,p.z))
            if not all(math.isfinite(v) for v in point):raise ValueError('Path Curve has invalid coordinates.')
            if not points or (point-points[-1]).length>1e-8:points.append(point)
        distances=[0.0]
        for a,b in zip(points,points[1:]):distances.append(distances[-1]+(b-a).length)
        if len(points)<2 or distances[-1]<1e-5:raise ValueError('Path Curve has no horizontal length.')
        result=[]
        for i in range(count):
            distance=distances[-1]*(span[0]+(span[1]-span[0])*i/max(1,count-1))
            j=max(0,min(len(points)-2,bisect.bisect_right(distances,distance)-1))
            result.append(list(points[j].lerp(points[j+1],(distance-distances[j])/(distances[j+1]-distances[j]))))
        signature=hashlib.sha256(json.dumps([curve.name_full,[[round(v,6) for v in p] for p in result]],separators=(',',':')).encode()).hexdigest()
        return dict(curve=curve.name_full,points=result,signature=signature)
    finally:
        if evaluated is not None:evaluated.to_mesh_clear()
        if temp is not None:bpy.data.objects.remove(temp,do_unlink=True)
        if data is not None and data.users==0:bpy.data.curves.remove(data)
        scene.frame_set(saved_frame[0],subframe=saved_frame[1]);rig.restore_pose_state(obj,saved_pose)
        for item,channels in saved_objects:
            for name,value in channels.items():setattr(item,name,value)
        context.view_layer.update()


def curve_groups(scene):
    """Use scene neighbors so regenerating a subset retains its route section."""
    groups=[]
    for block in sorted((b for b in rig_store.settings(scene).blocks if b.enabled),key=lambda b:(b.start,b.end,b.uid)):
        curve=block.path_curve
        if block.engine not in ('kimodo','ardy') or not curve:
            groups.append([]);continue
        previous=groups[-1][-1] if groups and groups[-1] else None
        if previous is not None and previous.engine==block.engine and previous.end==block.start and previous.path_curve==curve and get_start_frame(block)==block.start:
            groups[-1].append(block)
        else:groups.append([block])
    return {b.uid:group for group in groups for b in group}


def block_path(context,block,count,group):
    fps=context.scene.render.fps/context.scene.render.fps_base
    start=group[0].start;delay=start_index(group[0],fps);offset=start_index(block,fps,count)
    total=round((group[-1].end-start)*30/fps)-delay
    if total<1 or count-offset<1:raise ValueError('Choose an earlier Curve Start (%) for this route.')
    first=0 if block.uid==group[0].uid else round((block.start-start)*30/fps)-delay
    last=round((block.end-start)*30/fps)-1-delay
    span=(first/max(1,total-1),last/max(1,total-1));frame=get_start_frame(group[0])
    path=sample(context,rig_store.settings(context.scene).rig,block.path_curve,frame,count-offset,span)
    path.update(group=[dict(uid=b.uid,start=b.start,end=b.end,curve_start_percent=get_start_percent(b)) for b in group],
                sample_frame=frame,start_index=offset,start_frame=get_start_frame(block),span=list(span))
    return path


def attach(context,blocks):
    live={b.uid:b for b in rig_store.settings(context.scene).blocks};groups=curve_groups(context.scene)
    fps=context.scene.render.fps/context.scene.render.fps_base;start=blocks[0]['start'];result=[];previous_engine=None
    for source in blocks:
        item=dict(source);block=live.get(source['uid'])
        engine=block.engine if block else source.get('engine')
        if engine!=previous_engine:start=source['start'];previous_engine=engine
        curve=block.path_curve if block else None
        if block and block.engine in ('kimodo','ardy') and curve:
            item['path_curve']=curve.name_full
            if not item.get('root_path'):
                count=round((block.end-start)*30/fps)-round((block.start-start)*30/fps)
                item['root_path']=block_path(context,block,count,groups[block.uid])
        result.append(item)
    for a,b in zip(result,result[1:]):
        if a['end']==b['start'] and a.get('root_path') and b.get('root_path'):
            if a['root_path'].get('group') and a['root_path']['group']==b['root_path'].get('group'):continue
            if not b['root_path'].get('start_index',0) and (Vector(a['root_path']['points'][-1])-Vector(b['root_path']['points'][0])).length>.05:
                raise ValueError('Adjacent Path Curves must meet, or increase Curve Start (%) on the next block for an approach.')
    return result


def matches(scene,block,source):
    curve=block.path_curve if block.engine in ('kimodo','ardy') else None
    if (curve.name_full if curve else '')!=source.get('path_curve',''):return False
    path=source.get('root_path')
    if not path:return curve is None
    if not curve:return False
    try:
        with bpy.context.temp_override(scene=scene,view_layer=scene.view_layers[0]):
            group=curve_groups(scene).get(block.uid)
            if not group:return False
            current=block_path(bpy.context,block,len(path['points'])+path.get('start_index',0),group)
        return (current['signature']==path['signature'] and current['start_index']==path.get('start_index',0)
                and ('group' not in path or current['group']==path['group']))
    except (ValueError,RuntimeError,ReferenceError,ZeroDivisionError):return False
