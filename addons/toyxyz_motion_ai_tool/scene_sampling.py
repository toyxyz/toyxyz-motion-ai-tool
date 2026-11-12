"""Keep consumers of the live pose out of temporary timeline evaluations."""

from contextlib import contextmanager
from functools import wraps

import bpy


SAMPLING = 'toyxyz_motion_ai.sampling_scenes'
APPLYING = 'toyxyz_motion_ai.committed_actors'


@contextmanager
def scope(key, scene, value):
    namespace = bpy.app.driver_namespace
    entries = namespace.setdefault(key, {})
    ident = scene.as_pointer()
    previous = entries.get(ident)
    entries[ident] = value
    try:
        yield
    finally:
        if previous is None:
            entries.pop(ident, None)
        else:
            entries[ident] = previous
        if not entries:
            namespace.pop(key, None)


def transient(function):
    @wraps(function)
    def wrapped(context, *args, **kwargs):
        with scope(SAMPLING, context.scene, True):
            return function(context, *args, **kwargs)
    return wrapped


def publish(context, obj):
    scene = context.scene
    with scope(APPLYING, scene, obj.as_pointer()):
        scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
        context.view_layer.update()
