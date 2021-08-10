# import dlib
from skimage import io
from skimage import transform as sktransform
import numpy as np
from matplotlib import pyplot as plt
import json
import os
import random
from PIL import Image
from imgaug import augmenters as iaa
from .processing.DeepFakeMask import dfl_full, facehull, components, extended
import cv2
import pickle
import tqdm
import torch
from torch.utils import data
from data.processing.blend_utils.faceBlending import Blender
from data.processing.aug_trans.aug_trans import Augmentator, data_transform
from .dataset_util import is_image_file
from data.processing.find_faces import find_face_landmark
from . import transforms
import elasticdeform


def drawLandmark(img, landmark):
    for (x, y) in landmark:
        cv2.circle(img, (int(x), int(y)), 1, (0, 0, 255), -1)
    return img


def generate_landmark_file(dir):
    images = []
    images_list = {}

    assert os.path.isdir(dir), '%s is not a valid directory' % dir
    cache = dir.rstrip('/') + '_landmark.pkl'
    if not os.path.isfile(cache):
        for root, _, fnames in sorted(os.walk(dir, followlinks=True)):
            for fname in fnames:
                if is_image_file(fname):
                    path = os.path.join(root, fname)
                    img = Image.open(path).convert('RGB')
                    face_hull = find_face_landmark(np.array(img))
                    if face_hull is None:
                        pass
                    else:
                        point_num = face_hull.shape[0]
                        face_hull = np.reshape(face_hull, [point_num, 2])
                        images.append(path)
                        images_list[fname] = face_hull
        fh = open(cache, 'wb')
        pickle.dump(images_list, fh)
    return cache


