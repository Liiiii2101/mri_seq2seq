import argparse
import os
import sys
import logging
import yaml
import random
from tqdm import tqdm
import numpy as np
import SimpleITK as sitk

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

import sys
sys.path.append('./src/')

from seq2seq.utils import torch_lpips, np_PSNR, np_SSIM
from seq2seq.dataloader.brats import Dataset_brats
from seq2seq.models.seq2seq import Generator


def test(args, net, device, dir_results):
    test_data = Dataset_brats(args, mode='test')
    test_loader = DataLoader(test_data, batch_size=1, shuffle=False, num_workers=2, pin_memory=True)

    c_in = args['seq2seq']['c_in']
    c_s = args['seq2seq']['c_s']
    valid_size = args['train']['valid_size']

    with open(os.path.join(dir_results, 'result_metrics.csv'), 'w') as f:
        f.write('name,src,tgt,psnr,ssim,lpips\n')
        
    with torch.no_grad():
        net.eval()
        with torch.no_grad():
            for batch in test_loader:
                img_t1 = batch['t1']
                img_t1ce = batch['t1ce']
                img_t2 = batch['t2']
                img_flair = batch['flair']
                #segs = batch['segs']
                path = batch['path'][0][0]
                name = os.path.basename(path)
                
                d = img_t1.shape[3]
                img_t1 = torch.cat([img_t1[:,:,:,i:d-c_in+i+1] for i in range(c_in)], dim=2)[0].permute(2,0,1,3,4)
                img_t1ce = torch.cat([img_t1ce[:,:,:,i:d-c_in+i+1] for i in range(c_in)], dim=2)[0].permute(2,0,1,3,4)
                img_t2 = torch.cat([img_t2[:,:,:,i:d-c_in+i+1] for i in range(c_in)], dim=2)[0].permute(2,0,1,3,4)
                img_flair = torch.cat([img_flair[:,:,:,i:d-c_in+i+1] for i in range(c_in)], dim=2)[0].permute(2,0,1,3,4)

                _, nw, nh = valid_size
                nd = 128

                d,t,c,w,h = img_t1.shape
                rd = (d-nd)//2 if d>nd else 0 #random.randint(0, d-nd-1) if d>nd else 0
                rw = (w-nw)//2 if w>nw else 0 #random.randint(0, w-nw-1) if w>nw else 0
                rh = (h-nh)//2 if h>nh else 0 #random.randint(0, h-nh-1) if h>nh else 0

                inputs = [
                    img_t1[rd:rd+nd,:,:,rw:rw+nw,rh:rh+nh].to(device=device, dtype=torch.float32),
                    img_t1ce[rd:rd+nd,:,:,rw:rw+nw,rh:rh+nh].to(device=device, dtype=torch.float32),
                    img_t2[rd:rd+nd,:,:,rw:rw+nw,rh:rh+nh].to(device=device, dtype=torch.float32),
                    img_flair[rd:rd+nd,:,:,rw:rw+nw,rh:rh+nh].to(device=device, dtype=torch.float32),
                ]

                for tgt in range(4):
                    target_img = inputs[tgt]
                    md = 0
                    for src in range(4):
                        source_img = inputs[src]
                        target_code = torch.from_numpy(np.array([1 if i==tgt else 0 for i in range(c_s)])).reshape((1,c_s)).to(device=device, dtype=torch.float32)
                        output_target = net(source_img, target_code, n_outseq=target_img.shape[1])
                        
                        tgtimg = target_img[:,0,1].cpu().numpy()
                        preimg = output_target[:,0,1].cpu().numpy()
                        md += np.abd(preimg-tgtimg)

                    md = md / 4
                        
                    dir_pred = os.path.join(dir_results, 'md')
                    os.makedirs(dir_pred, exist_ok=True)
                    sitk.WriteImage(sitk.GetImageFromArray(tgtimg), os.path.join(dir_pred, '{}_tgt_{}.nii.gz'.format(name, tgt)))
                    sitk.WriteImage(sitk.GetImageFromArray(md), os.path.join(dir_pred, '{}_md_{}.nii.gz'.format(name, tgt)))
                        
                        
def get_args():
    parser = argparse.ArgumentParser(description='Calculate M_d',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', '--config', dest='config', type=str, default='config/seq2seq_brats_2d_missing.yaml',
                        help='config file')
    parser.add_argument('-l', '--load', dest='load', type=str, default=None,
                        help='Load model from a .pth file')
    parser.add_argument('-d', '--device', dest='device', type=str, default='cpu',
                        help='cuda or cpu')
    parser.add_argument('-o', '--output', dest='output', type=str, default=None,
                        help='output')
    
    return parser.parse_args()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    args = get_args()
    
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    dir_output = args.output
    if not os.path.exists(dir_output):
        os.makedirs(dir_output)

    device = torch.device(args.device)
    logging.info(f'Using device {device}')

    net = Generator(config)
    net.to(device=device)

    if args.load:
        load_dict = torch.load(args.load, map_location=device)
        net.load_state_dict(load_dict)
        print('[*] Load model from', args.load)
    
    try:
        test(
            config,
            net=net,
            device=device,
            dir_results=dir_output,
        )
    except KeyboardInterrupt:
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)