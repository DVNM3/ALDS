import hashlib
import os
import pickle
import shutil

import numpy as np

from .cancel import check as check_cancel

VERSION = 1
MAX_REF_SETS = 8
PNG_LEVEL = 3


def digest(*arrays) -> str:
    h = hashlib.sha1()
    for a in arrays:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def file_hash(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with open(path, "rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            check_cancel()
            h.update(chunk)
    return h.hexdigest()


def unlinked(folder, pattern="*"):
    return [f for f in folder.glob(pattern) if f.stat().st_nlink == 1] if folder.exists() else []


class CropCache:
    def __init__(self, project, fresh=False):
        self.dir = project.dir / "cache"
        self.file = self.dir / "crops.pkl"
        self.img_dir = self.dir / "images"
        self.entries, self.matches, self.central = {}, {}, {}
        self.computed = 0
        self.fresh, self.made, self.discarded = fresh, set(), False
        data = None
        if self.file.exists() and not fresh:
            try:
                data = pickle.loads(self.file.read_bytes())
            except Exception:
                pass
        if data and data.get("version") == VERSION:
            self.entries, self.matches, self.central = data["entries"], data["matches"], data["central"]
        elif not fresh:
            shutil.rmtree(self.dir, ignore_errors=True)

    def entry(self, det, frame):
        sig = (frame["file"], tuple(det["box"]), tuple(det["head"]) if det["head"] else None)
        e = self.entries.get(det["id"])
        if e is None or e["sig"] != sig:
            if e is not None:
                for f in self.img_dir.glob(f"{det['id']}_*"):
                    f.unlink()
            e = self.entries[det["id"]] = {"sig": sig, "crops": {}, "poses": {}}
        return e

    def get(self, rec, key, compute):
        if key not in rec:
            rec[key] = compute()
            self.computed += 1
        return rec[key]

    def scores(self, key, ids, compute):
        known = self.matches.pop(key, {})
        missing = [i for i in ids if i not in known]
        if missing:
            known.update(zip(missing, compute(missing).tolist()))
            self.computed += 1
        self.matches[key] = known
        for old in list(self.matches)[:-MAX_REF_SETS]:
            del self.matches[old]
        return np.array([known[i] for i in ids], np.float32)

    def image(self, det_id, ctype, size, compute):
        p = self.img_dir / f"{det_id}_{ctype}_{size}.png"
        if not p.exists() or (self.fresh and p not in self.made):
            self.img_dir.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.stem + ".tmp.png")
            compute().save(tmp, compress_level=PNG_LEVEL)
            tmp.replace(p)
            self.made.add(p)
            self.computed += 1
        return p

    def discard(self):
        self.discarded = True
        for p in self.made:
            p.unlink(missing_ok=True)
        for folder in (self.img_dir, self.dir):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

    def save(self):
        if self.discarded:
            return
        if self.fresh:
            for f in self.img_dir.glob("*.png") if self.img_dir.exists() else ():
                if f not in self.made:
                    f.unlink()
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps({"version": VERSION, "entries": self.entries, "matches": self.matches,
                                      "central": self.central}, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(self.file)


def unused_images(project):
    return unlinked(project.dir / "cache" / "images", "*.png")


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
