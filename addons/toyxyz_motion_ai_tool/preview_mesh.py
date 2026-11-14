from . import rig_store
"""Official SOMA skin on the existing rig using native deformation only.

The source skin's bind matrices differ from the authoring rig's rest matrices.
Skin each influence as a rigid point, then sum its weighted position in Geometry
Nodes. This reproduces the official LBS without another armature or frame handler.
"""
import hashlib
from pathlib import Path
import bpy
from mathutils import Matrix
from . import rig

ROLE='toyxyz_soma_preview_role'
OWNER='toyxyz_soma_preview_owner'
WEIGHT='toyxyz_skin_weight'
VERTEX='toyxyz_skin_vertex'
FIRST='toyxyz_skin_first'


def owned(obj,role):
    return [child for child in obj.children if child.type=='MESH' and child.get(ROLE)==role
            and child.get(OWNER)==obj.get('toyxyz_uuid')]


def asset_path(context):
    from . import preferences,runtime_default
    pref=preferences(context);root=Path(bpy.path.abspath((pref.runtime_root if pref else '') or runtime_default()))
    for engine in ('kimodo','ardy'):
        path=root/f'engines/{engine}/{engine}/assets/skeletons/somaskel77/skin_standard.npz'
        if path.is_file():return path
    raise ValueError('SOMA mesh asset is missing. Set External App Folder to the installed companion app.')


