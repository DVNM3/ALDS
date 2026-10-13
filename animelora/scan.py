"""Stage 2: find every character in the kept frames, extract identity features, and cluster them
so the user can point at "their" character by cluster number.

Detection runs while the video is still decoding: each kept frame is searched for characters on worker
threads, and one more thread puts the results together in frame order (ids, CCIP batches), so the output is
the same as going through the frames one at a time. A frame is only kept on disk when it holds a character
big enough to identify: build and the contact sheets never open the others (a quarter to a third of all
frames). They stay in frames.json, so frame numbers and shots don't change. The per-frame work is mostly CPU (resizing a
1080p frame for each detector), which releases the GIL; the detectors themselves take ~6-8 ms on the GPU.
"""
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

from .cancel import check as check_cancel
from .common import box_area, frame_in_use, inside_ratio
from .extract import extract_frames, save_frame
from .identity import ccip_features, ccip_matrix
from .repeats import detect_repeats

VIDEO_EXTS = {".mkv", ".mp4", ".webm", ".avi", ".mov", ".m4v", ".ts"}
MIN_REL_HEIGHT = 0.12  # person box height / frame height needed to bother identifying it
MIN_SIDE_PX = 128
FEAT_DIM = 768
# Extract + detect of a 24-min 1080p episode on a 5800X + 5070 Ti: serial 293 s (6.4 GB VRAM peak); with
# 2 / 3 / 4 threads 162 s (7.3 GB) / 144 s (8.2 GB) / 135 s (9.7 GB). Decoding alone takes 58 s. imgutils
# loads its own copy of the detectors for every thread, so more threads cost VRAM for little gain.
DETECT_WORKERS = 3
IN_FLIGHT = 4 * DETECT_WORKERS  # decoded frames waiting for detection (bounds memory)
CCIP_BATCH = 32
_pool = None  # kept for the whole process: new threads would load new copies of the models


def _workers():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(DETECT_WORKERS, thread_name_prefix="detect")
    return _pool


def expand_video_args(paths):
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
        elif p.exists():
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return [p.resolve() for p in out]


def find_characters(img):
    """[(person box, score, head box or None)]: each head goes to the person box that contains most of it."""
    from imgutils.detect import detect_heads, detect_person

    persons = detect_person(img, conf_threshold=0.35)
    heads = [h[0] for h in detect_heads(img)]
    owner = {}
    for hb in heads:
        best, best_r = None, 0.7
        for pi, (pb, _, _) in enumerate(persons):
            r = inside_ratio(hb, pb)
            if r > best_r:
                best, best_r = pi, r
        if best is not None and (best not in owner or box_area(hb) > box_area(owner[best])):
            owner[best] = hb
    return [([int(v) for v in pb], float(score), [int(v) for v in owner[pi]] if pi in owner else None)
            for pi, (pb, _, score) in enumerate(persons)]


def _examine(frame, path):
    """Worker thread: save the frame and detect on the saved JPEG (exactly what build will crop from later);
    delete it again when no character in it is big enough to identify. (Encoding into memory instead and
    writing only the useful ones was slower with 3 threads: PIL holds the GIL longer for in-memory files.)"""
    save_frame(frame, path)
    img = Image.open(path).convert("RGB")
    found = find_characters(img)
    H = img.height
    big = lambda b: b[3] - b[1] >= MIN_REL_HEIGHT * H and min(b[2] - b[0], b[3] - b[1]) >= MIN_SIDE_PX
    crops = [img.crop(pb) if big(pb) else None for pb, _, _ in found]
    if all(c is None for c in crops):
        path.unlink()
    return found, crops, H


