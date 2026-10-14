import functools
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm

from .angles import face_pose
from .cache import CropCache, digest, link_or_copy
from .cancel import check as check_cancel
from .captions import FRAMING_TAGS, classify, find_core_tags, make_caption
from .common import box_area, box_iou, expand_box, frame_in_use
from .identity import ccip_cross, ccip_features
from . import negatives
from .scan import load_state

DEFAULT_THRESHOLD = 0.13
MIN_CONTRAST = 18.0
TEXT_MIN_CONF = 0.75
OFFMODEL_TAGS = ("chibi", "super deformed", "blurry")
MONOCHROME_TAGS = ("monochrome", "greyscale", "sepia")
OTHER_PER_CLUSTER = 16
UPSCALE_MIN_FACTOR = 1.15
MAX_ASPECT = 3.0
CROP_TYPES = ("full", "half", "head")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
FRAMINGS = ("close_up", "upper_body", "cowboy_shot", "full_body")
VIEWS = ("front", "three_quarter", "side", "back", "above", "below")
SCORE_BINS = (0.05, 0.10, 0.13, 0.15, 0.178, 0.20, 0.25)


def reference_features(project, cluster_ids, ref_dir, dets, F, cache):
    refs = []
    if cluster_ids:
        data = project.load("scan/clusters.json")
        if not data:
            raise SystemExit("no clusters yet - run scan first")
        by_id = {c["id"]: c for c in data["clusters"]}
        for cid in cluster_ids:
            if cid not in by_id:
                raise SystemExit(f"cluster #{cid} does not exist (have #1..#{len(by_id)})")
            refs.append(most_central(F[[dets[m]["feat"] for m in by_id[cid]["members"]]], 64, cache))
    if ref_dir:
        from imgutils.detect import detect_person
        imgs = []
        for p in sorted(Path(ref_dir).iterdir()):
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            img = Image.open(p).convert("RGB")
            persons = detect_person(img, conf_threshold=0.35)
            if persons:
                img = img.crop(max(persons, key=lambda x: box_area(x[0]))[0])
            imgs.append(img)
        if not imgs:
            raise SystemExit(f"no images in {ref_dir}")
        refs.append(ccip_features(imgs))
        print(f"[build] {len(imgs)} reference images")
    if not refs:
        raise SystemExit("give --cluster and/or --ref")
    return np.concatenate(refs)


def most_central(feats, n, cache):
    if len(feats) <= n:
        return feats
    order = cache.get(cache.central, "order:" + digest(feats), lambda: np.argsort(ccip_cross(feats, feats).mean(1)))
    return feats[order[:n]]


def other_characters(project, cluster_ids, refs, dets, F, threshold, cache):
    data = project.load("scan/clusters.json") or {"clusters": []}
    feats, used = [], []
    for c in data["clusters"]:
        if c["id"] in cluster_ids:
            continue
        fc = most_central(F[[dets[m]["feat"] for m in c["members"]]], 4 * OTHER_PER_CLUSTER, cache)
        fc = fc[match_score(fc, refs) > threshold][:OTHER_PER_CLUSTER]
        if len(fc):
            feats.append(fc)
            used.append(c["id"])
    return (np.concatenate(feats) if feats else None), used