class I2GDataset(data.Dataset):
    def __init__(self, opt, dir_real, is_val=False):
        self.dir_real = dir_real
        landmark_record_filename = generate_landmark_file(self.dir_real)
        with open(landmark_record_filename, 'rb') as f:
            self.landmarks_record = pickle.load(f)
            self.data_list = list(self.landmarks_record.keys())
            self.data_size = len(self.data_list)
            if self.data_size > opt.max_dataset_size:
                self.data_list = random.sample(
                    self.data_list, opt.max_dataset_size)
                self.data_size = len(self.data_list)
        self.distortion = iaa.Sequential(
            [iaa.PiecewiseAffine(scale=(0.01, 0.05))])
        self.blender = Blender(
            ldmPath=None, dataPath=None, topk=100, selectNum=1, gaussianKernel=[31, 63], gaussianSigma=[7, 15], loader='cv', pixel_aug=None, spatial_aug=None
        )
        self.transform = transforms.get_transform(opt, for_val=is_val)
        self.mask_transform = transforms.get_mask_transform(
            opt, for_val=is_val)
        self.opt = opt

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, index):
        face_img, mask, is_forgery = self.gen_datapoint_from(
            self.data_list[index], self.opt.loadSize)
        # face_img = (face_img.transpose(2, 0, 1) / 255.).astype(np.float32)
        face_img = Image.fromarray(face_img)
        mask = Image.fromarray(np.uint8(mask * 255), 'L')

        face_img = self.transform(face_img)
        mask = self.mask_transform(mask)
        return_obj = {
            'img': face_img,
            'mask': mask,
            'label': is_forgery
        }

        return return_obj

    def total_euclidean_distance(self, a, b):
        assert len(a.shape) == 2
        return np.sum(np.linalg.norm(a-b, axis=1))

    def random_get_hull(self, landmark, img1):
        hull_type = random.choice([0, 1, 2, 3])
        if hull_type == 0:
            mask = dfl_full(landmarks=landmark.astype(
                'int32'), face=img1, channels=3).mask
            return mask/255
        elif hull_type == 1:
            mask = extended(landmarks=landmark.astype(
                'int32'), face=img1, channels=3).mask
            return mask/255
        elif hull_type == 2:
            mask = components(landmarks=landmark.astype(
                'int32'), face=img1, channels=3).mask
            return mask/255
        elif hull_type == 3:
            mask = facehull(landmarks=landmark.astype(
                'int32'), face=img1, channels=3).mask
            return mask/255

    def random_erode_dilate(self, mask, ksize=None):
        if random.random() > 0.5:
            if ksize is None:
                ksize = random.randint(1, 21)
            if ksize % 2 == 0:
                ksize += 1
            mask = np.array(mask).astype(np.uint8)*255
            kernel = np.ones((ksize, ksize), np.uint8)
            mask = cv2.erode(mask, kernel, 1)/255
        else:
            if ksize is None:
                ksize = random.randint(1, 5)
            if ksize % 2 == 0:
                ksize += 1
            mask = np.array(mask).astype(np.uint8)*255
            kernel = np.ones((ksize, ksize), np.uint8)
            mask = cv2.dilate(mask, kernel, 1)/255
        return mask

    def blendImages(self, src, dst, mask, featherAmount=0.2):

        maskIndices = np.where(mask != 0)

        maskPts = np.hstack(
            (maskIndices[1][:, np.newaxis], maskIndices[0][:, np.newaxis]))
        faceSize = np.max(maskPts, axis=0) - np.min(maskPts, axis=0)
        featherAmount = featherAmount * np.max(faceSize)

        hull = cv2.convexHull(maskPts)
        dists = np.zeros(maskPts.shape[0])
        for i in range(maskPts.shape[0]):
            dists[i] = cv2.pointPolygonTest(
                hull, (int(maskPts[i, 0]), int(maskPts[i, 1])), True)

        weights = np.clip(dists / featherAmount, 0, 1)

        composedImg = np.copy(dst)
        composedImg[maskIndices[0], maskIndices[1]] = weights[:, np.newaxis] * src[maskIndices[0],
                                                                                   maskIndices[1]] + (1 - weights[:, np.newaxis]) * dst[maskIndices[0], maskIndices[1]]

        return composedImg

    # borrow from https://github.com/MarekKowalski/FaceSwap

    def colorTransfer(self, src, dst, mask):
        transferredDst = np.copy(dst)

        maskIndices = np.where(mask != 0)

        maskedSrc = src[maskIndices[0], maskIndices[1]].astype(np.int32)
        maskedDst = dst[maskIndices[0], maskIndices[1]].astype(np.int32)

        meanSrc = np.mean(maskedSrc, axis=0)
        meanDst = np.mean(maskedDst, axis=0)

        maskedDst = maskedDst - meanDst
        maskedDst = maskedDst + meanSrc
        maskedDst = np.clip(maskedDst, 0, 255)

        transferredDst[maskIndices[0], maskIndices[1]] = maskedDst

        return transferredDst

    def gen_datapoint_from(self, background_face_path, size):
        # background_face_path = random.choice(self.data_list)
        data_type = 'real' if random.randint(0, 1) else 'fake'
        if data_type == 'fake':
            face_img, mask = self.get_blended_face(background_face_path, size)
            face_img = Image.fromarray(face_img)
            face_img = face_img.resize((size, size), Image.BILINEAR)
            face_img = np.array(face_img)
            mask = Image.fromarray(mask)
            mask = mask.resize((size, size), Image.BILINEAR)
            mask = np.array(mask)
            mask = 1 - mask
            # mask = (1 - mask) * mask * 4
        else:
            face_img = io.imread(os.path.join(
                self.dir_real, background_face_path))

            face_img = Image.fromarray(face_img)
            face_img = face_img.resize((size, size), Image.BILINEAR)
            face_img = np.array(face_img)

            mask = np.ones((size, size))

        # random jpeg compression after BI pipeline
        if random.randint(0, 1):
            quality = random.randint(60, 100)
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            face_img_encode = cv2.imencode('.jpg', face_img, encode_param)[1]
            face_img = cv2.imdecode(face_img_encode, cv2.IMREAD_COLOR)

        # random flip
        if random.randint(0, 1):
            face_img = np.flip(face_img, 1).copy()
            mask = np.flip(mask, 1).copy()

        return face_img, mask, int(data_type == 'real')

    def get_blended_face(self, background_face_path, size):
        background_face = io.imread(os.path.join(
            self.dir_real, background_face_path))
        background_landmark = self.landmarks_record[background_face_path]

        foreground_face_path = self.search_similar_face(
            background_landmark, background_face_path)
        foreground_face = io.imread(os.path.join(
            self.dir_real, foreground_face_path))

        # get random type of initial blending mask
        mask = self.random_get_hull(background_landmark, background_face)
        # # random deform mask

        # apply color transfer
        foreground_face = self.colorTransfer(
            background_face, foreground_face, mask*255)

        # blend two face
        blended_face = self.blendImages(
            foreground_face, background_face, mask*255)
        blended_face = blended_face.astype(np.uint8)

        mask = mask[:, :, 0:1]

        mask = elasticdeform.deform_random_grid(
            mask[:, :, 0], sigma=0.01, points=4)
        mask = cv2.GaussianBlur(mask, (15, 15), 5)

        return blended_face, mask

    def search_similar_face(self, this_landmark, background_face_path):
        min_dist = 99999999

        # random sample 5000 frame from all frams:
        # sample_num = int(self.data_size * 0.2)
        sample_num = 50
        all_candidate_path = random.sample(self.data_list, k=sample_num)

        # filter all frame that comes from the same video as background face
        all_candidate_path = filter(lambda x: x.split('_')[0] != background_face_path.split('_')[0], all_candidate_path)
        all_candidate_path = list(all_candidate_path)

        # loop throungh all candidates frame to get best match
        for candidate_path in all_candidate_path:
            candidate_landmark = self.landmarks_record[candidate_path].astype(
                np.float32)
            candidate_distance = self.total_euclidean_distance(
                candidate_landmark, this_landmark)
            if candidate_distance < min_dist:
                min_dist = candidate_distance
                min_path = candidate_path

        return min_path

