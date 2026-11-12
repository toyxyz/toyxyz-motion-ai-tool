"""Read-only asset retention and one-time state recovery for withdrawn features."""
from . import rig_store
import json

DONE='toyxyz_legacy_state_restored_0241'


def decode(value):
    try:
        result=json.loads(value or '{}')
        return result if isinstance(result,dict) else {}
    except (TypeError,ValueError):return {}


def restore_foot_curves(scene):
    """Retain an old modifier's route as an ordinary block curve, once.

    Read only serialized ID properties; the removed modifier type is never
    registered. Keep historical settings, terrain objects and native animation.
    """
    import bpy
    restored=False
    for block in rig_store.settings(scene).blocks:
        if block.get('toyxyz_foot_curve_restored_0310'):continue
        records=block.get('modifiers')
        if records is None:continue
        for record in records:
            if not hasattr(record,'get'):continue
            if record.get('type','FOOT_CONTACT') not in ('FOOT_CONTACT',0) or not record.get('enabled',True):continue
            curve=record.get('curve')
            if isinstance(curve,bpy.types.Object) and curve.type=='CURVE' and curve.name in scene.objects:
                block.path_curve=curve;restored=True
            break
        block['toyxyz_foot_curve_restored_0310']=True
    return restored


def restore(scene):
    """Restore normal authoring without deleting old boxes, drafts or Actions."""
    s=rig_store.settings(scene)
    if s.get(DONE) or not any(name.startswith('primitive_') for name in s.keys()):return False
    old=decode(s.get('primitive_restore'));pending=decode(s.get('primitive_route_backup'))
    if old:
        if s.rig:
            for layer in scene.view_layers:
                try:s.rig.hide_set(bool(old.get('hidden',False)),view_layer=layer)
                except (RuntimeError,ValueError):pass
        scene.frame_start=old.get('start',scene.frame_start);scene.frame_end=old.get('end',scene.frame_end)
        scene.frame_set(old.get('frame',scene.frame_current),subframe=old.get('subframe',0))
        s.view_start=old.get('view_start',s.view_start);s.pixels_per_frame=old.get('ppf',s.pixels_per_frame)
    if pending:
        scene.frame_start=pending.get('frame_start',scene.frame_start);scene.frame_end=pending.get('frame_end',scene.frame_end)
    for block in s.blocks:
        plan=block.get('primitive_plan','')
        if not plan:continue
        # Existing generated strips stay ordinary native animation. Retain the
        # old identifiers as archival metadata; never regenerate stored routes.
        block['toyxyz_archived_primitive_plan']=plan
        if block.get('primitive_retired',False):block.enabled=True
        elif pending.get('new_id')==plan and not block.has_result:block.enabled=False
        for name in ('primitive_plan','primitive_retired'):
            if name in block:del block[name]
    s[DONE]=True
    return True