def match_score(feats, refs):
    k = max(1, min(5, len(refs) // 4))
    return np.sort(ccip_cross(feats, refs), axis=1)[:, :k].mean(1)


def select(frames, dets, F, refs, threshold, relax, cache, negs=None):
    elig = [d for d in dets if d["feat"] >= 0 and frame_in_use(frames[d["frame"]])]
    feats_of = lambda ids: F[[dets[i]["feat"] for i in ids]]
    ids = [d["id"] for d in elig]
    scores = cache.scores(digest(refs, F), ids, lambda ids: match_score(feats_of(ids), refs))
    rejected = set()
    if negs is not None:
        near = cache.scores("neg:" + digest(negs, F), ids, lambda ids: negatives.nearest(feats_of(ids), negs))
        rejected = {i for i, s, n in zip(ids, scores, near) if n < s}
    by_frame = defaultdict(list)
    for d, s in zip(elig, scores):
        by_frame[d["frame"]].append((d, float(s)))

    chosen, best_scores, n_rejected = {}, [], 0
    for fi, ds in by_frame.items():
        best_scores.append(min(s for _, s in ds))
        ok = [x for x in ds if x[0]["id"] not in rejected]
        d, s = min(ok, key=lambda x: x[1]) if ok else (None, float("inf"))
        if s <= threshold:
            chosen[fi] = (d, s, "match")
        elif best_scores[-1] <= threshold:
            n_rejected += 1

    frontier = list(chosen) if relax > 1 else []
    while frontier:
        nxt = []
        for fi in frontier:
            base = chosen[fi][0]
            for nf in (fi - 1, fi + 1):
                if nf in chosen or nf not in by_frame:
                    continue
                if (frames[nf]["vid"], frames[nf]["shot"]) != (frames[fi]["vid"], frames[fi]["shot"]):
                    continue
                cands = [(box_iou(d["box"], base["box"]), d, s) for d, s in by_frame[nf]
                         if s <= threshold * relax and d["id"] not in rejected]
                cands = [c for c in cands if c[0] >= 0.4]
                if cands:
                    _, d, s = max(cands, key=lambda c: c[0])
                    chosen[nf] = (d, s, "track")
                    nxt.append(nf)
        frontier = nxt
    return chosen, best_scores, n_rejected


def crop_boxes(img, det, detect_halfbody):
    W, H = img.size
    full = expand_box(det["box"], 1.12, W, H)
    out = {"full": full}
    hb = detect_halfbody(img.crop(full), conf_threshold=0.5)
    if hb:
        b = max(hb, key=lambda x: x[2])[0]
        half = expand_box([full[0] + b[0], full[1] + b[1], full[0] + b[2], full[1] + b[3]], 1.08, W, H)
        if box_area(half) < 0.72 * box_area(full):
            out["half"] = half
    if det["head"]:
        head = expand_box(det["head"], 1.7, W, H, square=True, shift_y=0.12)
        if box_area(head) < 0.6 * box_area(out.get("half", full)):
            out["head"] = head
    return out


def usable_crops(boxes, min_size):
    return {t: b for t, b in boxes.items() if box_area(b) ** 0.5 >= min_size
            and max(b[2] - b[0], b[3] - b[1]) <= MAX_ASPECT * min(b[2] - b[0], b[3] - b[1])}


def crowded(crop_box, det, frame_dets):
    for o in frame_dets:
        if o["id"] == det["id"]:
            continue
        b = o["box"]
        ix0, iy0 = max(b[0], crop_box[0]), max(b[1], crop_box[1])
        ix1, iy1 = min(b[2], crop_box[2]), min(b[3], crop_box[3])
        inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
        if inter >= 0.5 * box_area(b) and inter >= 0.15 * box_area(crop_box):
            return True
    return False


def image_stats(img):
    g = np.asarray(img.convert("L"))
    s = 512 / max(g.shape)
    g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()), float(g.std())


def read_text(img, ocr):
    return [(txt, float(score)) for _, txt, score in ocr(img)]


def has_text(words):
    return any(score >= TEXT_MIN_CONF and len(re.sub(r"[\W_]", "", txt)) >= 3 for txt, score in words)


def upscale_factor(box, target):
    f = min(4.0, target / box_area(box) ** 0.5)
    return f if f >= UPSCALE_MIN_FACTOR else 1.0


def upscale(img, f, upscale_with_cdc):
    big = upscale_with_cdc(img, silent=True)
    return big.resize((round(img.width * f), round(img.height * f)), Image.LANCZOS)


def dedup(items, sim):
    keep = []
    for ctype in CROP_TYPES:
        group = [it for it in items if it["type"] == ctype]
        if not group:
            continue
        E = np.stack([it["emb"] for it in group])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        quality = np.array([np.log1p(it["sharp"]) + 0.5 * np.log(box_area(it["box"])) for it in group])
        kept = []
        for i in np.argsort(-quality):
            if kept and float((E[kept] @ E[i]).max()) >= sim:
                continue
            kept.append(int(i))
        keep += [group[i] for i in kept]
    return keep


def check_overwrite(project, name, overwrite):
    sorted_dir = project.char_dir(name) / "sorted"
    if sorted_dir.exists() and not overwrite:
        raise SystemExit(f"{sorted_dir} already exists (your reviewed images?). Use --overwrite to rebuild it.")


def run_build(project, name, cluster_ids, ref_dir, threshold, relax, min_size, sim, series,
              keep_core, screencap, tagger, keep_text, keep_crowded, keep_offmodel, save_dropped, overwrite,
              upscale_to=0, outfits=True, fresh=False, auto_reject=True, keep_mono=False):
    from imgutils.detect import detect_halfbody
    from imgutils.ocr import ocr
    from imgutils.tagging import get_wd14_tags
    from imgutils.validate import anime_portrait

    project.require_frames()
    frames, dets, F = load_state(project)
    if not dets:
        raise SystemExit("nothing scanned yet - run scan first")
    out_dir = project.char_dir(name)
    sorted_dir = out_dir / "sorted"
    check_overwrite(project, name, overwrite)
    if sorted_dir.exists():
        shutil.rmtree(sorted_dir)
        shutil.rmtree(out_dir / "_deleted", ignore_errors=True)

    cache = CropCache(project, fresh)
    try:
        threshold = threshold or DEFAULT_THRESHOLD
        refs = reference_features(project, cluster_ids, ref_dir, dets, F, cache)
        neg_names, negs = negatives.load(out_dir)
        others, other_ids = (other_characters(project, cluster_ids, refs, dets, F, threshold, cache)
                             if auto_reject else (None, []))
        negs = [x for x in (negs, others) if x is not None]
        negs = np.concatenate(negs) if negs else None
        chosen, best_scores, n_rejected = select(frames, dets, F, refs, threshold, relax, cache, negs)
        n_track = sum(1 for v in chosen.values() if v[2] == "track")
        print(f"[build] matched {len(chosen)} frames ({n_track} via shot tracking), threshold {threshold}")
        sources = ([f"{len(other_ids)} other clusters"] if other_ids else []) + (
            [f"{len(neg_names)} images rejected in review"] if neg_names else [])
        others_line = (f"{n_rejected} frames left out as other characters (from {' and '.join(sources)})"
                       if sources else "")
        if others_line:
            print("        " + others_line)
        print("        best score per frame: " + score_histogram(best_scores))
        if not chosen:
            raise SystemExit("no matches - try a higher --threshold or other clusters/refs")

        dets_by_frame = defaultdict(list)
        for d in dets:
            dets_by_frame[d["frame"]].append(d)

        dropped_dir = out_dir / "_dropped"
        if dropped_dir.exists():
            shutil.rmtree(dropped_dir)
        items, dropped = [], Counter()

        def drop(reason, crop, fr, ctype):
            dropped[reason] += 1
            if save_dropped:
                folder = dropped_dir / reason.replace(" ", "_").replace("/", "")
                folder.mkdir(parents=True, exist_ok=True)
                crop(ctype).save(folder / f"v{fr['vid']:02d}_{fr['t']:07.1f}s_{ctype}.jpg", quality=90)

        def wd14(img):
            rating, general, _chars, emb = get_wd14_tags(
                img, model_name=tagger, general_threshold=0.35, no_underline=True, drop_overlap=True,
                fmt=("rating", "general", "character", "embedding"))
            return rating, general, emb

        n_new = 0
        for fi in tqdm(sorted(chosen), desc="  crop+tag", unit="f"):
            check_cancel()
            det, score, how = chosen[fi]
            fr = frames[fi]
            entry, computed = cache.entry(det, fr), cache.computed
            frame = functools.cache(lambda: Image.open(project.path(fr["file"])).convert("RGB"))
            boxes = usable_crops(cache.get(entry, "boxes", lambda: crop_boxes(frame(), det, detect_halfbody)),
                                 min_size)
            crop = functools.cache(lambda t: frame().crop(boxes[t]))
            recs = {t: entry["crops"].setdefault(t, {}) for t in boxes}
            sub = [t for t in boxes if t != "full"]
            missing = [t for t in sub if "ccip" not in recs[t]]
            if missing:
                for t, f in zip(missing, ccip_features([crop(t) for t in missing])):
                    recs[t]["ccip"] = f
                cache.computed += 1
            if sub:
                sub_feats = np.stack([recs[t]["ccip"] for t in sub])
                near = negatives.nearest(sub_feats, negs) if negs is not None else [float("inf")] * len(sub)
                for t, s, n in zip(sub, match_score(sub_feats, refs), near):
                    if s > threshold:
                        drop("another character in crop", crop, fr, t)
                        del boxes[t]
                    elif n < s:
                        drop("looks like another character", crop, fr, t)
                        del boxes[t]
            for ctype, box in boxes.items():
                rec = recs[ctype]
                if not keep_crowded and ctype != "head" and crowded(box, det, dets_by_frame[fi]):
                    drop("another character in crop", crop, fr, ctype)
                    continue
                sharp, contrast = cache.get(rec, "stats", lambda: image_stats(crop(ctype)))
                if contrast < MIN_CONTRAST:
                    drop("dark or faded", crop, fr, ctype)
                    continue
                if not keep_text and has_text(cache.get(rec, "ocr", lambda: read_text(crop(ctype), ocr))):
                    drop("text on screen", crop, fr, ctype)
                    continue
                rating, general, emb = cache.get(rec.setdefault("tags", {}), tagger, lambda: wd14(crop(ctype)))
                if not keep_offmodel and any(t in general for t in OFFMODEL_TAGS):
                    drop("chibi or blurry", crop, fr, ctype)
                    continue
                if not keep_mono and any(t in general for t in MONOCHROME_TAGS):
                    drop("black and white or sepia", crop, fr, ctype)
                    continue
                portrait = None
                if ctype != "head" and not any(t in general for t, _ in FRAMING_TAGS):
                    portrait = cache.get(rec, "portrait", lambda: anime_portrait(crop(ctype))[0])
                items.append({"frame": fi, "det": det["id"], "type": ctype, "box": box, "score": round(score, 4),
                              "how": how, "sharp": sharp, "rating": rating, "general": general, "emb": emb,
                              "portrait": portrait, "head": box if ctype == "head" else det["head"]})
            n_new += cache.computed > computed
        print(f"[build] {len(chosen) - n_new} frames reused from the saved analysis, {n_new} analysed now")
        n_crops = len(items) + sum(dropped.values())
        keep = dedup(items, sim)
        dropped["near-duplicate"] = len(items) - len(keep)
        print(f"[build] {n_crops} crops -> {len(keep)} kept "
              f"(dropped: {', '.join(f'{v} {k}' for k, v in dropped.items() if v)})")

        if upscale_to:
            from imgutils.upscale import upscale_with_cdc
        from imgutils.detect import detect_eyes, detect_faces
        core = set() if keep_core else find_core_tags([it["general"] for it in keep])
        review_cut = threshold * 0.85
        meta, dist, n_review, n_up, stems, embs, ccips = [], Counter(), 0, 0, [], [], []
        open_key = open_img = None

        def frame_img(fr):
            nonlocal open_key, open_img
            if open_key != fr["file"]:
                open_key, open_img = fr["file"], Image.open(project.path(fr["file"])).convert("RGB")
            return open_img

        for it in tqdm(sorted(keep, key=lambda x: x["frame"]), desc="  write" + (" + upscale" if upscale_to else "")):
            check_cancel()
            fr = frames[it["frame"]]
            pose = None
            if it["head"]:
                pose = cache.get(cache.entries[it["det"]]["poses"], tuple(it["head"]),
                                 lambda: face_pose(frame_img(fr), it["head"], detect_faces, detect_eyes))
            framing, view = classify(it["type"], it["general"], it["portrait"], pose)
            review = it["how"] == "track" or it["score"] > review_cut
            n_review += review
            folder = sorted_dir / ("_review" if review else "") / framing / view
            folder.mkdir(parents=True, exist_ok=True)
            stem = f"v{fr['vid']:02d}_{fr['t']:07.1f}s_{it['type']}"
            stems.append(stem)
            embs.append(it["emb"])
            ccips.append(F[dets[it["det"]]["feat"]] if it["type"] == "full"
                         else cache.entries[it["det"]]["crops"][it["type"]]["ccip"])
            factor = upscale_factor(it["box"], upscale_to) if upscale_to else 1.0
            n_up += factor > 1
            cut = lambda: frame_img(fr).crop(it["box"])
            png = cache.image(it["det"], it["type"], upscale_to if factor > 1 else 0,
                              lambda: upscale(cut(), factor, upscale_with_cdc) if factor > 1 else cut())
            link_or_copy(png, folder / f"{stem}.png")
            caption = make_caption(name, it["rating"], it["general"], core, series, screencap)
            (folder / f"{stem}.txt").write_text(caption, encoding="utf-8")
            dist[(framing, view)] += 1
            meta.append({"file": str((folder / f"{stem}.png").relative_to(out_dir)), "det": it["det"], "vid": fr["vid"],
                         "t": fr["t"], "type": it["type"], "ccip": it["score"], "how": it["how"],
                         "sharp": round(it["sharp"], 1), "framing": framing, "view": view, "caption": caption,
                         "upscaled": round(factor, 2), "pose": pose})
    finally:
        cache.save()

    np.savez_compressed(out_dir / "emb.npz", stems=np.array(stems), emb=np.stack(embs).astype(np.float16))
    np.savez_compressed(out_dir / negatives.FEATS, stems=np.array(stems), feats=np.stack(ccips), refs=refs)
    project.save(f"characters/{out_dir.name}/build.json",
                 {"name": name, "series": series, "clusters": cluster_ids, "other_clusters": other_ids,
                  "ref_dir": str(ref_dir) if ref_dir else None,
                  "threshold": threshold, "core_tags": sorted(core), "items": meta})
    outfit_lines = []
    if outfits:
        from .outfits import run_outfits
        found = run_outfits(project, name)
        outfit_lines = [f"Outfit {o['token']}: {o['count']} body crops - {', '.join(o['tags'])}" for o in found]
    report = make_report(name, keep, core, dist, n_review, len(chosen), n_track, dropped, best_scores, threshold,
                         n_up, upscale_to, min_size, outfit_lines, others_line)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"Review:  {sorted_dir}\n  - check the _review folder first, delete anything that is not {name}\n"
          f"  - then run:  alds.bat export -p {project.name} -n {name}")


