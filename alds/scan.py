import queue
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

from .cache import file_hash
from .cancel import check as check_cancel
from .common import VIDEO_EXTS, box_area, frame_in_use, inside_ratio
from .extract import extract_frames, save_frame
from .i18n import t
from .identity import ccip_features, ccip_matrix
from .repeats import detect_repeats

MIN_REL_HEIGHT = 0.12
MIN_SIDE_PX = 128
FEAT_DIM = 768
DETECT_WORKERS = 3
IN_FLIGHT = 4 * DETECT_WORKERS
CCIP_BATCH = 32
_pool = None


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
    def __init__(self, frame_offset, det_offset, feat_offset):
        self.frame_offset, self.det_offset, self.feat_offset = frame_offset, det_offset, feat_offset
        self.dets, self.feats, self.batch = [], [], []
        self.n_added = self.n_done = self.n_feat = 0
        self.error = None
        self.stopping = False
        self.pending = queue.Queue()
        self.inflight = set()
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
        except BaseException as e:
            self.error = e
            self.slots.release()

    def _flush(self):
        if self.batch:
            self.feats.append(ccip_features(self.batch))
            self.batch = []

    def finish(self):
        self.pending.put(None)
        with tqdm(total=self.n_added, initial=self.n_done, desc=t("Finding the characters"), unit=t("frames"),
                  leave=False) as bar:
            while self.collector.is_alive():
                check_cancel()
                self.collector.join(0.2)
                bar.update(self.n_done - bar.n)
        self._raise_error()
        F = np.concatenate(self.feats) if self.feats else np.zeros((0, FEAT_DIM), np.float32)
        return self.dets, F

    def abort(self):
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

    videos = expand_video_args(videos)
    for i, vp in enumerate(videos, 1):
        if any(v["path"] == str(vp) for v in proj["videos"]):
            print(t("Episode {i} of {n}: {name} is already scanned, skipped", i=i, n=len(videos), name=vp.name))
            continue
        vid = len(proj["videos"]) + 1
        print(t("Episode {i} of {n}: {name}", i=i, n=len(videos), name=vp.name))
        detector = FrameDetector(len(frames), len(dets), len(F))
        try:
            fr, info, fp = extract_frames(vp, project.frames_dir / f"v{vid:02d}", f"frames/v{vid:02d}",
                                          skip=skip_ranges, min_gap=min_gap, keep_diff=keep_diff,
                                          keep=detector.add)
            print("  • " + t("{n} frames taken from {shots} shots ({minutes} min)", n=len(fr), shots=info["shots"],
                             minutes=f"{info['duration'] / 60:.1f}"))
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
        print("  • " + t("{n} character appearances, {k} of them big enough to recognise", n=len(new_dets),
                         k=n_feat))
        print("  • " + t("{n} frames saved", n=n_saved)
              + (t("; {n} frames without a character to recognise were not kept", n=len(fr) - n_saved)
                 if len(fr) > n_saved else ""))

        frames += fr
        dets += new_dets
        F = np.concatenate([F, newF])
        proj["videos"].append({"id": vid, "path": str(vp), "name": vp.stem, **info,
                               "kept_frames": len(fr), "saved_frames": n_saved, "skip": skip_ranges})
        proj["videos"][-1]["source_sha256"] = file_hash(vp)
        project.save("scan/frames.json", frames)
        project.save("scan/detections.json", dets)
        np.save(project.path("scan/ccip.npy"), F)
        project.save("project.json", proj)

    if not dets:
        raise SystemExit("no characters detected")
    if auto_skip:
        detect_repeats(project, auto_min)
    run_clusters(project)


def run_clusters(project, cut=0.2, min_size=8, max_samples=4000):
    from sklearn.cluster import AgglomerativeClustering

    project.require_frames()
    print(t("Grouping the characters"))
    frames, dets, F = load_state(project)
    cand = [d for d in dets if d["feat"] >= 0 and d["head"] is not None and d["rh"] >= 0.2
            and frame_in_use(frames[d["frame"]])]
    if len(cand) > max_samples:
        rng = np.random.default_rng(0)
        cand = [cand[i] for i in sorted(rng.choice(len(cand), max_samples, replace=False))]
    if len(cand) < min_size:
        raise SystemExit("not enough clear character views to cluster")
    print("  • " + t("{n} clear views of characters", n=len(cand)))
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
    print("  • " + t("{n} characters found; {k} views in groups smaller than {size} are hidden", n=len(clusters),
                     k=n_small, size=min_size))
    for c in clusters:
        vids = sorted({frames[dets[m]["frame"]]["vid"] for m in c["members"]})
        print("    " + t("#{id}: {n} views, episodes {episodes}", id=c["id"], n=len(c["members"]),
                         episodes=", ".join(f"v{v:02d}" for v in vids)))


def split_cluster(project, cid, cut=0.14, min_size=3):
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
    print(t("Cluster #{id} split into {parts}", id=cid,
            parts=t(", ").join(t("#{id} ({n} views)", id=i, n=len(p)) for i, p in zip(new_ids, parts)))
          + (t("; {n} views that fit nowhere were left out", n=n_lost) if n_lost else ""))


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


def _spread(members, dets, n):
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
    for c in tqdm(clusters, desc=t("Drawing the character cards"), unit=t("characters"), leave=False):
        check_cancel()
        row = Image.new("RGB", (label_w + per_row * (cw + pad), ch + 2 * pad), (32, 32, 36))
        d = ImageDraw.Draw(row)
        d.text((12, 20), f"#{c['id']}", fill=(255, 220, 90), font=font)
        d.text((12, 60), f"{len(c['members'])} views", fill=(200, 200, 200), font=small)
        for k, m in enumerate(_spread(c["members"], dets, per_row)):
            tile = _thumb(project, frames, dets[m], cell, cache)
            row.paste(tile, (label_w + k * (cw + pad) + (cw - tile.width) // 2, pad + (ch - tile.height) // 2))
        rows.append(row)

        picks = _spread(c["members"], dets, 40)
        cols = 8
        sheet = Image.new("RGB", (cols * (cw + pad) + pad, ((len(picks) + cols - 1) // cols) * (ch + pad) + pad + 40), (32, 32, 36))
        ImageDraw.Draw(sheet).text((10, 6), f"Cluster #{c['id']} - {len(c['members'])} views", fill=(255, 220, 90), font=font)
        for k, m in enumerate(picks):
            tile = _thumb(project, frames, dets[m], cell, cache)
            x = pad + (k % cols) * (cw + pad) + (cw - tile.width) // 2
            y = 40 + pad + (k // cols) * (ch + pad) + (ch - tile.height) // 2
            sheet.paste(tile, (x, y))
        sheet.save(out / f"cluster_{c['id']:02d}.jpg", quality=88)

        card = Image.new("RGB", (3 * (cw + pad) + pad, 2 * (ch + pad) + pad + 36), (32, 32, 36))
        ImageDraw.Draw(card).text((10, 4), f"#{c['id']}   {len(c['members'])}", fill=(255, 220, 90), font=font)
        for k, m in enumerate(_spread(c["members"], dets, 6)):
            tile = _thumb(project, frames, dets[m], cell, cache)
            card.paste(tile, (pad + (k % 3) * (cw + pad) + (cw - tile.width) // 2,
                              36 + pad + (k // 3) * (ch + pad) + (ch - tile.height) // 2))
        card.save(out / f"card_{c['id']:02d}.jpg", quality=88)

    if rows:
        overview = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), (20, 20, 24))
        y = 0
        for r in rows:
            overview.paste(r, (0, y))
            y += r.height
        overview.save(out / "overview.jpg", quality=88)
