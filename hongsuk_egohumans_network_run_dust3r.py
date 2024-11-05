import os
import numpy as np
import copy
import pickle
import PIL
import tyro
import tqdm
import pytz

from datetime import datetime
from pathlib import Path

from dust3r.inference import inference
from dust3r.image_pairs import make_pairs
from dust3r.utils.image import load_images

from hongsuk_egohumans_dataloader import create_dataloader


def main(output_path: str = './outputs/egohumans'):
    Path(output_path).mkdir(parents=True, exist_ok=True)

    # EgoHumans data
    # Fix batch size to 1 for now
    egohumans_data_root = './data/egohumans_data' #'/home/hongsuk/projects/egohumans/data'
    cam_names = None # ['cam01', 'cam02', 'cam03', 'cam04']
    num_of_cams = 6
    output_dir = f'./outputs/egohumans/dust3r_raw_outputs/num_of_cams{num_of_cams}'

    dataset, dataloader = create_dataloader(egohumans_data_root, batch_size=1, split='test', subsample_rate=10, cam_names=cam_names)

    # Dust3r parameters
    device = 'cuda'
    silent = False
    scenegraph_type = 'complete'
    winsize = 1
    refid = 0
    model_path = '/home/hongsuk/projects/SimpleCode/multiview_world/checkpoints/DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth'

    # get dust3r network model
    from dust3r.model import AsymmetricCroCo3DStereo
    model = AsymmetricCroCo3DStereo.from_pretrained(model_path).to(device)

    total_output = {}
    for i, sample in tqdm.tqdm(enumerate(dataloader), total=len(dataloader)):
        cam_names = sorted(sample['multiview_images'].keys())

        imgs = [sample['multiview_images'][cam_name] for cam_name in cam_names]
        affine_transforms = [sample['multiview_affine_transforms'][cam_name] for cam_name in cam_names]

        # for single view, make a pair with itself
        if len(imgs) == 1:
            imgs = [imgs[0], copy.deepcopy(imgs[0])]
            imgs[1]['idx'] = 1
        pairs = make_pairs(imgs, scene_graph=scenegraph_type, prefilter=None, symmetrize=True)
        print(f"Running DUSt3R network inference with {len(imgs)} images, scene graph type: {scenegraph_type}, {len(pairs)} pairs")
        output = inference(pairs, model, device, batch_size=1, verbose=not silent)

        # Save output
        to_save_data = {
            'affine_matrices': affine_transforms,
            'output': output,
            'img_names': (sample['sequence'], sample['frame'].tolist(), cam_names)
        }
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'{sample["sequence"][0]}_{sample["frame"].item()}.pkl')
        print(f'Saving output to {output_path}')
        with open(output_path, 'wb') as f:
            pickle.dump(to_save_data, f)


if __name__ == '__main__':
    tyro.cli(main)