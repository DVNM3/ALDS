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
from .cancel import Cancelled, check as check_cancel
from .captions import (FRAMING_TAGS, appearance_tags, classify, low_scores, make_caption, people_count,
                       recover_details)
from .common import box_area, box_iou, frame_in_use, save_json
from .identity import ccip_cross, ccip_features
from . import negatives, positives
from .scan import load_state
from .upscale import DEFAULT as DEFAULT_UPSCALER, LABELS as UPSCALER_LABELS, factor_for, upscale_image

DEFAULT_THRESHOLD = 0.13
MIN_CONTRAST = 18.0
TEXT_MIN_CONF = 0.75
OFFMODEL_TAGS = ("chibi", "super deformed", "blurry")
MONOCHROME_TAGS = ("monochrome", "greyscale", "sepia")
OTHER_PER_CLUSTER = 16
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


def other_characters(project, cluster_ids, refs, dets, F, threshold, cache, confirmed=None):
    data = project.load("scan/clusters.json") or {"clusters": []}
    feats, used = [], []
    for c in data["clusters"]:
        if c["id"] in cluster_ids:
            continue
        fc = most_central(F[[dets[m]["feat"] for m in c["members"]]], 4 * OTHER_PER_CLUSTER, cache)
        fc = fc[identity_score(fc, refs, confirmed) > threshold][:OTHER_PER_CLUSTER]
        if len(fc):
            feats.append(fc)
            used.append(c["id"])
    return (np.concatenate(feats) if feats else None), used


