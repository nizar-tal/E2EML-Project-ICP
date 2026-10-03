# Nizar Talty
# Ishan Pathak

# 2/10/2026
# function to pre-process the images before OCR stages

from collections.abc import Mapping
from numbers import Real

import cv2
import numpy as np
from PIL import Image


CHANNEL_IDX={"red": 0, "green": 1, "blue": 2}


def convertRGB(image):
    # Convert dataset PIL image or RGB array into an independent array
    # might not need this even it has boilerplate or impacts latency
    if isinstance(image, Image.Image):
        return np.array(image.convert("RGB"), dtype=np.uint8)

    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a PIL image or a NumPy RGB array")
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("numpy images must have shape (H,W,3) and dtype uint8")
    return image.copy()


def get_number(value, name, minimum, maximum=None):
    # some safety check to make sure configs are valid:
    # rejct missing, nonnumeric, and out-of-range operation settings
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        limit = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise ValueError(f"{name} must be{limit}")
    return float(value)


def apply_enhancements(image, operations=None):
    # apply enhancement operations in order read from the config file

    result = convertRGB(image)
    if operations is None:
        return result
    if not isinstance(operations, (list, tuple)):
        raise TypeError("enhancement must be a list of operation objects")

    for operation in operations:
        if not isinstance(operation, Mapping):
            raise TypeError("each enhancement operation must be an object")
        kind = operation.get("type")

        if kind == "none":
            continue
        if kind == "brightness":
            amount=get_number(operation.get("amount"), "brightness amount", -255, 255)
            result=np.clip(result.astype(np.float32) + amount, 0, 255).astype(np.uint8)
        elif kind == "contrast":
            factor=get_number(operation.get("factor"), "contrast factor", 0)
            result=np.clip((result.astype(np.float32) - 127.5) * factor + 127.5, 0, 255).astype(np.uint8)
        elif kind == "sharpen":
            amount=get_number(operation.get("amount"), "sharpen amount", 0, 2)
            if amount:
                # some of these values are set as starting point and not included as part of config
                blurred = cv2.GaussianBlur(result, (0, 0), sigmaX=1.0)
                # Add back image detail that the blur removed
                result = cv2.addWeighted(result, 1 + amount, blurred, -amount, 0)
        else:
            raise ValueError(f"unknown enhancement type: {kind!r}")

    return result


def select_channels(image, c="original"):
    # here we choose which color channels from an RGB image for OCR

    # "original" returns RGB
    # one channel returns a 2D image
    # two or three channels return RGB with unselected channels set to zero

    rgb = convertRGB(image)
    if c == "original":
        return rgb
    if isinstance(c, str):
        c = [c]
    if not isinstance(c, (list, tuple)) or not c:
        raise ValueError("[warning] channels must be either 'original' or a nonempty list of color names")
    if any(channel not in CHANNEL_IDX for channel in c):
        raise ValueError("channel names must be red, green, or blue")
    if len(set(c)) != len(c):
        raise ValueError("channel names cannot repeat")

    indices = [CHANNEL_IDX[chan] for chan in c]
    if len(indices) == 1:
        return rgb[:, :, indices[0]].copy()

    s=np.zeros_like(rgb)
    s[:, :, indices] = rgb[:, :, indices]
    return s


def process_image(image, config):
    """Run the two image stages selected by one pipeline configuration."""
    if not isinstance(config, Mapping):
        raise TypeError("config must be an object")
    enhanced = apply_enhancements(image, config.get("enhancement", []))
    return select_channels(enhanced, config.get("channels", "original"))
