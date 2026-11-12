"""Direct editing of native SOMA pose keys in the dedicated timeline."""
from . import rig_store
import struct
import bpy
from bpy.props import IntProperty
from . import rig,keyframes,pose_constraints as pc,nla_motion

_live=None


def busy():return _live is not None
def selected(obj):return {frame for frame,on in keyframes.markers(obj,force=True) if on}
def keytime(value):return round(struct.unpack('f',struct.pack('f',value))[0],5)


def selection_snapshot(obj):
    return {(fc.as_pointer(),round(float(point.co.x),5)):
            (point.select_control_point,point.select_left_handle,point.select_right_handle)
            for fc in keyframes.curves(obj) for point in fc.keyframe_points}


def restore_selection(obj,values):
    for fc in keyframes.curves(obj):
        for point in fc.keyframe_points:
            state=values.get((fc.as_pointer(),round(float(point.co.x),5)))
            if state:point.select_control_point,point.select_left_handle,point.select_right_handle=state
    keyframes.clear()


def select(obj,frames):
    frames=set(frames)
    for fc in keyframes.curves(obj):
        for point in fc.keyframe_points:
            on=round(float(point.co.x),5) in frames
            point.select_control_point=point.select_left_handle=point.select_right_handle=on
    keyframes.clear()


def editable(obj,frames):
    rig.validate_rig(obj);animation=obj.animation_data;action,slot=rig.pose_action(obj)
    if animation and animation.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before editing pose keys.')
    if not action or not frames:raise ValueError('Select one or more pose keys in the Keyframes row.')
    if not getattr(action,'is_editable',True):raise ValueError('Make the user pose Action local before editing its keys.')
    if action.get(nla_motion.OWNER):raise ValueError('Use the user pose Action before editing pose keys.')
    for fc in keyframes.curves(obj,include_modes=True):
        if (fc.lock or (fc.group and fc.group.lock)) and any(round(float(point.co.x),5) in frames for point in fc.keyframe_points):
            raise ValueError('Unlock the selected pose F-Curves before editing their keys.')


def refresh(context):
    keyframes.clear();scene=context.scene
    scene.frame_set(scene.frame_current,subframe=scene.frame_subframe);context.view_layer.update()
    from . import timeline
    timeline.redraw_regions(scene,context.window_manager.windows)


class Move:
    def __init__(self,context,obj,frames):
        global _live
        if busy():raise ValueError('Finish the current pose-key edit first.')
        self.frames={round(float(at),5) for at in frames};editable(obj,self.frames)
        self.obj=obj;self.context=context;self.closed=False;self.delta=0;self.error=''
        self.action,self.slot=rig.pose_action(obj)
        self.stationary=set(keyframes.frames(obj,True))-self.frames
        self.records=[record for at in sorted(self.frames) for record in keyframes.begin_move(obj,at)]
        if not self.records:raise ValueError('The selected pose keys no longer exist.')
        from . import control_rig
        mode_paths=control_rig.mode_paths(obj)
        self.mode_stationary={fc.as_pointer():{keytime(point.co.x) for point in fc.keyframe_points}-self.frames
                              for fc,_,_,_,_ in self.records if fc.data_path in mode_paths}
        self.current={(fc.as_pointer(),round(float(co.x),5)):round(float(co.x),5) for fc,_,co,_,_ in self.records}
        self.ident=pc.begin_manual(obj);_live=self
    def place(self,delta):
        # Reacquire points by time on each preview. FCurve.update sorts its RNA
        # array, so stored point references cannot identify keys after crossing.
        lookups={};curves={};positions={};current={}
        for fc,_,co,left,right in self.records:
            pointer=fc.as_pointer();curves[pointer]=fc
            if pointer not in lookups:lookups[pointer]={round(float(p.co.x),5):p for p in fc.keyframe_points}
            original=round(float(co.x),5)
            point=lookups[pointer].get(self.current[pointer,original])
            if point is None:raise ValueError('A pose key changed during editing.')
            point.co=(co.x+delta,co.y);point.handle_left=(left.x+delta,left.y);point.handle_right=(right.x+delta,right.y)
            at=round(float(point.co.x),5);current[pointer,original]=at;positions[original]=at
        for fc in curves.values():fc.update()
        self.current=current;self.delta=delta
        return positions
    def preview(self,delta):
        if self.closed:raise ValueError('The pose-key edit ended.')
        if rig.pose_action(self.obj)!=(self.action,self.slot):raise ValueError('The user pose Action changed during editing.')
        delta=round(delta);destinations={keytime(float(co.x)+delta) for _,_,co,_,_ in self.records};collisions=destinations&self.stationary
        for fc,_,co,_,_ in self.records:
            at=keytime(float(co.x)+delta)
            if at in self.mode_stationary.get(fc.as_pointer(),()):collisions.add(at)
        if collisions:
            self.error=f'A pose already exists at frame {min(collisions):g}. Choose another frame.';return False
        if len(destinations)!=len(self.frames):self.error='Pose keys would overlap. Choose a smaller offset.';return False
        self.error=''
        positions=self.place(delta);pc.preview_manual(self.ident,self.frames,delta,positions=positions)
        refresh(self.context);return True
    def finish(self,commit=True):
        global _live
        if self.closed:return
        commit=commit and not self.error
        try:
            if not commit:self.place(0)
            pc.end_manual(self.ident,commit)
        except BaseException:
            pc.end_manual(self.ident,False);raise
        finally:
            self.closed=True;_live=None;refresh(self.context)


