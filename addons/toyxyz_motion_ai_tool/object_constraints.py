"""Per-actor timeline markers backed by evaluated scene objects."""
import hashlib
import json

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty
from mathutils import Vector

from . import pose_constraints, rig, rig_store

BONES = {'LEFT_HAND': 'LeftHand', 'RIGHT_HAND': 'RightHand',
         'LEFT_FOOT': 'LeftFoot', 'RIGHT_FOOT': 'RightFoot'}
ITEMS = [item for item in pose_constraints.ITEMS if item[0] in BONES or item[0] == 'ROOT']
LABELS = {item[0]: item[1] for item in ITEMS}
SHORT = pose_constraints.LABELS
SIGNATURE = 'object_constraint_signature'


def changed(self, context):
    from . import pose_preview, timeline
    pose_preview.changed(self, context)
    timeline.redraw_regions(context.scene, context.window_manager.windows)


class TOYXYZ_ObjectConstraint(bpy.types.PropertyGroup):
    frame: IntProperty(name='Frame', description='Frame at which to sample the target object',
                       min=-1048574, max=1048574, update=changed)
    kind: EnumProperty(name='Constraint Type', description='Which part of the rig follows the object target',
                       items=ITEMS, default='LEFT_HAND', update=changed)
    target: PointerProperty(name='Target Object', type=bpy.types.Object, update=changed,
                            description='Use the evaluated origin and rotation of this object at the marker frame')
    root_heading: BoolProperty(name='Constrain Root Heading', default=True, update=changed,
                               description='Use the target object’s local -Y axis as the forward direction')
    root_height: BoolProperty(name='Constrain Root Height', default=True, update=changed,
                              description='Use the target origin’s height as a soft hips-height goal')


class TOYXYZ_UL_object_constraints(bpy.types.UIList):
    def filter_items(self, context, data, propname):
        marker = active(data)
        return [self.bitflag_filter_item if marker and item.frame == marker.frame else 0
                for item in getattr(data, propname)], []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0, flt_flag=0):
        kind = 'Root' if item.kind == 'ROOT' else LABELS[item.kind]
        target = item.target.name if item.target else 'No Target'
        layout.label(text=f'{kind} · {target}', icon='CONSTRAINT')


def active(settings):
    index = settings.active_object_constraint
    markers = settings.object_constraints
    return markers[index] if settings.selection == 'CONSTRAINT' and 0 <= index < len(markers) else None


def select(settings, index):
    settings.active_object_constraint = index
    settings.selection = 'CONSTRAINT'


def remove(settings):
    settings.object_constraints.remove(settings.active_object_constraint)
    settings.active_object_constraint = -1


def definitions(settings, start=-1048574, end=1048575):
    return sorted((m.frame, m.kind, m.target.name_full if m.target else '', m.root_heading, m.root_height)
                  for m in settings.object_constraints if start <= m.frame < end)


def stamp(goals):
    return hashlib.sha256(json.dumps(goals, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sample(context, settings, start, end):
    """Read target and actor world transforms at the marker, keeping live edits."""
    from . import pose_preview

    markers = [m for m in settings.object_constraints if start <= m.frame < end]
    if not markers:
        return []
    actor = settings.rig
    actor_objects = {actor, *actor.children_recursive}
    keys = set()
    for marker in markers:
        obj = marker.target
        if not obj or context.view_layer.objects.get(obj.name) != obj:
            raise ValueError(f'Choose a Target Object for the constraint at frame {marker.frame}.')
        if obj in actor_objects:
            raise ValueError(f'Choose an independent Target Object at frame {marker.frame}.')
        key = (marker.frame, marker.kind)
        if key in keys:
            raise ValueError(f'Only one {LABELS[marker.kind]} object constraint can use frame {marker.frame}.')
        keys.add(key)

    goals = []
    with pose_preview.preserve_edit_state(context):
        previous_frame = None
        for marker in sorted(markers, key=lambda m: (m.frame, m.kind)):
            if marker.frame != previous_frame:
                context.scene.frame_set(marker.frame)
                depsgraph = context.evaluated_depsgraph_get()
                actor_world = actor.evaluated_get(depsgraph).matrix_world.copy()
                if abs(actor_world.to_3x3().determinant()) < 1e-12:
                    raise ValueError('The SOMA rig has a zero scale axis.')
                inverse = actor_world.inverted()
                rotation_inverse = actor_world.to_quaternion().inverted()
                previous_frame = marker.frame
            world = marker.target.evaluated_get(depsgraph).matrix_world
            position = rig.CI @ (inverse @ world.translation) / actor['toyxyz_units']
            rotation = rotation_inverse @ world.to_quaternion()
            goal = dict(frame=marker.frame, kind=marker.kind, object=marker.target.name_full,
                        position=[round(v, 6) for v in position])
            if marker.kind == 'ROOT':
                if marker.root_heading:
                    forward = rig.CI @ (rotation @ Vector((0, -1, 0)))
                    heading = Vector((forward.z, forward.x))
                    if heading.length < 1e-5:
                        raise ValueError(f'The Target Object at frame {marker.frame} points vertically. Rotate it to give the root a heading.')
                    goal['heading'] = [round(v, 6) for v in heading.normalized()]
                if marker.root_height:
                    goal['height'] = True
            else:
                rest = actor.data.bones[BONES[marker.kind]].matrix_local.to_3x3()
                native = rig.CI @ rotation.to_matrix() @ rest.inverted() @ rig.C
                goal['rotation'] = [[round(v, 6) for v in row] for row in native]
            goals.append(goal)
    return goals


def matches(context, settings, block, source):
    if SIGNATURE not in source:
        return True
    try:
        goals = sample(context, settings, block.start, block.end)
    except (ValueError, RuntimeError, ReferenceError):
        return False
    return (not goals or (block.start, block.end) == (source['start'], source['end'])) and stamp(goals) == source[SIGNATURE]


def draw_sidebar(layout, context):
    settings = rig_store.settings(context.scene)
    marker = active(settings)
    if marker is None:
        return
    box = layout.box()
    box.label(text=f'Object Constraints · Frame {marker.frame}', icon='CONSTRAINT')
    count = sum(item.frame == marker.frame for item in settings.object_constraints)
    box.template_list('TOYXYZ_UL_object_constraints', '', settings, 'object_constraints',
                      settings, 'active_object_constraint', rows=min(5, count), maxrows=5, sort_lock=True)
    box.prop(marker, 'frame')
    box.prop(marker, 'kind')
    box.prop_search(marker, 'target', context.scene, 'objects')
    if marker.kind == 'ROOT':
        box.prop(marker, 'root_heading')
        box.prop(marker, 'root_height')