class FrameDetector:
    """Detects characters in kept frames as extract_frames hands them over (`add` is its `keep` callback).
    finish() -> (detections, CCIP features) of all frames, ids continuing from the given offsets."""

    def __init__(self, frame_offset, det_offset, feat_offset):
        self.frame_offset, self.det_offset, self.feat_offset = frame_offset, det_offset, feat_offset
        self.dets, self.feats, self.batch = [], [], []
        self.n_added = self.n_done = self.n_feat = 0
        self.error = None
        self.stopping = False
        self.pending = queue.Queue()  # futures in frame order, None = no more frames
        self.inflight = set()         # submitted, result not taken yet
        self.slots = threading.Semaphore(IN_FLIGHT)
        self.collector = threading.Thread(target=self._collect, name="detect-collect", daemon=True)
        self.collector.start()

    def add(self, frame, path):
        while not self.slots.acquire(timeout=0.2):
            self._raise_error()
        self._raise_error()
        fut = _workers().submit(_examine, frame, path)
        self.inflight.add(fut)
        self.pending.put(fut)
        self.n_added += 1

    def _raise_error(self):
        if self.error is not None:
            raise self.error

    def _collect(self):
        try:
            while (fut := self.pending.get()) is not None and not self.stopping:
                found, crops, H = fut.result()
                self.inflight.discard(fut)
                self.slots.release()
                for (pb, score, head), crop in zip(found, crops):
                    d = {"id": self.det_offset + len(self.dets), "frame": self.frame_offset + self.n_done,
                         "box": pb, "score": round(score, 3), "rh": round((pb[3] - pb[1]) / H, 3),
                         "head": head, "feat": -1}
                    if crop is not None:
                        d["feat"] = self.feat_offset + self.n_feat
                        self.n_feat += 1
                        self.batch.append(crop)
                        if len(self.batch) >= CCIP_BATCH:
                            self._flush()
                    self.dets.append(d)
                self.n_done += 1
            if not self.stopping:
                self._flush()
        except BaseException as e:  # incl. Cancelled from the stop button; add()/finish() re-raise it
            self.error = e
            self.slots.release()  # unblock add()

    def _flush(self):
        if self.batch:
            self.feats.append(ccip_features(self.batch))
            self.batch = []

    def finish(self):
        self.pending.put(None)
        with tqdm(total=self.n_added, initial=self.n_done, desc="  detect", unit="f", leave=False) as bar:
            while self.collector.is_alive():
                check_cancel()
                self.collector.join(0.2)
                bar.update(self.n_done - bar.n)
        self._raise_error()
        F = np.concatenate(self.feats) if self.feats else np.zeros((0, FEAT_DIM), np.float32)
        return self.dets, F

    def abort(self):
        """After an error or a stop: drop the queued frames and wait for the running ones, so nothing is
        written into the frames folder after the undo has cleaned it up."""
        self.stopping = True
        futs = self.inflight.copy()
        for fut in futs:
            fut.cancel()
        wait(futs)
        self.pending.put(None)
        self.collector.join()


def load_state(project):
    frames = project.load("scan/frames.json", [])
    dets = project.load("scan/detections.json", [])
    fp = project.path("scan/ccip.npy")
    F = np.load(fp) if fp.exists() else np.zeros((0, FEAT_DIM), np.float32)
    return frames, dets, F


def run_scan(project, videos, skip_ranges, min_gap, keep_diff, auto_skip=True, auto_min=40.0):
    project.require_frames()
    proj = project.load("project.json", {"videos": []})
    frames, dets, F = load_state(project)

    for vp in expand_video_args(videos):
        if any(v["path"] == str(vp) for v in proj["videos"]):
            print(f"[scan] already scanned, skipping: {vp.name}")
            continue
        vid = len(proj["videos"]) + 1
        print(f"[scan] v{vid:02d}  {vp.name}")
        detector = FrameDetector(len(frames), len(dets), len(F))
        try:
            fr, info, fp = extract_frames(vp, project.frames_dir / f"v{vid:02d}", f"frames/v{vid:02d}",
                                          skip=skip_ranges, min_gap=min_gap, keep_diff=keep_diff,
                                          keep=detector.add)
            print(f"        kept {len(fr)} frames from {info['shots']} shots ({info['duration'] / 60:.1f} min)")
            new_dets, newF = detector.finish()
        except BaseException:
            detector.abort()
            raise
        project.scan_dir.mkdir(parents=True, exist_ok=True)
        np.save(project.path(f"scan/fp_v{vid:02d}.npy"), fp)
        for f in fr:
            f["vid"] = vid
        n_feat = sum(d["feat"] >= 0 for d in new_dets)
        n_saved = len({d["frame"] for d in new_dets if d["feat"] >= 0})
        print(f"        {len(new_dets)} character detections, {n_feat} large enough to identify")
        print(f"        {n_saved} frames saved ({len(fr) - n_saved} without a character to identify not kept)")

        frames += fr
        dets += new_dets
        F = np.concatenate([F, newF])
        proj["videos"].append({"id": vid, "path": str(vp), "name": vp.stem, **info,
                               "kept_frames": len(fr), "saved_frames": n_saved, "skip": skip_ranges})
        project.save("scan/frames.json", frames)
        project.save("scan/detections.json", dets)
        np.save(project.path("scan/ccip.npy"), F)
        project.save("project.json", proj)

    if not dets:
        raise SystemExit("[scan] no characters detected")
    if auto_skip:
        detect_repeats(project, auto_min)
    run_clusters(project)


