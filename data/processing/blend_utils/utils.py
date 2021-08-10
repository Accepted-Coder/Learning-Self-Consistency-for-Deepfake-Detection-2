import os, errno, sys, shutil
from os.path import join, splitext, join, basename
from collections import OrderedDict
import numpy as np
import cv2


# define a dictionary that maps the indexes of the facial
# landmarks to specific face regions
FACIAL_LANDMARKS_IDXS = OrderedDict([  # 根据放入元素的先后顺序进行排序
	("mouth", (48, 68)),
	("right_eyebrow", (17, 22)),
	("left_eyebrow", (22, 27)),
	("right_eye", (36, 42)),
	("left_eye", (42, 48)),
	("nose", (27, 36)),
	("jaw", (0, 17))
])


def mkdir_p(path):
    try:
        os.makedirs(os.path.abspath(path))
    except OSError as exc: 
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise


def files(path, exts=None, r=False):
    if os.path.isfile(path):
        if exts is None or (exts is not None and splitext(path)[-1] in exts):
            yield path
    elif os.path.isdir(path):
        for p, _, fs in os.walk(path):
            for f in sorted(fs):
                if exts is not None:
                    if splitext(f)[1] in exts:
                        yield join(p, f)
                else:
                    yield join(p, f)
            if not r:
                break


def rect_to_bb(rect):

    # 采用dlib预测的边界并将其转换为通常使用OpenCV的格式（x，y，w，h）
	x = rect.left()
	y = rect.top()
	w = rect.right() - x
	h = rect.bottom() - y

	# return a tuple of (x, y, w, h)
	return (x, y, w, h)

def shape_to_np(shape, dtype="int"):
    if isinstance(shape, np.ndarray):
        return shape.astype(dtype)  # 默认把 float 转到 int64/32
    # initialize the list of (x, y)-coordinates
    coords = np.zeros((68, 2), dtype=dtype)

    # 在68-landmarks上循环并转换成（x，y）坐标的2元组
    for i in range(0, 68):
        coords[i] = (shape.part(i).x, shape.part(i).y)

    # return the list of (x, y)-coordinates
    return coords

if __name__ == "__main__":
    pass