"""Per-boundary overlap on the pinned official multi-prompt implementation.

Only the overlap assignment is adapted in memory on this worker's model instance.
The upstream engine source, transition constraints and postprocessing stay intact.
"""
import ast
import inspect
import textwrap
import types
from contextlib import contextmanager


@contextmanager
def transition_frames(model,frames,previous_motion=None):
    original=model._multiprompt
    if len(frames)<2 and previous_motion is None:
        yield
        return
    function=original.__func__;tree=ast.parse(textwrap.dedent(inspect.getsource(function)))
    class Adapt(ast.NodeTransformer):
        count=0;seeds=0
        def visit_Assign(self,node):
            if (len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='nb_transition_frames'
                and isinstance(node.value,ast.Name) and node.value.id=='num_transition_frames'):
                self.count+=1
                value=ast.Assign(targets=[ast.Name(id='num_transition_frames',ctx=ast.Store())],
                    value=ast.Subscript(value=ast.Name(id='_toyxyz_transition_frames',ctx=ast.Load()),slice=ast.Name(id='idx',ctx=ast.Load()),ctx=ast.Load()))
                return [ast.copy_location(value,node),node]
            if (len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='generated_motions'
                and isinstance(node.value,ast.List) and not node.value.elts):
                self.seeds+=1
                if previous_motion is not None:
                    node.value=ast.List(elts=[ast.Name(id='_toyxyz_previous_motion',ctx=ast.Load())],ctx=ast.Load())
            return self.generic_visit(node)
    adapter=Adapt();tree=adapter.visit(tree)
    if adapter.count!=1 or adapter.seeds!=1:raise RuntimeError('The installed Kimodo sequence implementation changed; transition adapter requires review.')
    namespace=dict(function.__globals__,_toyxyz_transition_frames=tuple(frames),_toyxyz_previous_motion=previous_motion)
    filename=(inspect.getsourcefile(function) or '<kimodo>')+' [per-block transitions]'
    exec(compile(ast.fix_missing_locations(tree),filename,'exec'),namespace)
    model._multiprompt=types.MethodType(namespace[function.__name__],model)
    try:yield
    finally:model._multiprompt=original