def run_clusters(project, cut=0.2, min_size=8, max_samples=4000):
    """Average-linkage clustering on the CCIP difference matrix. (OPTICS, imgutils' default, shattered
    a test episode into 136 tiny clusters; average linkage at ~0.2 gave one cluster per main character.)"""
    from sklearn.cluster import AgglomerativeClustering

    project.require_frames()
    frames, dets, F = load_state(project)
    # cluster only clear views (head visible, reasonably large) outside auto-detected OP/ED;
    # build() matches everything else later
    cand = [d for d in dets if d["feat"] >= 0 and d["head"] is not None and d["rh"] >= 0.2
            and frame_in_use(frames[d["frame"]])]
    if len(cand) > max_samples:
        rng = np.random.default_rng(0)
        cand = [cand[i] for i in sorted(rng.choice(len(cand), max_samples, replace=False))]
    if len(cand) < min_size:
        raise SystemExit("[clusters] not enough clear character views to cluster")
    print(f"[clusters] clustering {len(cand)} clear character views ...")
    D = ccip_matrix(F[[d["feat"] for d in cand]])
    labels = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                     distance_threshold=cut).fit(D).labels_

    groups = {}
    for d, l in zip(cand, labels):
        groups.setdefault(int(l), []).append(d["id"])
    ordered = sorted((g for g in groups.values() if len(g) >= min_size), key=len, reverse=True)
    clusters = [{"id": k + 1, "members": m} for k, m in enumerate(ordered)]
    project.save("scan/clusters.json", {"params": {"cut": cut, "min_size": min_size}, "clusters": clusters})
    contact_sheets(project, frames, dets, clusters)

    n_small = len(cand) - sum(len(c["members"]) for c in clusters)
    print(f"[clusters] {len(clusters)} characters found ({n_small} views in groups smaller than {min_size})")
    for c in clusters:
        vids = sorted({frames[dets[m]["frame"]]["vid"] for m in c["members"]})
        print(f"   #{c['id']:<3} {len(c['members']):>5} views   episodes: {', '.join(f'v{v:02d}' for v in vids)}")
    print(f"\nOpen  {project.clusters_dir / 'overview.jpg'}")
    print(f"and pick the cluster number(s) of your character (a character can be split across several clusters).")


def split_cluster(project, cid, cut=0.14, min_size=3):
    """Re-cluster one mixed cluster at a tighter cut. The biggest part keeps the number, the others get new
    numbers at the end, so the rest of the numbering doesn't move."""
    from sklearn.cluster import AgglomerativeClustering

    project.require_frames()
    frames, dets, F = load_state(project)
    data = project.load("scan/clusters.json")
    if not data:
        raise SystemExit("no clusters yet - run scan first")
    clusters = data["clusters"]
    c = next((c for c in clusters if c["id"] == cid), None)
    if c is None:
        raise SystemExit(f"cluster #{cid} does not exist")
    if len(c["members"]) < 2 * min_size:
        raise SystemExit(f"cluster #{cid} is too small to split")
    D = ccip_matrix(F[[dets[m]["feat"] for m in c["members"]]])
    labels = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                     distance_threshold=cut).fit(D).labels_
    groups = {}
    for m, l in zip(c["members"], labels):
        groups.setdefault(int(l), []).append(m)
    parts = sorted((g for g in groups.values() if len(g) >= min_size), key=len, reverse=True)
    if len(parts) < 2:
        raise SystemExit(f"cluster #{cid} didn't split at cut {cut} - try a lower value")
    c["members"] = parts[0]
    next_id = max(x["id"] for x in clusters) + 1
    new_ids = [cid]
    for k, part in enumerate(parts[1:]):
        clusters.append({"id": next_id + k, "members": part})
        new_ids.append(next_id + k)
    project.save("scan/clusters.json", data)
    contact_sheets(project, frames, dets, clusters)
    n_lost = len(D) - sum(len(p) for p in parts)
    print(f"[split] #{cid} -> " + ", ".join(f"#{i} ({len(p)})" for i, p in zip(new_ids, parts))
          + (f"; {n_lost} stray views dropped" if n_lost else ""))
    return new_ids