def match_score(feats, refs):
    k = max(1, min(5, len(refs) // 4))
    return np.sort(ccip_cross(feats, refs), axis=1)[:, :k].mean(1)


def identity_score(feats, refs, confirmed=None):
    score = match_score(feats, refs)
    if confirmed is not None and len(confirmed):
        score = np.minimum(score, negatives.nearest(feats, confirmed))
    return score


def select(frames, dets, F, refs, threshold, relax, cache, negs=None, confirmed=None):
    elig = [d for d in dets if d["feat"] >= 0 and frame_in_use(frames[d["frame"]])]
    feats_of = lambda ids: F[[dets[i]["feat"] for i in ids]]
    ids = [d["id"] for d in elig]
    scores = cache.scores(digest(refs, F), ids, lambda ids: match_score(feats_of(ids), refs))
    if confirmed is not None and len(confirmed):
        scores = np.minimum(scores, cache.scores("pos:" + digest(confirmed, F), ids,
                                                 lambda ids: negatives.nearest(feats_of(ids), confirmed)))
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


def alone(det, frame_dets):
    return all(o["id"] == det["id"] for o in frame_dets)


def image_stats(img):
    g = np.asarray(img.convert("L"))
    s = 512 / max(g.shape)
    g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()), float(g.std())


def read_text(img, ocr):
    return [(txt, float(score)) for _, txt, score in ocr(img)]


def has_text(words):
    return any(score >= TEXT_MIN_CONF and len(re.sub(r"[\W_]", "", txt)) >= 3 for txt, score in words)


def dedup(items, sim):
    if not items:
        return []
    E = np.stack([it["emb"] for it in items])
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    quality = np.array([np.log1p(it["sharp"]) + 0.5 * np.log(box_area(it["box"])) for it in items])
    kept = []
    for i in np.argsort(-quality):
        if kept and float((E[kept] @ E[i]).max()) >= sim:
            continue
        kept.append(int(i))
    return [items[i] for i in kept]


def check_overwrite(project, name, overwrite):
    sorted_dir = project.char_dir(name) / "sorted"
    if sorted_dir.exists() and not overwrite:
        raise SystemExit(f"{sorted_dir} already exists (your reviewed images?). Use --overwrite to rebuild it.")


def run_build(project, name, cluster_ids, ref_dir, threshold, relax, min_height, sim, series,
              screencap, tagger, keep_text, keep_offmodel, save_dropped, overwrite,
              upscale_to=0, outfits=True, fresh=False, auto_reject=True, keep_mono=False, preview_limit=0,
              upscaler=DEFAULT_UPSCALER, upscale_version="auto"):
    from imgutils.ocr import ocr
    from imgutils.tagging import get_wd14_tags
    from imgutils.validate import anime_portrait

    project.require_frames()
    frames, dets, F = load_state(project)
    if not dets:
        raise SystemExit("nothing scanned yet - run scan first")
    out_dir = project.preview_dir(name) if preview_limit else project.char_dir(name)
    sorted_dir = out_dir / "sorted"
    if not preview_limit:
        check_overwrite(project, name, overwrite)
    if sorted_dir.exists():
        shutil.rmtree(sorted_dir)
        shutil.rmtree(out_dir / "_deleted", ignore_errors=True)

    cache = CropCache(project, fresh and not preview_limit)
    preview_rows = []

    def preview_image(img, fr, reason, score=None):
        img = img.copy()
        img.thumbnail((512, 512))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"v{fr['vid']:02d}_{fr['n']:06d}.jpg"
        img.save(path, quality=90)
        preview_rows.append({"file": str(path), "reason": reason, "score": score})

    try:
        threshold = threshold or DEFAULT_THRESHOLD
        refs = reference_features(project, cluster_ids, ref_dir, dets, F, cache)
        confirmed_names, confirmed = positives.load(project.char_dir(name))
        neg_names, negs = negatives.load(project.char_dir(name))
        others, other_ids = (other_characters(project, cluster_ids, refs, dets, F, threshold, cache, confirmed)
                             if auto_reject else (None, []))
        negs = negatives.combine(negs, others)
        chosen, best_scores, n_rejected = select(frames, dets, F, refs, threshold, relax, cache, negs, confirmed)
        if confirmed_names:
            print(f"[build] {len(confirmed_names)} confirmed identity references")
        n_track = sum(1 for v in chosen.values() if v[2] == "track")
        print(f"[build] matched {len(chosen)} frames ({n_track} via shot tracking), threshold {threshold}")
        sources = ([f"{len(other_ids)} other clusters"] if other_ids else []) + (
            [f"{len(neg_names)} images rejected in review"] if neg_names else [])
        others_line = (f"{n_rejected} frames left out as other characters (from {' and '.join(sources)})"
                       if sources else "")
        if others_line:
            print("        " + others_line)
        print("        best score per frame: " + score_histogram(best_scores))
        if not chosen and not preview_limit:
            raise SystemExit("no matches - try a higher --threshold or other clusters/refs")

        if preview_limit:
            eligible = sorted({d["frame"] for d in dets if d["feat"] >= 0 and frame_in_use(frames[d["frame"]])})
            indices = np.linspace(0, len(eligible) - 1, min(preview_limit, len(eligible)), dtype=int)
            sampled = {eligible[i] for i in indices}
            for fi in sorted(sampled - chosen.keys()):
                check_cancel()
                candidates = [d for d in dets if d["frame"] == fi and d["feat"] >= 0]
                scores = identity_score(F[[d["feat"] for d in candidates]], refs, confirmed)
                best = int(np.argmin(scores))
                d, score = candidates[best], float(scores[best])
                fr = frames[fi]
                with Image.open(project.path(fr["file"])) as image:
                    preview_image(image.convert("RGB"), fr,
                                  "identity threshold" if score > threshold else "looks like another character", score)
            chosen = {fi: value for fi, value in chosen.items() if fi in sampled}

        dets_by_frame = defaultdict(list)
        for d in dets:
            dets_by_frame[d["frame"]].append(d)

        dropped_dir = out_dir / "_dropped"
        if dropped_dir.exists():
            shutil.rmtree(dropped_dir)
        items, dropped = [], Counter()

        def drop(reason, image, fr):
            dropped[reason] += 1
            if preview_limit:
                preview_image(image(), fr, reason)
            elif save_dropped:
                folder = dropped_dir / reason.replace(" ", "_").replace("/", "")
                folder.mkdir(parents=True, exist_ok=True)
                image().save(folder / f"v{fr['vid']:02d}_{fr['t']:07.1f}s.jpg", quality=90)

        def wd14(img):
            rating, general, _chars, emb = get_wd14_tags(
                img, model_name=tagger, general_threshold=0.35, no_underline=True, drop_overlap=True,
                fmt=("rating", "general", "character", "embedding"))
            return rating, general, emb

        n_new = 0
        for fi in tqdm(sorted(chosen), desc="  analyse", unit="f"):
            check_cancel()
            det, score, how = chosen[fi]
            fr = frames[fi]
            entry, computed = cache.entry(det, fr), cache.computed
            rec = entry["crops"].setdefault("scene", {})
            frame = functools.cache(lambda: Image.open(project.path(fr["file"])).convert("RGB"))
            if not alone(det, dets_by_frame[fi]):
                drop("another character in the scene", frame, fr)
                continue
            if det["rh"] < min_height:
                drop("character too small in the scene", frame, fr)
                continue
            sharp, contrast = cache.get(rec, "stats", lambda: image_stats(frame()))
            if contrast < MIN_CONTRAST:
                drop("dark or faded", frame, fr)
                continue
            if not keep_text and has_text(cache.get(rec, "ocr", lambda: read_text(frame(), ocr))):
                drop("text on screen", frame, fr)
                continue
            rating, general, emb = cache.get(rec.setdefault("tags", {}), tagger, lambda: wd14(frame()))
            if people_count(general) > 1:
                drop("another character in the scene", frame, fr)
                continue
            if not keep_offmodel and any(t in general for t in OFFMODEL_TAGS):
                drop("chibi or blurry", frame, fr)
                continue
            if not keep_mono and any(t in general for t in MONOCHROME_TAGS):
                drop("black and white or sepia", frame, fr)
                continue
            portrait = None
            if not any(t in general for t, _ in FRAMING_TAGS):
                portrait = cache.get(rec, "portrait", lambda: anime_portrait(frame().crop(det["box"]))[0])
            items.append({"frame": fi, "det": det["id"], "type": "scene", "box": det["box"], "score": round(score, 4),
                          "how": how, "sharp": sharp, "rating": rating, "general": general, "emb": emb,
                          "portrait": portrait, "head": det["head"]})
            n_new += cache.computed > computed
        print(f"[build] {len(chosen) - n_new} frames reused from the saved analysis, {n_new} analysed now")
        n_scenes = len(items) + sum(dropped.values())
        keep = dedup(items, sim)
        dropped["near-duplicate"] = len(items) - len(keep)
        print(f"[build] {n_scenes} scenes -> {len(keep)} kept "
              f"(dropped: {', '.join(f'{v} {k}' for k, v in dropped.items() if v)})")

        if preview_limit:
            accepted = {it["frame"] for it in keep}
            for it in items:
                check_cancel()
                fr = frames[it["frame"]]
                with Image.open(project.path(fr["file"])) as image:
                    preview_image(image.convert("RGB"), fr,
                                  "accepted" if it["frame"] in accepted else "near-duplicate", it["score"])
            result = {"frames": len(sampled), "accepted": len(keep), "items": preview_rows}
            save_json(out_dir / "preview.json", result)
            print(f"[preview] {len(sampled)} sampled frames; {len(keep)} accepted scenes. "
                  "Duplicates are checked within the sample; upscaling and outfits run on a full build.")
            return result

        if not keep:
            raise SystemExit("no usable scenes after filtering - preview the settings before rebuilding")

        from imgutils.detect import detect_eyes, detect_faces
        recovered = Counter()
        try:
            found, recovered = recover_details([it["general"] for it in keep],
                                               low_scores([it["emb"] for it in keep], tagger))
        except Exception as e:
            found = [it["general"] for it in keep]
            print(f"[build] small details were not checked again: {e}")
        for it, general in zip(keep, found):
            it["caption_tags"] = general
        appearance = appearance_tags(found)
        review_cut = threshold * 0.85
        meta, dist, n_review, n_up, stems, embs, ccips = [], Counter(), 0, 0, [], [], []
        sizes = {v["id"]: (v["width"], v["height"]) for v in project.load("project.json")["videos"]}
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
            stem = f"v{fr['vid']:02d}_{fr['t']:07.1f}s_scene"
            stems.append(stem)
            embs.append(it["emb"])
            ccips.append(F[dets[it["det"]]["feat"]])
            factor = factor_for(*sizes[fr["vid"]], upscale_to) if upscale_to else 1.0
            n_up += factor > 1
            key = f"{upscale_to}{upscaler}" + ("" if upscale_version == "auto" else f"x{upscale_version}")
            png = cache.image(it["det"], "scene", key if factor > 1 else 0,
                              lambda: (upscale_image(frame_img(fr), factor, upscaler, upscale_version) if factor > 1
                                       else frame_img(fr)))
            link_or_copy(png, folder / f"{stem}.png")
            caption = make_caption(name, it["rating"], it["caption_tags"], series, screencap)
            (folder / f"{stem}.txt").write_text(caption, encoding="utf-8")
            dist[(framing, view)] += 1
            meta.append({"file": str((folder / f"{stem}.png").relative_to(out_dir)), "det": it["det"], "vid": fr["vid"],
                         "t": fr["t"], "type": it["type"], "ccip": it["score"], "how": it["how"],
                         "sharp": round(it["sharp"], 1), "framing": framing, "view": view, "caption": caption,
                         "upscaled": round(factor, 2), "upscaler": upscaler if factor > 1 else None, "pose": pose})
    except (Cancelled, KeyboardInterrupt):
        cache.discard()
        raise
    finally:
        cache.save()

    np.savez_compressed(out_dir / "emb.npz", stems=np.array(stems), emb=np.stack(embs).astype(np.float16))
    np.savez_compressed(out_dir / negatives.FEATS, stems=np.array(stems), feats=np.stack(ccips), refs=refs,
                        others=others if others is not None else np.empty((0, refs.shape[1]), np.float32))
    project.save(f"characters/{out_dir.name}/build.json",
                 {"name": name, "series": series, "clusters": cluster_ids, "other_clusters": other_ids,
                  "ref_dir": str(ref_dir) if ref_dir else None,
                  "threshold": threshold, "appearance_tags": appearance, "items": meta,
                  "settings": {"threshold": threshold, "relax": relax, "min_height": min_height, "sim": sim,
                               "tagger": tagger, "upscale_to": upscale_to, "upscaler": upscaler if upscale_to else None,
                               "upscale_version": upscale_version if upscale_to else None,
                               "outfits": outfits, "auto_reject": auto_reject, "keep_mono": keep_mono,
                               "keep_text": keep_text, "keep_offmodel": keep_offmodel,
                               "screencap": screencap}})
    outfit_lines = []
    if outfits:
        from .outfits import run_outfits
        found = run_outfits(project, name)
        outfit_lines = [f"Outfit {o['token']}: {o['count']} images - {', '.join(o['tags'])}" for o in found]
    report = make_report(name, keep, appearance, recovered, dist, n_review, len(chosen), n_track, dropped, best_scores,
                         threshold, n_up, upscale_to, min_height, outfit_lines, others_line, upscaler, upscale_version)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"Review:  {sorted_dir}\n  - check the _review folder first, delete anything that is not {name}\n"
          f"  - then run:  alds.bat export -p {project.name} -n {name}")


