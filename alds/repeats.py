from pathlib import Path

import av
import numpy as np
from tqdm import tqdm

from .cancel import check as check_cancel
from .common import VIDEO_EXTS, mmss

FP_RATE = 2.0
FLAT_STD = 4.0
MATCH_CORR = 0.75
MAX_GAP_S = 2.0
PIECE_S = 8.0
JOIN_GAP_S = 8.0
RECAP_SHIFT = 0.3


class Fingerprinter:
    def __init__(self):
        self.rows, self.cur, self.acc, self.n = [], -1, None, 0

    def add(self, t, thumb64x36):
        w = max(int(t * FP_RATE), self.cur)
        small = thumb64x36.reshape(9, 4, 16, 4).mean(axis=(1, 3))
        if w != self.cur:
            self._flush()
            self.cur, self.acc, self.n = w, small.copy(), 1
        else:
            self.acc += small
            self.n += 1

    def _flush(self):
        if self.cur < 0:
            return
        while len(self.rows) < self.cur:
            self.rows.append(np.zeros(144, np.float32))
        self.rows.append((self.acc / self.n).ravel())

    def result(self) -> np.ndarray:
        self._flush()
        self.cur = -1
        return np.array(self.rows, np.float16) if self.rows else np.zeros((0, 144), np.float16)


def fingerprint_video(path) -> np.ndarray:
    fp, covered = _fingerprint(path, skip="NONREF")
    if covered < 0.9:
        fp, _ = _fingerprint(path, skip=None)
    return fp


def _fingerprint(path, skip):
    fp, windows = Fingerprinter(), set()
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        if skip:
            s.codec_context.skip_frame = skip
        fps = float(s.average_rate or 24)
        duration = c.duration / av.time_base if c.duration else None
        with tqdm(total=round(duration) if duration else None, unit="s", desc="  fingerprint", leave=False) as bar:
            for n, frame in enumerate(c.decode(s)):
                check_cancel()
                t = float(frame.time) if frame.time is not None else n / fps
                fp.add(t, frame.reformat(width=64, height=36, format="gray").to_ndarray().astype(np.float32))
                windows.add(int(t * FP_RATE))
                bar.update(max(0, int(t) - bar.n))
    expected = int(duration * FP_RATE) if duration else len(windows)
    return fp.result(), len(windows) / max(expected, 1)


def _prep(F):
    F = F.astype(np.float32)
    F = F - F.mean(1, keepdims=True)
    sd = F.std(1, keepdims=True)
    F = F / np.maximum(sd, 1e-6) / np.sqrt(F.shape[1])
    F[sd[:, 0] < FLAT_STD] = 0
    return F


def match_pair(A, B, min_len_s):
    if not len(A) or not len(B):
        return []
    M = (_prep(A) @ _prep(B).T) >= MATCH_CORR
    n, m = M.shape
    L, G = int(min_len_s * FP_RATE), int(MAX_GAP_S * FP_RATE)
    out = []
    for k in range(-(n - 1), m):
        d = np.diagonal(M, offset=k)
        if d.sum() < L * 0.6:
            continue
        idx = np.flatnonzero(d)
        cut = np.flatnonzero(np.diff(idx) > G + 1)
        for s, e in zip(np.r_[idx[0], idx[cut + 1]], np.r_[idx[cut], idx[-1]]):
            if e - s + 1 >= L:
                a0, b0 = s + max(0, -k), s + max(0, k)
                out.append((a0, a0 + e - s + 1, b0, b0 + e - s + 1))
    return out


def _merge(pieces, min_len, pad=1.0, duration=None):
    out = []
    for s, e, lab in sorted(pieces):
        if out and s <= out[-1][1] + JOIN_GAP_S:
            prev = out[-1]
            best = lab if (e - s) > prev[3] else prev[2]
            out[-1] = [prev[0], max(prev[1], e), best, max(prev[3], e - s)]
        else:
            out.append([s, e, lab, e - s])
    hi = duration if duration else float("inf")
    return [[round(max(0.0, s - pad), 1), round(min(hi, e + pad), 1), lab]
            for s, e, lab, _ in out if e - s >= min_len]


