import gc
import json
import os
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projects"
VIDEO_EXTS = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m4v", ".ts"}
DEFAULT_MIN_HEIGHT = 0.5


def load_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def plain_name(name) -> bool:
    return bool(name) and Path(name).name == name and name not in (".", "..")


def inside(path, folder) -> bool:
    return Path(path).resolve().is_relative_to(Path(folder).resolve())


def setup_runtime():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    warnings.filterwarnings("ignore", category=UserWarning)
    from huggingface_hub.utils import logging as hf_logging
    hf_logging.set_verbosity_error()

    import onnxruntime as ort
    try:
        ort.preload_dlls()
    except Exception:
        pass
    gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    print(f"[runtime] onnxruntime {ort.__version__} - {'GPU (CUDA)' if gpu else 'CPU only (slow)'}")


def release_models():
    for name, module in list(sys.modules.items()):
        if name.startswith(("imgutils", "alds.")) and module is not None:
            for value in list(vars(module).values()):
                if callable(getattr(value, "cache_clear", None)):
                    value.cache_clear()
    gc.collect()


class Project:
    def __init__(self, name: str):
        self.name = name
        self.dir = PROJECTS_DIR / name
        self.frames_dir = self.dir / "frames"
        self.scan_dir = self.dir / "scan"
        self.clusters_dir = self.dir / "clusters"
        self.chars_dir = self.dir / "characters"
        self.previews_dir = self.dir / "previews"

    def path(self, rel: str) -> Path:
        return self.dir / rel

    def load(self, rel: str, default=None):
        return load_json(self.dir / rel, default)

    def save(self, rel: str, data):
        save_json(self.dir / rel, data)

    def char_dir(self, name: str) -> Path:
        return self.chars_dir / safe_name(name)

    def preview_dir(self, name: str) -> Path:
        return self.previews_dir / safe_name(name)

    def require_frames(self):
        if self.load("project.json", {}).get("frames_deleted"):
            raise SystemExit("frames of this project were deleted to save space - restore them first with "
                             f"alds.bat restore-frames -p {self.name}")


def frame_in_use(f) -> bool:
    return not f.get("auto") and not f.get("deleted")


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", s).strip("_") or "character"


def parse_time(s: str) -> float:
    parts = [float(p) for p in s.strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def mmss(sec) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def parse_ranges(specs):
    out = []
    for spec in specs or []:
        for chunk in spec.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            a, b = chunk.split("-")
            out.append((parse_time(a), parse_time(b)))
    return out


def box_area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def box_iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def inside_ratio(inner, outer):
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    a = box_area(inner)
    return inter / a if a > 0 else 0.0


def expand_box(box, factor, W, H, square=False, shift_y=0.0):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + shift_y * h
    if square:
        w = h = max(w, h)
    w, h = w * factor, h * factor
    nx0, ny0 = max(0, cx - w / 2), max(0, cy - h / 2)
    nx1, ny1 = min(W, cx + w / 2), min(H, cy + h / 2)
    return [int(round(nx0)), int(round(ny0)), int(round(nx1)), int(round(ny1))]
