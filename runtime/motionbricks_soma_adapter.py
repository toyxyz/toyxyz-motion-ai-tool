"""Map canonical SOMA rotation deltas to MotionBricks' native joint frames.

Kimodo/canonical SOMA uses identity rotations in the neutral pose. MotionBricks
was trained with the joint frames of its shipped USD skeleton. Matching names
and world-space joint positions alone does not make local rotations compatible.
"""
import numpy as np
from scipy.spatial.transform import Rotation


class SOMAAdapter:
    def __init__(self,schema):
        import warp as wp
        from motionbricks.io.usd import load_skeleton_from_usd
        from motionbricks.io.utils import get_asset_file,SOMA_SKELETON_PRIM_PATH
        from motionbricks.animation.skeleton import Skeleton
        official=load_skeleton_from_usd(get_asset_file('human','soma_base_skel_minimal_no_root.usd'),SOMA_SKELETON_PRIM_PATH)
        names=schema['names'];parents=schema['parents'];indices=[official.joint_index(n) for n in names]
        if any(i<0 for i in indices):raise ValueError('MotionBricks SOMA joint names do not match the canonical skeleton.')
        for j,index in enumerate(indices):
            parent=official.joint_parent(index)
            if (official.joint_names[parent] if parent>=0 else None)!=(names[parents[j]] if parents[j]>=0 else None):
                raise ValueError('MotionBricks SOMA hierarchy does not match the canonical skeleton.')
        rest=official.reference_local_transforms.numpy()[indices]
        local=Rotation.from_quat(rest[:,3:]).as_matrix();basis=np.empty_like(local)
        for j,parent in enumerate(parents):basis[j]=basis[parent]@local[j] if parent>=0 else local[j]
        self.basis=basis
        self.parent_basis=np.stack([basis[p] if p>=0 else np.eye(3) for p in parents])
        neutral=np.asarray(schema['neutral_joints'],dtype=np.float64)
        offsets=np.stack([neutral[j]-neutral[p] if p>=0 else neutral[j] for j,p in enumerate(parents)])
        # Keep the shared canonical body proportions. Express each offset in its
        # parent's native frame so FK positions stay unchanged by the conversion.
        self.reference=np.zeros((len(names),7),dtype=np.float32)
        self.reference[:,:3]=np.einsum('nji,nj->ni',self.parent_basis,offsets)
        self.reference[:,3:]=Rotation.from_matrix(self.parent_basis.swapaxes(-1,-2)@basis).as_quat()
        self.skeleton=Skeleton(names,parents,self.reference)
        self.skeleton.up_axis=wp.vec3(0,1,0);self.skeleton.forward_axis=wp.vec3(0,0,1)

    def to_native(self,pose):
        local=np.asarray(pose['local_rotations'],dtype=np.float64)
        rotation=self.parent_basis.swapaxes(-1,-2)@local@self.basis
        result=self.reference.copy();result[0,:3]=pose['root']
        result[:,3:]=Rotation.from_matrix(rotation).as_quat()
        return result

    def to_canonical(self,poses):
        rotation=Rotation.from_quat(np.asarray(poses)[...,3:].reshape(-1,4)).as_matrix().reshape(*np.asarray(poses).shape[:-1],3,3)
        return self.parent_basis@rotation@self.basis.swapaxes(-1,-2)
