from . import rig_store
"""Timeline presentation using the live Blender animation/theme settings.

Geometry follows Blender's scrubbing UI conventions. Native playback widgets are
drawn by bl_ui.space_time in timeline.py. No global editor theme is changed.
"""
import math
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from . import control_layers,keyframes,object_constraints

LANES=('Motion','Keyframes','Constraints')


def metrics(context):
    scale=context.preferences.system.ui_scale or 1.0
    s=rig_store.settings(context.scene)
    return dict(scale=scale,gutter=112*scale if s.timeline_show_channels else 0,
                ruler=23*scale,row=24*scale,scroll=12*scale,
                font=context.preferences.ui_styles[0].widget.points,
                pixel=max(1,context.preferences.system.ui_line_width))


def lane_layout(context):
    m=metrics(context);s=rig_store.settings(context.scene)
    layers=list(reversed(control_layers.rows(s.rig)))
    top=context.region.height-m['ruler']
    visible=max(1,math.floor((top-m['scroll'])/m['row']))
    limit=max(0,len(layers)+len(LANES)-visible) if layers else 0
    offset=min(s.timeline_lane_scroll,limit)
    return layers,top+offset*m['row'],offset,limit


def rgba(color,alpha=None):return tuple(color[:3])+(alpha if alpha is not None else color[3] if len(color)>3 else 1,)


def shade(color,offset,alpha=None):
    return tuple(max(0,min(1,v+offset/255)) for v in color[:3])+(alpha if alpha is not None else rgba(color)[3],)


def palette(context):
    theme=context.preferences.themes[0];d=theme.dopesheet_editor
    return dict(back=rgba(d.space.back),grid=rgba(d.grid),text=rgba(d.space.text),text_hi=rgba(d.space.header_text_hi),
                ruler=rgba(theme.regions.scrubbing.back),ruler_text=rgba(theme.regions.scrubbing.text),
                channels=rgba(theme.regions.channels.back),channel_text=rgba(theme.regions.channels.text),
                playhead=rgba(theme.common.anim.playhead),preview=rgba(theme.common.anim.preview_range),
                strip=rgba(theme.user_interface.wcol_regular.inner),strip_selected=rgba(theme.user_interface.wcol_list_item.inner_sel),
                strip_text=rgba(theme.user_interface.wcol_regular.text),strip_text_selected=rgba(theme.user_interface.wcol_list_item.text_sel),
                key=rgba(theme.common.anim.keyframe),key_selected=rgba(theme.common.anim.keyframe_selected),
                key_border=rgba(d.keyframe_border),key_border_selected=rgba(d.keyframe_border_selected),
                outline=rgba(theme.user_interface.wcol_regular.outline),scroll=rgba(theme.user_interface.wcol_scroll.item),
                scroll_back=rgba(theme.user_interface.wcol_scroll.inner),scroll_outline=rgba(theme.user_interface.wcol_scroll.outline))