def _thumb(project, frames, det, cell, cache):
    fr = frames[det["frame"]]
    img = cache.get(fr["file"])
    if img is None:
        img = Image.open(project.path(fr["file"]))
        full_w = img.size[0]
        img.draft("RGB", (img.size[0] // 2, img.size[1] // 2))
        img = img.convert("RGB")
        img.info["scale"] = img.size[0] / full_w
        if len(cache) > 64:
            cache.clear()
        cache[fr["file"]] = img
    s = img.info["scale"]
    x0, y0, x1, y1 = det["box"]
    crop = img.crop((int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s)))
    crop.thumbnail(cell)
    return crop


def _spread(members, frames, dets, n):
    """Pick up to n members spread over time so the sheet shows variety."""
    ms = sorted(members, key=lambda m: dets[m]["frame"])
    if len(ms) <= n:
        return ms
    return [ms[int(i)] for i in np.linspace(0, len(ms) - 1, n)]


def contact_sheets(project, frames, dets, clusters, per_row=10, cell=(150, 200)):
    out = project.clusters_dir
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    font = ImageFont.load_default(size=26)
    small = ImageFont.load_default(size=18)
    cache = {}
    label_w, pad = 110, 4
    cw, ch = cell

    rows = []
    for c in tqdm(clusters, desc="  sheets", leave=False):
        check_cancel()
        row = Image.new("RGB", (label_w + per_row * (cw + pad), ch + 2 * pad), (32, 32, 36))
        d = ImageDraw.Draw(row)
        d.text((12, 20), f"#{c['id']}", fill=(255, 220, 90), font=font)
        d.text((12, 60), f"{len(c['members'])} views", fill=(200, 200, 200), font=small)
        for k, m in enumerate(_spread(c["members"], frames, dets, per_row)):
            t = _thumb(project, frames, dets[m], cell, cache)
            row.paste(t, (label_w + k * (cw + pad) + (cw - t.width) // 2, pad + (ch - t.height) // 2))
        rows.append(row)

        # a bigger sheet per cluster for a closer look
        picks = _spread(c["members"], frames, dets, 40)
        cols = 8
        sheet = Image.new("RGB", (cols * (cw + pad) + pad, ((len(picks) + cols - 1) // cols) * (ch + pad) + pad + 40), (32, 32, 36))
        ImageDraw.Draw(sheet).text((10, 6), f"Cluster #{c['id']} - {len(c['members'])} views", fill=(255, 220, 90), font=font)
        for k, m in enumerate(picks):
            t = _thumb(project, frames, dets[m], cell, cache)
            x = pad + (k % cols) * (cw + pad) + (cw - t.width) // 2
            y = 40 + pad + (k // cols) * (ch + pad) + (ch - t.height) // 2
            sheet.paste(t, (x, y))
        sheet.save(out / f"cluster_{c['id']:02d}.jpg", quality=88)

        # a small 3x2 card for the GUI picker
        card = Image.new("RGB", (3 * (cw + pad) + pad, 2 * (ch + pad) + pad + 36), (32, 32, 36))
        ImageDraw.Draw(card).text((10, 4), f"#{c['id']}   {len(c['members'])}", fill=(255, 220, 90), font=font)
        for k, m in enumerate(_spread(c["members"], frames, dets, 6)):
            t = _thumb(project, frames, dets[m], cell, cache)
            card.paste(t, (pad + (k % 3) * (cw + pad) + (cw - t.width) // 2,
                           36 + pad + (k // 3) * (ch + pad) + (ch - t.height) // 2))
        card.save(out / f"card_{c['id']:02d}.jpg", quality=88)

    if rows:
        overview = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), (20, 20, 24))
        y = 0
        for r in rows:
            overview.paste(r, (0, y))
            y += r.height
        overview.save(out / "overview.jpg", quality=88)