def load_asset(context,obj):
    import numpy as np
    path=asset_path(context)
    with np.load(path,allow_pickle=False) as source:
        vertices=np.array(source['bind_vertices'],dtype=np.float64)
        faces=np.array(source['faces'],dtype=np.int32)
        bind=np.array(source['bind_rig_transform'],dtype=np.float64)
        indices=np.array(source['lbs_indices'],dtype=np.int32)
        weights=np.array(source['lbs_weights'],dtype=np.float64)
        names=source['rig_joint_names'].tolist()
    if (names!=rig.NAMES or bind.shape!=(77,4,4) or vertices.ndim!=2 or vertices.shape[1]!=3
        or faces.ndim!=2 or faces.shape[1]!=3 or indices.shape!=weights.shape or len(indices)!=len(vertices)
        or not np.isfinite(vertices).all() or not np.isfinite(bind).all() or not np.isfinite(weights).all()
        or (weights<0).any() or not np.allclose(weights.sum(1),1,atol=1e-5)
        or (indices<0).any() or (indices>=77).any() or (faces<0).any() or (faces>=len(vertices)).any()):
        raise ValueError('The SOMA preview asset does not match the 77-joint rig.')
    rows,columns=np.nonzero(weights>0)
    joints=indices[rows,columns];influence_weights=weights[rows,columns]
    inverses=np.linalg.inv(bind)[joints]
    local=np.einsum('nij,nj->ni',inverses[:,:3,:3],vertices[rows])+inverses[:,:3,3]
    # Blender's arbitrary bone Y axes cancel in PoseMatrix @ RestMatrix^-1.
    # Rest influence coordinates therefore use the model's identity joint axes.
    heads=np.asarray([obj.data.bones[name].head_local[:] for name in names])
    points=(local@np.asarray(rig.C).T)*obj['toyxyz_units']+heads[joints]
    rest=np.zeros((len(vertices),3));np.add.at(rest,rows,points*influence_weights[:,None])
    first=np.searchsorted(rows,np.arange(len(vertices))).astype(np.int32)
    return dict(vertices=rest,faces=faces,points=points,joints=joints,weights=influence_weights,
                vertex=rows.astype(np.int32),first=first,path=path,sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def attribute(mesh,name,data_type,field,values):
    item=mesh.attributes.new(name,data_type,'POINT');item.data.foreach_set(field,values)


def skin_nodes(mesh_obj,helper):
    group=bpy.data.node_groups.new('SOMA Preview Skin','GeometryNodeTree');group[ROLE]='NODES'
    group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    group.is_modifier=True;nodes=group.nodes;links=group.links
    incoming=nodes.new('NodeGroupInput');outgoing=nodes.new('NodeGroupOutput')
    info=nodes.new('GeometryNodeObjectInfo');info.transform_space='RELATIVE';info.inputs['Object'].default_value=helper
    position=nodes.new('GeometryNodeInputPosition')
    weight=nodes.new('GeometryNodeInputNamedAttribute');weight.data_type='FLOAT';weight.inputs['Name'].default_value=WEIGHT
    vertex=nodes.new('GeometryNodeInputNamedAttribute');vertex.data_type='INT';vertex.inputs['Name'].default_value=VERTEX
    first=nodes.new('GeometryNodeInputNamedAttribute');first.data_type='INT';first.inputs['Name'].default_value=FIRST
    scale=nodes.new('ShaderNodeVectorMath');scale.operation='SCALE'
    links.new(position.outputs['Position'],scale.inputs[0]);links.new(weight.outputs['Attribute'],scale.inputs['Scale'])
    total=nodes.new('GeometryNodeAccumulateField');total.data_type='FLOAT_VECTOR';total.domain='POINT'
    links.new(scale.outputs['Vector'],total.inputs['Value']);links.new(vertex.outputs['Attribute'],total.inputs['Group ID'])
    sample=nodes.new('GeometryNodeSampleIndex');sample.data_type='FLOAT_VECTOR';sample.domain='POINT'
    links.new(info.outputs['Geometry'],sample.inputs['Geometry']);links.new(total.outputs['Total'],sample.inputs['Value'])
    links.new(first.outputs['Attribute'],sample.inputs['Index'])
    deform=nodes.new('GeometryNodeSetPosition')
    links.new(incoming.outputs['Geometry'],deform.inputs['Geometry']);links.new(sample.outputs['Value'],deform.inputs['Position'])
    links.new(deform.outputs['Geometry'],outgoing.inputs['Geometry'])
    modifier=mesh_obj.modifiers.new('SOMA Preview Skin','NODES');modifier.node_group=group
    return group


def make_object(obj,name,role,vertices,faces):
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
    item=bpy.data.objects.new(name,data)
    (obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection).objects.link(item)
    item.parent=obj;item.matrix_parent_inverse=Matrix.Identity(4);item.matrix_basis=Matrix.Identity(4)
    item[ROLE]=role;item[OWNER]=obj['toyxyz_uuid']
    return item


def material():
    name='toyxyz_motion_ai_tool_SOMA_Preview';value=bpy.data.materials.get(name)
    if value is None:
        value=bpy.data.materials.new(name);value.diffuse_color=(.48,.55,.62,1);value.use_nodes=True
        bsdf=value.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value=value.diffuse_color;bsdf.inputs['Roughness'].default_value=.65
    return value


def ensure(context,obj):
    rig.validate_rig(obj)
    existing=owned(obj,'MESH')
    if existing:
        mesh=existing[0]
        if not owned(obj,'INFLUENCES'):raise ValueError('The SOMA mesh skin helper is missing. Remove the preview mesh and add it again.')
        visibility(rig_store.settings(context.scene),context)
        return mesh
    values=load_asset(context,obj);created=[];group=None
    try:
        # An unreferenced internal cloud can remain after a user deletes only
        # the visible preview mesh. Reuse it if it has the same bind contract.
        helper=next((item for item in owned(obj,'INFLUENCES') if item.get('toyxyz_skin_sha256')==values['sha256']),None)
        if helper is None:
            helper=make_object(obj,obj.name+'_skin','INFLUENCES',values['points'],[]);created.append(helper)
            attribute(helper.data,WEIGHT,'FLOAT','value',values['weights'])
            attribute(helper.data,VERTEX,'INT','value',values['vertex'])
            for index,name in enumerate(rig.NAMES):
                ids=(values['joints']==index).nonzero()[0].tolist()
                if ids:helper.vertex_groups.new(name=name).add(ids,1,'REPLACE')
            armature=helper.modifiers.new('SOMA Armature','ARMATURE');armature.object=obj;armature.use_deform_preserve_volume=False
            helper.hide_render=True;helper.hide_select=True;helper.hide_set(True)
            helper['toyxyz_skin_sha256']=values['sha256']
        mesh=make_object(obj,obj.name+'_mesh','MESH',values['vertices'],values['faces']);created.append(mesh)
        attribute(mesh.data,FIRST,'INT','value',values['first'])
        mesh.data.polygons.foreach_set('use_smooth',[True]*len(mesh.data.polygons))
        mesh.data.materials.append(material());mesh.hide_select=True
        mesh['toyxyz_skin_sha256']=values['sha256'];mesh['toyxyz_skin_source']=str(values['path'])
        group=skin_nodes(mesh,helper);visibility(rig_store.settings(context.scene),context)
        return mesh
    except BaseException:
        for item in reversed(created):
            data=item.data;bpy.data.objects.remove(item,do_unlink=True)
            if data.users==0:bpy.data.meshes.remove(data)
        if group is not None and group.users==0:bpy.data.node_groups.remove(group)
        raise


def visibility(settings,context):
    obj=settings.rig
    if obj is None:return
    for mesh in owned(obj,'MESH'):mesh.hide_set(not settings.show_soma_mesh);mesh.hide_render=not settings.show_soma_mesh
    for helper in owned(obj,'INFLUENCES'):helper.hide_set(True);helper.hide_render=True