def divisor(distance):
    values=[v for v in (2,3,5) if distance%v==0]
    return next((v for v in values if distance//v==2),values[0] if values else distance)


def grid_step(context):
    """Use FPS subdivisions and the user's native minimum 2D grid spacing."""
    s=rig_store.settings(context.scene);m=metrics(context)
    minimum=context.preferences.view.view2d_grid_spacing_min*m['scale']
    blf.size(0,m['font']*m['scale'])
    end=s.view_start+max(1,context.region.width-m['gutter'])/s.pixels_per_frame
    labels=[ruler_text(context.scene,abs(f),s.timeline_show_seconds) for f in (s.view_start,end)]
    minimum=max(minimum,max(blf.dimensions(0,value)[0] for value in labels)+6)
    distance=max(1,round(context.scene.render.fps/context.scene.render.fps_base))
    if distance*s.pixels_per_frame<=minimum:
        while distance*s.pixels_per_frame<minimum:distance*=2
    else:
        while distance>1:
            smaller=distance//divisor(distance)
            if smaller*s.pixels_per_frame<minimum:break
            distance=smaller
    return distance


def grid_layers(context):
    """Pinned View2D: opaque grid +16 shade for minor lines; no duplicate major=1 pass."""
    major=grid_step(context);minor=major/divisor(major);m=metrics(context);p=palette(context)
    layers=[]
    minimum=context.preferences.view.view2d_grid_spacing_min*m['scale']
    if major>1 and minor*rig_store.settings(context.scene).pixels_per_frame>minimum/5:
        layers.append((minor,shade(p['grid'],16)))
    layers.append((major,p['grid']))
    return layers


def playhead_geometry(context,x,text_width):
    """Pixel-aligned dimensions from the installed-version scrubbing UI conventions."""
    m=metrics(context);scale=m['scale'];outline=scale;pixel=m['pixel']
    top=math.trunc(context.region.height-m['ruler']);width=max(24*scale,text_width+8*scale)
    stalk_outline=outline
    if scale<.91:
        stalk_outline=1;left=math.floor(x)-1;right=left+pixel+2
    else:left=math.floor(x-pixel)-outline;right=math.floor(x+pixel+1)+outline
    y=math.floor(top+2*scale-outline);end=math.ceil(context.region.height-2*scale+outline)
    return dict(left=left,right=right,outline=outline,stalk_outline=stalk_outline,width=width+1,x=x-width/2,y=y,height=end-y,
                top=top,tip_top=math.ceil(top+2*scale),tip_bottom=math.ceil(top+2*scale)-6*scale,tip_half=6*scale)


def scrollbar(context):
    s=rig_store.settings(context.scene);m=metrics(context)
    x=m['gutter']+2*m['scale'];width=max(1,context.region.width-x-2*m['scale'])
    visible=max(1,context.region.width-m['gutter'])/s.pixels_per_frame
    layers=control_layers.rows(s.rig)
    left=min([context.scene.frame_start,s.view_start]+[b.start for b in s.blocks]+[strip.frame_start for _,strip in layers])
    right=max([context.scene.frame_end,s.view_start+visible]+[b.end for b in s.blocks]+[strip.frame_end for _,strip in layers])
    padding=max(1,(right-left)*.02);left-=padding;right+=padding
    a=x+(s.view_start-left)/(right-left)*width;b=x+(s.view_start+visible-left)/(right-left)*width
    return dict(x=x,width=width,left=left,right=right,a=a,b=b,visible=visible,y=2*m['scale'],height=8*m['scale'])


def frame_text(scene,frame,seconds=False):
    if seconds:
        return bpy.utils.smpte_from_frame(frame,fps=scene.render.fps,fps_base=scene.render.fps_base)
    return f'{frame:.2f}' if scene.show_subframe else str(round(frame))


def ruler_text(scene,frame,seconds=False):
    # Subframe display belongs to the playhead tag, not every integer ruler label.
    return frame_text(scene,frame,True) if seconds else str(int(frame))


def selection_outline(rectangle):
    """Native wm_gesture.cc box pattern: alternating 4px grey/white, 1px line.

    Batch each color once rather than issuing a GPU draw per dash.
    """
    a,b,c,d=rectangle;left,right=sorted((round(a),round(c)));bottom,top=sorted((round(b),round(d)))
    batches=[[],[]]
    if right<=left or top<=bottom:return batches
    for x,y,length,vertical in ((left,bottom,right-left,False),(left,top-1,right-left,False),
                                (left,bottom,top-bottom,True),(right-1,bottom,top-bottom,True)):
        for offset in range(0,max(0,length),4):
            span=min(4,length-offset)
            px=x if vertical else x+offset;py=y+offset if vertical else y
            w=1 if vertical else span;h=span if vertical else 1
            batches[(offset//4)%2].extend(((px,py),(px+w,py),(px+w,py+h),(px,py),(px+w,py+h),(px,py+h)))
    return batches


def draw(context,border=None,selection_box=None):
    s=rig_store.settings(context.scene);m=metrics(context);p=palette(context)
    w=context.region.width;h=context.region.height;scale=m['scale'];g=m['gutter'];row=m['row']
    top=max(0,math.trunc(h-m['ruler']));bottom=m['scroll'];pixel=m['pixel']
    if w<1 or h<1:return
    layers,lane_top,_,_=lane_layout(context)
    active_layer=control_layers.editing(s.rig)
    shader=gpu.shader.from_builtin('UNIFORM_COLOR')
    def shape(vertices,color):
        # BLF text drawing resets blending to NONE. Reassert it for every
        # primitive so later translucent overlays are actually composited.
        gpu.state.blend_set('ALPHA')
        shader.bind();shader.uniform_float('color',rgba(color))
        batch_for_shader(shader,'TRIS',{'pos':vertices}).draw(shader)
    def rect(x,y,width,height,color,radius=0):
        if width<=0 or height<=0:return
        if not radius:
            shape([(x,y),(x+width,y),(x+width,y+height),(x,y),(x+width,y+height),(x,y+height)],color);return
        radius=min(radius,width/2,height/2);outline=[]
        for cx,cy,start in ((x+radius,y+radius,180),(x+width-radius,y+radius,270),
                            (x+width-radius,y+height-radius,0),(x+radius,y+height-radius,90)):
            outline.extend((cx+radius*math.cos(math.radians(start+i*90/5)),cy+radius*math.sin(math.radians(start+i*90/5))) for i in range(6))
        vertices=[];center=(x+width/2,y+height/2)
        for i,point in enumerate(outline):vertices.extend((center,point,outline[(i+1)%len(outline)]))
        shape(vertices,color)
    def text(x,y,value,color,center=False,font=None):
        blf.size(0,(font or m['font'])*scale)
        if center:x-=blf.dimensions(0,value)[0]/2
        blf.color(0,*rgba(color));blf.position(0,x,y,0);blf.draw(0,value)
    viewport=gpu.state.viewport_get()
    def clip(x,y,width,height):
        # Scissor coordinates are framebuffer pixels; geometry remains region-local.
        gpu.state.scissor_test_set(True);gpu.state.scissor_set(viewport[0]+int(x),viewport[1]+int(y),max(1,int(width)),max(1,int(height)))
    def xof(frame):return g+(frame-s.view_start)*s.pixels_per_frame
    gpu.state.blend_set('ALPHA')
    try:
        rect(0,0,w,h,p['back'])
        clip(g,bottom,w-g,max(0,top-bottom))
        major=grid_step(context)
        for spacing,color in grid_layers(context):
            start=math.ceil(s.view_start/spacing)*spacing
            for i in range(max(0,math.ceil(((w-g)/s.pixels_per_frame+s.view_start-start)/spacing))):
                x=round(xof(start+i*spacing));rect(x,bottom,pixel,top-bottom,color)
        scene=context.scene
        # Native Timeline curtains and thin boundaries outside the scene range.
        outside=shade(p['back'],-25,155/255)
        left=max(g,min(w,xof(scene.frame_start)));right=max(g,min(w,xof(scene.frame_end)))
        rect(g,bottom,left-g,top-bottom,outside);rect(right,bottom,w-right,top-bottom,outside)
        for frame in (scene.frame_start,scene.frame_end):rect(round(xof(frame)),bottom,pixel,top-bottom,shade(p['back'],-60))
        for lane,(track,strip) in enumerate(layers):
            y=lane_top-(lane+1)*row
            x=xof(strip.frame_start);width=(strip.frame_end-strip.frame_start)*s.pixels_per_frame
            if x+width<g or x>w or y+row<=bottom or y>=top:continue
            selected=active_layer==(track,strip)
            fill=p['strip_selected'] if selected else p['strip']
            outline=p['strip_text_selected'] if selected else p['outline']
            rect(x,y+2*scale,width,row-4*scale,rgba(outline,.55 if track.mute else 1),2*scale)
            rect(x+pixel,y+2*scale+pixel,width-2*pixel,row-4*scale-2*pixel,rgba(fill,.4 if track.mute else 1),scale)
            if width>18*scale:
                grip=rgba(p['strip_text_selected'] if selected else p['strip_text'],.45)
                for edge in (x+3*scale,x+width-4*scale):rect(edge,y+8*scale,pixel,row-16*scale,grip)
            if min(w,x+width)-max(g,x)>8*scale:
                blf.enable(0,blf.CLIPPING);blf.clipping(0,max(g,x+4*scale),max(bottom,y),min(w,x+width),min(top,y+row))
                text(max(g+3*scale,x+7*scale),y+row/2-m['font']*scale*.38,strip.name,p['strip_text_selected'] if selected else p['strip_text'])
                blf.disable(0,blf.CLIPPING)
        for lane,name in enumerate(LANES):
            y=lane_top-(len(layers)+lane+1)*row
            if y+row<=bottom or y>=top:continue
            # Compact native-height rows; no permanently colored model bands.
            if lane==2:
                center=y+row/2;size=4*scale;active=object_constraints.active(s)
                grouped={}
                for marker in s.object_constraints:grouped.setdefault(marker.frame,[]).append(marker)
                frames=sorted(grouped)
                for index,frame in enumerate(frames):
                    x=xof(frame)
                    if x+size<g or x-size>w or center-size<=bottom:continue
                    markers=grouped[frame];selected=active is not None and active.frame==frame
                    color=p['key_selected'] if selected else p['key']
                    rect(x-size-pixel,center-size-pixel,2*(size+pixel),2*(size+pixel),p['key_border'])
                    rect(x-size,center-size,2*size,2*size,color)
                    label='+'.join(object_constraints.SHORT[m.kind] for m in markers)
                    label_left=max(g,x+size+3*scale)
                    label_right=min(w,xof(frames[index+1])-size-2*scale) if index+1<len(frames) else w
                    blf.size(0,9*scale)
                    if label and label_right-label_left>=blf.dimensions(0,label)[0]+2*scale:
                        blf.enable(0,blf.CLIPPING);blf.clipping(0,label_left,y,label_right,y+row)
                        text(label_left,center-3*scale,label,p['channel_text'],font=9)
                        blf.disable(0,blf.CLIPPING)
                continue
            if lane==1:
                center=y+row/2;radius=5*scale
                markers=keyframes.markers(s.rig)
                from . import pose_constraints
                for marker_index,(frame,selected) in enumerate(markers):
                    x=xof(frame)
                    if x+radius<g or x-radius>w or center-radius<=bottom:continue
                    for size,color in ((radius+pixel,p['key_border_selected'] if selected else p['key_border']),(radius,p['key_selected'] if selected else p['key'])):
                        shape([(x-size,center),(x,center-size),(x+size,center),(x-size,center),(x+size,center),(x,center+size)],color)
                    label_left=max(g,x+radius+3*scale)
                    label_right=min(w,xof(markers[marker_index+1][0])-radius-2*scale) if marker_index+1<len(markers) else w
                    label=pose_constraints.label(s.rig,frame)
                    blf.size(0,9*scale)
                    if label and label_right-label_left>=blf.dimensions(0,label)[0]+2*scale:
                        blf.enable(0,blf.CLIPPING);blf.clipping(0,label_left,y,label_right,y+row)
                        text(label_left,center-3*scale,label,p['channel_text'],font=9)
                        blf.disable(0,blf.CLIPPING)
                continue
            for index,b in enumerate(s.blocks):
                name={'kimodo':'Kimodo','motionbricks':'MotionBricks','ardy':'ARDY'}[b.engine]
                x=xof(b.start);width=(b.end-b.start)*s.pixels_per_frame
                if x+width<g or x>w or y+row<=bottom:continue
                selected=b.selected;fill=p['strip_selected'] if selected else p['strip']
                if not b.enabled:fill=rgba(fill,.4)
                outline=p['strip_text_selected'] if selected and index==s.active_block else p['outline']
                rect(x,y+2*scale,width,row-4*scale,outline,2*scale)
                rect(x+pixel,y+2*scale+pixel,width-2*pixel,row-4*scale-2*pixel,fill,scale)
                # Thin inset grips replace the previous full-height white end bars.
                grip=rgba(p['strip_text_selected'] if selected else p['strip_text'],.45)
                if width>18*scale:
                    for edge in (x+3*scale,x+width-4*scale):rect(edge,y+8*scale,pixel,row-16*scale,grip)
                value=b.prompt if b.engine in ('kimodo','ardy') and b.prompt else b.name
                value=name+' | '+value
                blf.enable(0,blf.CLIPPING);blf.clipping(0,max(g,x+6*scale),max(bottom,y),min(w,x+width-6*scale),y+row)
                text(max(g+3*scale,x+7*scale),y+row/2-m['font']*scale*.38,value,p['strip_text_selected'] if selected else p['strip_text'])
                blf.disable(0,blf.CLIPPING)
        if scene.use_preview_range:
            preview=shade(p['preview'],-25,max(0,p['preview'][3]-30/255))
            a=max(g,min(w,xof(scene.frame_preview_start)));b=max(g,min(w,xof(scene.frame_preview_end)))
            rect(g,bottom,a-g,top-bottom,preview);rect(b,bottom,w-b,top-bottom,preview)
        gpu.state.scissor_test_set(False)
        if g:
            rect(0,0,g,top,p['channels']);rect(g-pixel,0,pixel,top,p['grid'])
            clip(0,bottom,g,max(0,top-bottom))
            for lane,(track,strip) in enumerate(layers):
                y=lane_top-(lane+.5)*row-m['font']*scale*.38
                if bottom-row<y<top:
                    text(8*scale,y,strip.name,p['channel_text'],font=9)
                    text(g-26*scale,y,'Off' if track.mute else 'On',p['channel_text'],font=9)
            for lane,name in enumerate(LANES):
                text(8*scale,lane_top-(len(layers)+lane+.5)*row-m['font']*scale*.38,name,p['channel_text'])
            gpu.state.scissor_test_set(False)
        # Separate scrubbing strip uses the exact native region background/text.
        rect(0,top,w,h-top,p['ruler'])
        clip(g,top,w-g,h-top)
        first=math.ceil(s.view_start/major)*major
        for frame in range(first,math.ceil(s.view_start+(w-g)/s.pixels_per_frame)+major,major):
            text(xof(frame),top+m['ruler']/2-4*scale,ruler_text(scene,frame,s.timeline_show_seconds),p['ruler_text'],center=True)
        gpu.state.scissor_test_set(False)
        x=xof(scene.frame_current_final)
        if g<=x<=w:
            clip(g,bottom,w-g,h-bottom)
            value=frame_text(scene,scene.frame_current_final,s.timeline_show_seconds)
            blf.size(0,m['font']*scale);head=playhead_geometry(context,x,blf.dimensions(0,value)[0])
            outline=shade(p['back'],-20);edge=head['outline'];stalk=head['right']-head['left']
            rect(head['left'],bottom,stalk,top-bottom,outline)
            rect(head['left']+head['stalk_outline'],bottom,stalk-2*head['stalk_outline'],top-bottom,p['playhead'])
            a=head['tip_top'];b=head['tip_bottom'];half=head['tip_half']
            shape([(x-half-edge,a),(x+half+1+edge,a),(x+.5,b-edge)],outline)
            shape([(x-half,a),(x+half+1,a),(x+.5,b)],p['playhead'])
            rect(head['x'],head['y'],head['width'],head['height'],outline,4*scale)
            rect(head['x']+edge,head['y']+edge,head['width']-2*edge,head['height']-2*edge,p['playhead'],3*scale)
            text(x,top+m['ruler']/2-m['font']*scale*.38,value,p['text_hi'],center=True)
            gpu.state.scissor_test_set(False)
        # The dedicated viewport has its own functional scrollbar, never a fake native handle.
        bar=scrollbar(context);rect(g,0,w-g,bottom,p['back'])
        rect(bar['x'],bar['y'],bar['width'],bar['height'],p['scroll_back'],4*scale)
        rect(bar['a'],bar['y'],bar['b']-bar['a'],bar['height'],p['scroll_outline'],4*scale)
        rect(bar['a']+pixel,bar['y']+pixel,bar['b']-bar['a']-2*pixel,bar['height']-2*pixel,p['scroll'],3*scale)
        if border:
            clip(g,bottom,w-g,top-bottom)
            rect(min(border),bottom,abs(border[1]-border[0]),top-bottom,rgba(p['playhead'],.2))
        if selection_box:
            clip(g,bottom,w-g,top-bottom)
            a,b,c,d=selection_box;x=min(a,c);y=min(b,d);width=abs(c-a);height=abs(d-b)
            # Match Blender's native gesture box, independent of block highlight.
            rect(x,y,width,height,(1,1,1,.05))
            grey,white=selection_outline(selection_box)
            if grey:shape(grey,(.4,.4,.4,1))
            if white:shape(white,(1,1,1,1))
    finally:
        blf.disable(0,blf.CLIPPING);gpu.state.scissor_test_set(False);gpu.state.blend_set('NONE')
