from pathlib import Path

from PIL import Image

from . import negatives
from .common import plain_name
from .txn import Transaction

FILE = "positives.npz"
IMAGES = "confirmed"


def load(char_dir):
    return negatives.load(char_dir, FILE)


def thumbnail(char_dir, name):
    if not plain_name(name):
        raise ValueError("invalid reference name")
    return Path(char_dir) / IMAGES / (name + ".jpg")


def transaction(char_dir, name):
    char_dir = Path(char_dir)
    return Transaction(char_dir, keep=[char_dir / FILE, char_dir / negatives.FILE, thumbnail(char_dir, name)],
                       remove_if_new=[char_dir / IMAGES])


def _drop(char_dir, name):
    negatives.remove(char_dir, name, FILE)
    thumbnail(char_dir, name).unlink(missing_ok=True)


def _confirm(char_dir, png, built):
    if png.stem not in load(char_dir)[0]:
        negatives.add(char_dir, png.stem, built[png.stem], FILE)
    image_path = thumbnail(char_dir, png.stem)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png) as source:
        image = source.convert("RGB")
        image.thumbnail((320, 320))
        image.save(image_path, quality=90)
    negatives.remove(char_dir, png.stem)


def _reject(char_dir, name, built):
    negatives.add(char_dir, name, built[name])
    _drop(char_dir, name)


def remove(char_dir, name):
    if name in load(char_dir)[0]:
        with transaction(char_dir, name):
            _drop(char_dir, name)


def confirm(char_dir, png):
    png = Path(png)
    built, _ = negatives.build_features(char_dir)
    if png.stem not in built and png.stem not in load(char_dir)[0]:
        return False
    with transaction(char_dir, png.stem):
        _confirm(char_dir, png, built)
    return True


def reject_image(char_dir, png):
    png = Path(png)
    built, _ = negatives.build_features(char_dir)
    if png.stem not in built:
        return None
    with transaction(char_dir, png.stem):
        _reject(char_dir, png.stem, built)
        return negatives.trash(char_dir, png)


def unreject(char_dir, png, dest_dir, reconfirm=False):
    png = Path(png)
    built, _ = negatives.build_features(char_dir)
    if reconfirm and png.stem not in built and png.stem not in load(char_dir)[0]:
        return None
    with transaction(char_dir, png.stem):
        negatives.remove(char_dir, png.stem)
        if reconfirm:
            _confirm(char_dir, png, built)
        return negatives.move_pair(png, dest_dir)
