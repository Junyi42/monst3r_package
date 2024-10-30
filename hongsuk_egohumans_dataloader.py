import torch
from torch.utils.data import Dataset, DataLoader
import numpy as np
import os
import json
import cv2
import glob
import PIL
from PIL import Image
import pickle

from dust3r.utils.image import load_images as dust3r_load_images

class EgoHumansDataset(Dataset):
    def __init__(self, data_root, split='train', subsample_rate=10, cam_names=None):
        """
        Args:
            data_root (str): Root directory of the dataset
            split (str): 'train', 'val', or 'test'
        """
        self.data_root = data_root 
        self.split = split
        self.dust3r_image_size = 512
        self.subsample_rate = subsample_rate

        # choose camera names
        if cam_names is None:
            self.camera_names = ['cam01', 'cam02', 'cam03', 'cam04']
        else:
            self.camera_names = cam_names
        # choose only one sequence for testing
        self.selected_small_seq_name = ''  # ex) 001_tagging

        # Load dataset metadata and create sample list
        self._load_annot_paths_and_cameras()
        self.datalist = self._load_dataset_info()
        print(f'Successfully loaded {len(self.datalist)} multiviewsamples')


    def _load_annot_paths_and_cameras(self):
        self.big_seq_list = sorted(glob.glob(os.path.join(self.data_root, '*')))
        self.small_seq_list = []
        self.small_seq_annot_list = []
        self.cameras = {}
        for big_seq in self.big_seq_list:
            small_seq_list = sorted(glob.glob(os.path.join(big_seq, '*')))
            
            for small_seq in small_seq_list:
                small_seq_name = os.path.basename(small_seq)
                if self.selected_small_seq_name != '' and small_seq_name != self.selected_small_seq_name:
                    continue
                try:
                    with open(os.path.join(small_seq, 'parsed_annot_hongsuk.pkl'), 'rb') as f:
                        annot = pickle.load(f)

                    self.cameras[small_seq_name] = annot['cameras']
                    # print(f'Successfully loaded annot for {small_seq}')
                    self.small_seq_list.append(small_seq_name)
                    self.small_seq_annot_list.append(os.path.join(small_seq, 'parsed_annot_hongsuk.pkl'))
                except:
                    print(f'Error loading annot for {small_seq}') # there is no smpl annot for this sequence

        """ Data Structure
        {
        num_frames: 
        , cameras: {
            camera_name1: {
                'cam2world_R': 
                'cam2world_t': 
                'K': 
                'img_width': 
                'img_height': 
            },
            ...
        }
        ,frame_data: [{
            world_data: 
                {
                    'human_name': {
                        'global_orient': 
                        'transl': 
                        'betas': 
                        'body_pose': 
                    }, 
                    ....
                }
            ]
        }]
        , per_view_2d_annot: {
            camera_name1: {
                'pose2d_annot_path_list': [],
                'bbox_annot_path_list': [],
            },
            camera_name2: {
                'pose2d_annot_path_list': [],
                'bbox_annot_path_list': [],
            },
            ...
        }

        } # end of dict
        """


    def _load_dataset_info(self):
        """Load and organize dataset information"""
        per_frame_data_list = []

        for small_seq, small_seq_annot in zip(self.small_seq_list, self.small_seq_annot_list):
            with open(small_seq_annot, 'rb') as f:
                annot = pickle.load(f)
        
            num_frames = annot['num_frames']

            for frame in range(num_frames):
                if frame % self.subsample_rate != 0:
                    continue

                per_frame_data = {
                    'sequence': small_seq,
                    'frame': frame
                }

                # add world smpl params data
                per_frame_data['world_data'] = annot['frame_data'][frame]['world_data'] # dictionrary of human names and their smpl params

                # add camera data
                per_frame_data['cameras'] = annot['cameras'] # dictionrary of camera names and their parameters
                
                # check whether the cameras.keys() are superset of the self.camera_names
                # if not, skip this frame
                selected_cameras = sorted([cam for cam in per_frame_data['cameras'].keys() if cam in self.camera_names ])
                if len(selected_cameras) != len(self.camera_names):
                    # print(f'Warning: {small_seq} does not have all the cameras in self.camera_names; skipping this frame')
                    continue
                
                # add 2d pose and bbox annot data
                per_frame_data['annot_and_img_paths'] = {}
                for camera_name in selected_cameras:
                    pose2d_annot_path = annot['per_view_2d_annot'][camera_name]['pose2d_annot_path_list'][frame] # numpy pickle
                    if len(annot['per_view_2d_annot'][camera_name]['bbox_annot_path_list']) > 0:
                        bbox_annot_path = annot['per_view_2d_annot'][camera_name]['bbox_annot_path_list'][frame] # numpy pickle
                    else:
                        bbox_annot_path = None
                    img_path = pose2d_annot_path.replace('processed_data/poses2d', 'exo').replace('rgb', 'images').replace('npy', 'jpg')

                    per_frame_data['annot_and_img_paths'][camera_name] = {
                        'pose2d_annot_path': pose2d_annot_path,
                        'bbox_annot_path': bbox_annot_path,
                        'img_path': img_path
                    }
                    # do this in __getitem__
                    # pose2d_annot = np.load(pose2d_annot_path, allow_pickle=True)
                    # bbox_annot = np.load(bbox_annot_path, allow_pickle=True)

                per_frame_data_list.append(per_frame_data)

        return per_frame_data_list
    
    def __len__(self):
        return len(self.datalist)
    
    def __getitem__(self, idx):
        sample = self.datalist[idx]
        seq = sample['sequence']
        frame = sample['frame']

        # get camera parameters
        cameras = self.cameras[seq] # include all cameras' extrinsics and intrinsics
        # filter camera names that exist in both self.camera_names and cameras
        selected_cameras = sorted([cam for cam in cameras.keys() if cam in self.camera_names])

        # load image
        multiview_images = {}
        img_path_list = [sample['annot_and_img_paths'][cam]['img_path'] for cam in selected_cameras]
        dust3r_input_imgs = dust3r_load_images(img_path_list, size=self.dust3r_image_size, verbose=False)
        # squeeze the batch dimension
        new_dust3r_input_imgs = []
        for dust3r_input_img in dust3r_input_imgs:
            new_dust3r_input_img = {}
            for key in ['img', 'true_shape']: # dict_keys(['img', 'true_shape', 'idx', 'instance'])
                new_dust3r_input_img[key] = dust3r_input_img[key][0]    
            new_dust3r_input_imgs.append(new_dust3r_input_img)

        multiview_images = {cam: new_dust3r_input_imgs[i] for i, cam in enumerate(selected_cameras)}
        multiview_affine_transforms = {cam: get_dust3r_affine_transform(img_path, size=self.dust3r_image_size) for cam, img_path in zip(selected_cameras, img_path_list)}

        multiview_multiple_human_2d_cam_annot = {}
        for camera_name in selected_cameras:
            # Load image if it exists
            img_path = sample['annot_and_img_paths'][camera_name]['img_path']
            if os.path.exists(img_path):
                # load 2d pose annot
                pose2d_annot_path = sample['annot_and_img_paths'][camera_name]['pose2d_annot_path']
                pose2d_annot = np.load(pose2d_annot_path, allow_pickle=True)

                # load bbox annot
                bbox_annot_path = sample['annot_and_img_paths'][camera_name]['bbox_annot_path']
                if bbox_annot_path is not None:
                    bbox_annot = np.load(bbox_annot_path, allow_pickle=True)
                else:
                    bbox_annot = None

                # Store annotations for this camera
                multiview_multiple_human_2d_cam_annot[camera_name] = {}
                for human_idx in range(len(pose2d_annot)):
                    if 'is_valid' in pose2d_annot[human_idx] and not pose2d_annot[human_idx]['is_valid']:
                        continue

                    human_name = pose2d_annot[human_idx]['human_name']
                    pose2d = pose2d_annot[human_idx]['keypoints']
                    if bbox_annot is not None:
                        bbox = bbox_annot[human_idx]['bbox']
                    else:
                        bbox = pose2d_annot[human_idx]['bbox']
                    
                    multiview_multiple_human_2d_cam_annot[camera_name][human_name] = {
                        'pose2d': pose2d,
                        'bbox': bbox
                    }

        # load 3d world annot
        world_multiple_human_3d_annot = {}
        for human_name in sample['world_data'].keys():
            world_multiple_human_3d_annot[human_name] = sample['world_data'][human_name]

        # Load all required data
        data = {
            'multiview_images': multiview_images,
            'multiview_affine_transforms': multiview_affine_transforms,
            'multiview_multiple_human_2d_cam_annot': multiview_multiple_human_2d_cam_annot,
            'world_multiple_human_3d_annot': world_multiple_human_3d_annot,
            'sequence': seq,
            'frame': frame
        }

        return data