def score_histogram(scores):
    edges = (0,) + SCORE_BINS + (9,)
    counts = np.histogram(scores, bins=edges)[0]
    labels = [f"<{SCORE_BINS[0]}"] + [f"{a}-{b}" for a, b in zip(SCORE_BINS, SCORE_BINS[1:])] + [f">{SCORE_BINS[-1]}"]
    return "  ".join(f"{l}:{c}" for l, c in zip(labels, counts))


def make_report(name, keep, appearance, recovered, dist, n_review, n_frames, n_track, dropped, best_scores, threshold,
                n_up, upscale_to, min_height, outfit_lines=(), others_line="", upscaler=DEFAULT_UPSCALER,
                upscale_version="auto"):
    lines = [f"Character: {name}",
             f"Frames matched: {n_frames} ({n_track} via shot tracking) at threshold {threshold}",
             *([others_line] if others_line else []),
             f"Best CCIP score per frame (lower = more alike): {score_histogram(best_scores)}",
             f"Scenes with the character alone, at least {min_height:.0%} of the frame height",
             "Scenes left out: " + (", ".join(f"{v} {k}" for k, v in dropped.items() if v) or "-"),
             f"Images written: {len(keep)}  ({n_review} placed in _review for a manual check)",
             f"Upscaled with {UPSCALER_LABELS[upscaler]}"
             + ("" if upscale_version == "auto" else f", {upscale_version}x version")
             + f", to ~{upscale_to}px: {n_up}"
             if upscale_to else "Upscaling: off",
             f"Appearance tags (all kept; move the ones '{name}' should learn in the Tags tab): "
             f"{', '.join(appearance) or '-'}",
             "Small details also found by comparing with the other images: "
             + (", ".join(f"{t} +{c}" for t, c in recovered.most_common()) or "-"),
             *(outfit_lines or ["Outfits: one outfit (no outfit tokens)"]), "",
             "framing \\ view   " + "".join(f"{'3/4' if v == 'three_quarter' else v:>8}" for v in VIEWS) + "   total"]
    for f in FRAMINGS:
        row = [dist[(f, v)] for v in VIEWS]
        if sum(row):
            lines.append(f"{f:<16} " + "".join(f"{x:>8}" for x in row) + f"{sum(row):>8}")
    tag_cnt = Counter(t for it in keep for t in it["caption_tags"])
    lines += ["", "Most common tags: " + ", ".join(f"{t} ({c})" for t, c in tag_cnt.most_common(30)), ""]
    return "\n".join(lines)
