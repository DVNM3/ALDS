"""Shared helpers: runtime setup, project layout, JSON I/O and box math."""
import json
import os
import re
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projects"


def setup_runtime():
    """Quiet noisy libraries and make the pip-installed CUDA/cuDNN DLLs visible to ONNX Runtime."""
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


class Project:
    def __init__(self, name: str):
        self.name = name
        self.dir = PROJECTS_DIR / name
        self.frames_dir = self.dir / "frames"
        self.scan_dir = self.dir / "scan"
        self.clusters_dir = self.dir / "clusters"
        self.chars_dir = self.dir / "characters"

    def path(self, rel: str) -> Path:
        return self.dir / rel

    def load(self, rel: str, default=None):
        p = self.dir / rel
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, rel: str, data):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def char_dir(self, name: str) -> Path:
        return self.chars_dir / safe_name(name)

    def require_frames(self):
        """Extracted frames are needed to build or re-cluster; `clean --all` deletes them."""
        if self.load("project.json", {}).get("frames_deleted"):
            raise SystemExit("frames of this project were deleted to save space - scan the episodes "
                             "again in a new project to build or re-cluster")


def frame_in_use(f) -> bool:
    """Clustering and build skip frames inside an auto-detected OP/ED ("auto") and frames that would be used
    but whose file `clean` deleted ("deleted", set by repeats.py when a frame leaves the OP/ED)."""
    return not f.get("auto") and not f.get("deleted")


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", s).strip("_") or "character"


def parse_time(s: str) -> float:
    """'90', '1:30', '1:02:03' -> seconds."""
    parts = [float(p) for p in s.strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_ranges(specs):
    """['0:00-1:30', '21:50-23:40'] or ['0:00-1:30,21:50-23:40'] -> [(0, 90), (1310, 1420)]."""
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
    """Fraction of `inner` box that lies inside `outer`."""
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    a = box_area(inner)
    return inter / a if a > 0 else 0.0


def expand_box(box, factor, W, H, square=False, shift_y=0.0):
    """Grow a box around its center (optionally squared / shifted down by a fraction of its height), clamped to the frame."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + shift_y * h
    if square:
        w = h = max(w, h)
    w, h = w * factor, h * factor
    nx0, ny0 = max(0, cx - w / 2), max(0, cy - h / 2)
    nx1, ny1 = min(W, cx + w / 2), min(H, cy + h / 2)
    return [int(round(nx0)), int(round(ny0)), int(round(nx1)), int(round(ny1))]
