import torchvision.transforms as transforms
import torchvision.transforms.functional as F
import logging
import PIL.Image
import numpy as np

def get_transform(opt, for_val=False):
    transform_list = []

    if for_val:
        transform_list.append(transforms.Resize(
            opt.loadSize, interpolation=PIL.Image.LANCZOS))
        # patch discriminators have receptive field < whole image
        # so patch ensembling should use all patches in image
        transform_list.append(transforms.CenterCrop(opt.loadSize))

        # we can add other test time augmentations here
        if hasattr(opt, 'test_flip') and opt.test_flip:
            transform_list.append(transforms.RandomHorizontalFlip(p=1.0))
        if hasattr(opt, 'test_compression') and opt.test_compression:
            transform_list.append(JPEGCompression(opt.compression))
        if hasattr(opt, 'test_blur') and opt.test_blur:
            transform_list.append(Blur(opt.blur))
        if hasattr(opt, 'test_gamma') and opt.test_gamma:
            transform_list.append(Gamma(opt.gamma))
    else:
        transform_list.append(transforms.Resize(
            opt.loadSize, interpolation=PIL.Image.LANCZOS))
        transform_list.append(transforms.CenterCrop(opt.fineSize))

    transform_list.append(transforms.ToTensor())
    # transform_list.append(transforms.Normalize((0.5, 0.5, 0.5),
    #                                            (0.5, 0.5, 0.5)))
    transform = transforms.Compose(transform_list)
    print(transform)
    logging.info(transform)
    return transform

def get_mask_transform(opt, for_val=False):
    transform_list = []
    transform_list.append(transforms.Resize(
        opt.loadSize, interpolation=PIL.Image.LANCZOS))
    transform_list.append(transforms.CenterCrop(opt.fineSize))
    transform_list.append(transforms.ToTensor())
    
    transform = transforms.Compose(transform_list)
    return transform

### additional augmentations ### 

class JPEGCompression(object):
    def __init__(self, level):
        import albumentations as A
        self.level = level
        self.transform = A.augmentations.transforms.JpegCompression(p=1)

    def __call__(self, image):
        image_np = np.array(image)
        image_out = self.transform.apply(image_np, quality=self.level)
        image_pil = PIL.Image.fromarray(image_out)
        return image_pil

class Blur(object):
    def __init__(self, level):
        import albumentations as A
        self.level = level
        self.transform = A.Blur(blur_limit=(self.level, self.level), always_apply=True)

    def __call__(self, image):
        image_np = np.array(image)
        augmented = self.transform(image=image_np)
        image_pil = PIL.Image.fromarray(augmented['image'])
        return image_pil

class Gamma(object):
    def __init__(self, level):
        import albumentations as A
        self.level = level
        self.transform = A.augmentations.transforms.RandomGamma(p=1)

    def __call__(self, image):
        image_np = np.array(image)
        image_out = self.transform.apply(image_np, gamma=self.level/100)
        image_pil = PIL.Image.fromarray(image_out)
        return image_pil