# get the affine transform matrix from cropped image to original image
# this is just to get the affine matrix (crop image to original image) - Hongsuk
def get_dust3r_affine_transform(file, size=512, square_ok=False):
    img = PIL.Image.open(file)
    original_width, original_height = img.size
    
    # Step 1: Resize
    S = max(img.size)
    if S > size:
        interp = PIL.Image.LANCZOS
    else:
        interp = PIL.Image.BICUBIC
    new_size = tuple(int(round(x*size/S)) for x in img.size)
    
    # Calculate center of the resized image
    cx, cy = size // 2, size // 2

    # Step 2: Crop
    halfw, halfh = ((2*cx)//16)*8, ((2*cy)//16)*8
    if not square_ok and new_size[0] == new_size[1]:
        halfh = 3*halfw//4
        
    # Calculate the total transformation
    scale_x = new_size[0] / original_width
    scale_y = new_size[1] / original_height
    
    translate_x = (cx - halfw) / scale_x
    translate_y = (cy - halfh) / scale_y
    
    affine_matrix = np.array([
        [1/scale_x, 0, translate_x],
        [0, 1/scale_y, translate_y]
    ])
    
    return affine_matrix



def create_dataloader(data_root, batch_size=8, split='train', num_workers=4, subsample_rate=10, cam_names=None):
    """
    Create a dataloader for the multiview human dataset
    
    Args:
        data_root (str): Root directory of the dataset
        batch_size (int): Batch size for the dataloader
        split (str): 'train', 'val', or 'test'
        num_workers (int): Number of workers for data loading
        
    Returns:
        DataLoader: PyTorch dataloader for the dataset
    """
    dataset = EgoHumansDataset(
        data_root=data_root,
        split=split,
        subsample_rate=subsample_rate,
        cam_names=cam_names
    )
    
    dataloader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=(split == 'train'),
        num_workers=num_workers,
        pin_memory=True,
    )
    
    return dataloader


if __name__ == '__main__':
    data_root = '/home/hongsuk/projects/egohumans/data'
    dataloader = create_dataloader(data_root, batch_size=1, split='test', num_workers=4)
    for data in dataloader:
        print(data.keys())
        import pdb; pdb.set_trace()
        break