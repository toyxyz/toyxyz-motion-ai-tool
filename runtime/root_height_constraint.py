"""Bridge-local Root2D extension using the models' existing root_y_pos condition.

Keep the native Root2D identity for stock postprocessing, without introducing
full-body joint/rotation goals or changing the vendored engine source files.
"""
_classes={}


def height_errors(data,roots):
    from motion_bridge_protocol import model_frame_index
    start=data['blocks'][0]['start'];end=data['blocks'][-1]['end'];result=[]
    for pose in data['poses']:
        if not pose.get('root_height'):continue
        index=model_frame_index(pose['frame'],start,end,data['fps'])
        target=float(pose['object_goal']['position'][1] if 'object_goal' in pose else pose['root'][1]);actual=float(roots[index][1])
        result.append(dict(frame=pose['frame'],model_frame=index,target_height_m=target,actual_height_m=actual,error_m=abs(actual-target)))
    return result


def with_height(base):
    if base in _classes:return _classes[base]

    class RootWithHeight(base):
        def __init__(self,skeleton,frame_indices,root_2d,root_height,global_root_heading=None):
            super().__init__(skeleton,frame_indices,root_2d,global_root_heading=global_root_heading)
            if root_height.shape!=(len(frame_indices),):raise ValueError('Root height needs one scalar per target frame.')
            self.root_y_pos=root_height

        def update_constraints(self,data_dict,index_dict):
            super().update_constraints(data_dict,index_dict)
            data_dict['root_y_pos'].append(self.root_y_pos)
            index_dict['root_y_pos'].append(self.frame_indices)
            if hasattr(self,'smooth_root_2d'):
                # Kimodo decodes hips from local_joints_positions, whose Y is
                # absolute, rather than from the smooth-root height channel.
                # Constrain only the Hips position; no other joints or rotations.
                import torch
                hips=torch.stack((self.smooth_root_2d[:,0],self.root_y_pos,self.smooth_root_2d[:,1]),dim=-1)
                indices=torch.stack((self.frame_indices,torch.full_like(self.frame_indices,self.skeleton.root_idx)),dim=-1)
                data_dict['global_joints_positions'].append(hips)
                index_dict['global_joints_positions'].append(indices)

        def crop_move(self,start,end):
            mask=(self.frame_indices>=start)&(self.frame_indices<end)
            points=getattr(self,'smooth_root_2d',None)
            if points is None:points=self.root_2d
            heading=self.global_root_heading[mask] if self.global_root_heading is not None else None
            return type(self)(self.skeleton,self.frame_indices[mask]-start,points[mask],self.root_y_pos[mask],heading)

        def to(self,device=None,dtype=None):
            parent=getattr(super(),'to',None)
            if parent is not None:parent(device=device,dtype=dtype)
            else:
                self.root_2d=self.root_2d.to(device=device,dtype=dtype)
                self.frame_indices=self.frame_indices.to(device=device)
                if self.global_root_heading is not None:self.global_root_heading=self.global_root_heading.to(device=device,dtype=dtype)
            self.root_y_pos=self.root_y_pos.to(device=device,dtype=dtype)
            return self

        def get_save_info(self):return dict(super().get_save_info(),root_y_pos=self.root_y_pos)

    _classes[base]=RootWithHeight
    return RootWithHeight