def score_histogram(scores):
    edges = (0,) + SCORE_BINS + (9,)
    counts = np.histogram(scores, bins=edges)[0]
    labels = [f"<{SCORE_BINS[0]}"] + [f"{a}-{b}" for a, b in zip(SCORE_BINS, SCORE_BINS[1:])] + [f">{SCORE_BINS[-1]}"]
    return "  ".join(f"{l}:{c}" for l, c in zip(labels, counts))


def make_report(name, keep, core, dist, n_review, n_frames, n_track, dropped, best_scores, threshold,
                n_up, upscale_to, min_size, outfit_lines=(), others_line=""):
    lines = [f"Character: {name}",
             f"Frames matched: {n_frames} ({n_track} via shot tracking) at threshold {threshold}",
             *([others_line] if others_line else []),
             f"Best CCIP score per frame (lower = more alike): {score_histogram(best_scores)}",
             "Dropped crops: " + (", ".join(f"{v} {k}" for k, v in dropped.items() if v) or "-"),
             f"Images written: {len(keep)}  ({n_review} placed in _review for a manual check)",
             f"Upscaled with the anime model to ~{upscale_to}px: {n_up} (min crop size {min_size}px)"
             if upscale_to else f"Upscaling: off (min crop size {min_size}px)",
             f"Core tags removed from captions (absorbed by '{name}'): {', '.join(sorted(core)) or '-'}",
             *(outfit_lines or ["Outfits: one outfit (no outfit tokens)"]), "",
             "framing \\ view   " + "".join(f"{'3/4' if v == 'three_quarter' else v:>8}" for v in VIEWS) + "   total"]
    for f in FRAMINGS:
        row = [dist[(f, v)] for v in VIEWS]
        if sum(row):
            lines.append(f"{f:<16} " + "".join(f"{x:>8}" for x in row) + f"{sum(row):>8}")
    tag_cnt = Counter(t for it in keep for t in it["general"] if t not in core)
    lines += ["", "Most common tags: " + ", ".join(f"{t} ({c})" for t, c in tag_cnt.most_common(30)), ""]
    return "\n".join(lines)