def _sibling(video_path: Path):
    files = sorted(f for f in video_path.parent.iterdir() if f.suffix.lower() in VIDEO_EXTS)
    if video_path not in files or len(files) < 2:
        return None
    i = files.index(video_path)
    return files[i + 1] if i + 1 < len(files) else files[i - 1]


def detect_repeats(project, min_len=40.0):
    proj = project.load("project.json", {"videos": []})
    vids = sorted(proj["videos"], key=lambda v: v["id"])
    if not vids:
        return
    fps = {}
    for v in vids:
        p = project.path(f"scan/fp_v{v['id']:02d}.npy")
        if not p.exists():
            if not Path(v["path"]).exists():
                print(f"[autoskip] v{v['id']:02d}: video file missing, can't fingerprint it")
                continue
            print(f"[autoskip] fingerprinting v{v['id']:02d} (one-time) ...")
            np.save(p, fingerprint_video(v["path"]))
        fps[v["id"]] = np.load(p)

    pairs = [(a["id"], b["id"]) for a, b in zip(vids, vids[1:]) if a["id"] in fps and b["id"] in fps]
    if len(vids) == 1 and vids[0]["id"] in fps:
        ref = _sibling(Path(vids[0]["path"]))
        if ref is None:
            print("[autoskip] only one episode and no other episode in its folder - nothing to compare with")
        else:
            p = project.path("scan/fp_ref.npy")
            if proj.get("fp_ref") != str(ref) or not p.exists():
                print(f"[autoskip] fingerprinting reference episode {ref.name} (not extracted) ...")
                np.save(p, fingerprint_video(ref))
                proj["fp_ref"] = str(ref)
            fps["ref"] = np.load(p)
            pairs = [(vids[0]["id"], "ref")]

    marks = {v["id"]: [] for v in vids}
    for a, b in pairs:
        A, B = fps[a], fps[b]
        for a0, a1, b0, b1 in match_pair(A, B, PIECE_S):
            pa, pb = a0 / len(A), b0 / len(B)
            seg_a = (a0 / FP_RATE, a1 / FP_RATE)
            seg_b = (b0 / FP_RATE, b1 / FP_RATE)
            if abs(pa - pb) > RECAP_SHIFT:
                if b != "ref":
                    marks[b].append((*seg_b, "recap"))
                continue
            label = "OP" if pa < 0.5 else "ED"
            marks[a].append((*seg_a, label))
            if b != "ref":
                marks[b].append((*seg_b, label))

    for v in vids:
        v["auto_skip"] = _merge(marks[v["id"]], min_len, duration=v.get("duration"))
    project.save("project.json", proj)

    skip_by_vid = {v["id"]: v["auto_skip"] for v in vids}
    n_flag, n_gone = _flag_frames(project, lambda f: any(s <= f["t"] < e for s, e, _ in skip_by_vid.get(f["vid"], [])))

    for v in vids:
        segs = " | ".join(f"{lab} {mmss(s)}-{mmss(e)}" for s, e, lab in v["auto_skip"]) or "none found"
        print(f"[autoskip] v{v['id']:02d}: {segs}")
    print(f"[autoskip] {n_flag} extracted frames excluded")
    _report_gone(n_gone)


def clear_repeats(project):
    proj = project.load("project.json", {"videos": []})
    for v in proj["videos"]:
        v["auto_skip"] = []
    project.save("project.json", proj)
    _, n_gone = _flag_frames(project, lambda f: False)
    print("[autoskip] cleared - all frames are used again")
    _report_gone(n_gone)


def _flag_frames(project, in_skip):
    frames = project.load("scan/frames.json", [])
    used = {d["frame"] for d in project.load("scan/detections.json", []) if d["feat"] >= 0}
    n_flag = n_gone = 0
    for i, f in enumerate(frames):
        if in_skip(f):
            f["auto"] = True
            n_flag += 1
        else:
            f.pop("auto", None)
        if i in used and not f.get("auto") and not project.path(f["file"]).exists():
            f["deleted"] = True
            n_gone += 1
        else:
            f.pop("deleted", None)
    project.save("scan/frames.json", frames)
    return n_flag, n_gone


def _report_gone(n_gone):
    if n_gone:
        print(f"[autoskip] {n_gone} frames are used again but their files were deleted by `clean` - "
              "they stay unused until you run restore-frames")