def delete(context,obj,frames):
    if busy():raise ValueError('Finish the current pose-key edit first.')
    frames={round(float(at),5) for at in frames};editable(obj,frames)
    ident=pc.begin_manual(obj)
    try:
        for fc in keyframes.curves(obj,include_modes=True):
            indices=[i for i,point in enumerate(fc.keyframe_points) if round(float(point.co.x),5) in frames]
            for index in reversed(indices):fc.keyframe_points.remove(fc.keyframe_points[index],fast=True)
            fc.update()
        pc.preview_manual(ident,frames,delete=True);pc.end_manual(ident,True)
    except BaseException:
        pc.end_manual(ident,False);raise
    refresh(context)


def abandon():
    global _live
    if _live:_live.closed=True
    _live=None


def cancel_live():
    if _live:_live.finish(False)


def header(context,text=None):
    if context.area:context.area.header_text_set(text)


class TOYXYZ_OT_move_pose_keys(bpy.types.Operator):
    bl_idname='toyxyz_motion_ai_tool.move_pose_keys';bl_label='Move Pose Keys';bl_options={'REGISTER','UNDO','BLOCKING'}
    bl_description='Move the selected pose keys and their constraint settings together'
    delta:IntProperty(name='Frame Offset',description='Move keys by this many frames. Negative values move them earlier.',default=0)
    @classmethod
    def poll(cls,context):
        from . import timeline
        return timeline.ours(context) and rig_store.settings(context.scene).selection=='POSE'
    def execute(self,context):
        move=None
        try:
            obj=rig_store.settings(context.scene).rig;move=Move(context,obj,selected(obj))
            if not move.preview(self.delta):
                message=move.error;move.finish(False);raise ValueError(message)
            move.finish();return {'FINISHED'}
        except ValueError as exc:
            if move and not move.closed:move.finish(False)
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
    def invoke(self,context,event):
        try:
            obj=rig_store.settings(context.scene).rig;self.move=Move(context,obj,selected(obj))
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        self.mouse_x=event.mouse_region_x;self.numeric='';self.delta=0
        header(context,'Move Pose Keys · Move mouse or type a frame offset · Enter: confirm · Esc: cancel')
        context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def modal(self,context,event):
        if self.move.closed:header(context);return {'CANCELLED'}
        if event.type in ('ESC','RIGHTMOUSE'):
            self.move.finish(False);header(context);return {'CANCELLED'}
        if event.value=='PRESS' and event.type in ('LEFTMOUSE','RET','NUMPAD_ENTER'):
            message=self.move.error;self.move.finish(not message);header(context)
            if message:self.report({'WARNING'},message);return {'CANCELLED'}
            return {'FINISHED'}
        if event.type=='MOUSEMOVE' and not self.numeric:
            self.delta=round((event.mouse_region_x-self.mouse_x)/rig_store.settings(context.scene).pixels_per_frame)
        elif event.value=='PRESS':
            digit={'ZERO':'0','ONE':'1','TWO':'2','THREE':'3','FOUR':'4','FIVE':'5','SIX':'6','SEVEN':'7','EIGHT':'8','NINE':'9'}.get(event.type)
            if digit is None and event.type.startswith('NUMPAD_') and event.type[-1:].isdigit():digit=event.type[-1]
            if digit is not None:self.numeric+=digit
            elif event.type in ('MINUS','NUMPAD_MINUS'):self.numeric=self.numeric[1:] if self.numeric.startswith('-') else '-'+self.numeric
            elif event.type=='BACK_SPACE':self.numeric=self.numeric[:-1]
            else:return {'RUNNING_MODAL'}
            self.delta=max(-1000000,min(1000000,int(self.numeric))) if self.numeric not in ('','-') else 0
        else:return {'RUNNING_MODAL'}
        try:self.move.preview(self.delta)
        except (ValueError,ReferenceError) as exc:
            self.move.finish(False);header(context);self.report({'WARNING'},str(exc));return {'CANCELLED'}
        header(context,self.move.error or f'Move Pose Keys · {self.delta:+d} frames · Enter: confirm · Esc: cancel')
        return {'RUNNING_MODAL'}
    def cancel(self,context):
        if hasattr(self,'move'):self.move.finish(False)
        header(context)


CLASSES=(TOYXYZ_OT_move_pose_keys,)
