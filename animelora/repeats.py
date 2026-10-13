"""Automatic opening/ending detection.

OPs and EDs are (nearly) the same footage in every episode of a season, so we look for long stretches
of video that repeat between neighbouring episodes. Each episode gets a fingerprint: one 16x9 grayscale
image per half second (the average of all frames in that half second, so sampling phase doesn't matter).
Two episodes share a segment when a long diagonal run of near-identical fingerprints shows up in their
similarity matrix. With a single episode in the project, a sibling file from the same folder is used as
the reference (fingerprinted only, never extracted).
"""
from pathlib import Path

import av
import numpy as np
from tqdm import tqdm

from .cancel import check as check_cancel

FP_RATE = 2.0        # fingerprints per second
FLAT_STD = 4.0       # fingerprints flatter than this (black/white screens) never count as a match
# Correlation for two fingerprints to count as the same picture. 0.85 split a real ED into short pieces
# because per-episode staff credits differ; 0.75 kept it whole. False matches stay unlikely because a
# segment needs many consecutive in-order matches.
MATCH_CORR = 0.75
MAX_GAP_S = 2.0      # tolerated mismatch inside a repeated run (cut misalignment)
PIECE_S = 8.0        # shortest matching run kept as a piece
JOIN_GAP_S = 8.0     # pieces this close are joined before the min-length test
RECAP_SHIFT = 0.3    # same footage at very different relative positions = recap, not OP/ED
VIDEO_EXTS = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m4v", ".ts"}


class Fingerprinter:
    """Collects 64x36 grayscale thumbnails (as computed while decoding) into half-second fingerprints."""

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
        while len(self.rows) < self.cur:  # windows with no frames (VFR gaps)
            self.rows.append(np.zeros(144, np.float32))
        self.rows.append((self.acc / self.n).ravel())

    def result(self) -> np.ndarray:
        self._flush()
        self.cur = -1
        return np.array(self.rows, np.float16) if self.rows else np.zeros((0, 144), np.float16)


def fingerprint_video(path) -> np.ndarray:
    """Fingerprint of a video that isn't extracted (the reference episode). The decoder skips non-reference
    frames (frames no other frame is predicted from): about half the decoding, while the half-second averages
    stay the same - Fairy Tail ep 17: 57 s -> 33 s, correlation with the every-frame version median 1.00 and
    1st percentile 0.96 (matches need 0.75), same OP/ED found."""
    fp, covered = _fingerprint(path, skip="NONREF")
    if covered < 0.9:  # a codec that skips (nearly) every frame this way, e.g. intra-only: use them all
        fp, _ = _fingerprint(path, skip=None)
    return fp


def _fingerprint(path, skip):
    """-> (fingerprints, share of half-second windows that got at least one frame)"""
    fp, windows = Fingerprinter(), set()
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        if skip:
            s.codec_context.skip_frame = skip
        fps = float(s.average_rate or 24)
        duration = c.duration / av.time_base if c.duration else None
        # progress in seconds of video: with skipped frames the frame count says nothing
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
    """Repeated runs (>= min_len_s) between two fingerprint sequences -> [(a0, a1, b0, b1)] in fingerprint indices."""
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
    """pieces: [(start_s, end_s, label)] -> joined segments at least `min_len` long, padded;
    the label of the longest piece wins."""
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
    """Neighbouring episode in the same folder (next one, else previous)."""
    files = sorted(f for f in video_path.parent.iterdir() if f.suffix.lower() in VIDEO_EXTS)
    if video_path not in files or len(files) < 2:
        return None
    i = files.index(video_path)
    return files[i + 1] if i + 1 < len(files) else files[i - 1]


def _fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def detect_repeats(project, min_len=40.0):
    """Find OP/ED (and long recaps) in every scanned episode, store them as `auto_skip` per video and flag
    the affected frames with "auto": True so clustering and build ignore them."""
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
                # same footage at different places: a recap in the later episode; the original stays
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
        segs = " | ".join(f"{lab} {_fmt(s)}-{_fmt(e)}" for s, e, lab in v["auto_skip"]) or "none found"
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
    """Set the "auto" flag of every frame. `clean` deletes the files of OP/ED frames, so a frame that leaves
    the OP/ED (other OP/ED found, --off) may have no file any more: it is flagged "deleted" and stays unused
    instead of breaking clustering and build. -> (frames flagged auto, frames flagged deleted)"""
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
              "they stay unused (scan the episodes again in a new project to get them back)")
