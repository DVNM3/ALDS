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
from .cache import CropCache, digest, file_hash, link_or_copy
from .cancel import Cancelled, check as check_cancel
from .captions import (FRAMING_TAGS, appearance_tags, classify, low_scores, make_caption, people_count,
                       recover_details)
from .common import FRAMING, IMAGE_EXTS, VIEW, box_area, box_iou, frame_in_use, safe_name, save_json
from .i18n import t
from .identity import ccip_cross, ccip_features
from . import negatives, positives
from .pick import image_files
from .scan import load_state
from .upscale import DEFAULT as DEFAULT_UPSCALER, LABELS as UPSCALER_LABELS, factor_for, upscale_image

DEFAULT_THRESHOLD = 0.13
MIN_CONTRAST = 18.0
TEXT_MIN_CONF = 0.75
OFFMODEL_TAGS = ("chibi", "super deformed", "blurry")
MONOCHROME_TAGS = ("monochrome", "greyscale", "sepia")
OTHER_PER_CLUSTER = 16
NEAR_MISS = 0.02


def open_image(path):
    with Image.open(path) as source:
        if "A" in source.getbands() or "transparency" in source.info:
            rgba = source.convert("RGBA")
            return Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("RGB")
        return source.convert("RGB")


def largest(found):
    return list(max(found, key=lambda x: box_area(x[0]))[0]) if found else None


def own_images(own_dir, cache):
    from imgutils.detect import detect_heads, detect_person
    out, stems = [], set()
    for path in image_files(own_dir):
        check_cancel()
        key = "own-" + file_hash(path, "sha1")
        rec = cache.entries.setdefault(key, {"sig": key, "crops": {"scene": {}}, "poses": {}})
        scene = rec["crops"]["scene"]
        image = functools.cache(lambda path=path: open_image(path))
        size = cache.get(scene, "size", lambda: image().size)
        box = cache.get(scene, "person", lambda: largest(detect_person(image(), conf_threshold=0.35))
                        or [0, 0, *image().size])
        head = cache.get(scene, "head", lambda: largest(detect_heads(image())))
        feat = cache.get(scene, "ccip", lambda: ccip_features([image().crop(box)])[0])
        stem = "own_" + safe_name(path.stem)
        if stem in stems:
            stem += "_" + path.suffix.lstrip(".").lower()
        stems.add(stem)
        out.append({"path": path, "key": key, "rec": rec, "image": image, "size": size, "box": box, "head": head,
                    "feat": feat, "stem": stem})
    return out


def reference_features(project, cluster_ids, ref_dir, dets, F, cache, own=()):
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
        print("  • " + t("{n} reference images", n=len(imgs)))
    if own:
        refs.append(np.stack([o["feat"] for o in own]).astype(np.float32))
        print("  • " + t("{n} of your images help to find the character", n=len(own)))
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
              upscaler=DEFAULT_UPSCALER, upscale_version="auto", own_dir=None, own_in_set=True, own_refs=True):
    from imgutils.ocr import ocr
    from imgutils.tagging import get_wd14_tags
    from imgutils.validate import anime_portrait

    frames, dets, F = load_state(project)
    has_own = bool(image_files(own_dir))
    add_own = has_own and own_in_set and not preview_limit
    use_episodes = bool(cluster_ids or ref_dir or (has_own and own_refs and dets))
    if use_episodes:
        project.require_frames()
        if not dets:
            raise SystemExit("nothing scanned yet - run scan first")
    elif not add_own:
        raise SystemExit("give --cluster and/or --ref")
    out_dir = project.preview_dir(name) if preview_limit else project.char_dir(name)
    sorted_dir = out_dir / "sorted"
    if not preview_limit:
        check_overwrite(project, name, overwrite)
    if sorted_dir.exists():
        shutil.rmtree(sorted_dir)
        shutil.rmtree(out_dir / "_deleted", ignore_errors=True)

    cache = CropCache(project, fresh and not preview_limit)
    preview_rows, lines = [], []
    n_steps = (2 if preview_limit else 3 + bool(outfits)) - (not use_episodes)
    done_steps = []

    def say(text):
        print(text)
        lines.append(text)

    def step(title):
        done_steps.append(title)
        say(t("Step {i} of {n}: {title}", i=len(done_steps), n=n_steps, title=title))

    def preview_image(img, fr, reason, score=None):
        img = img.copy()
        img.thumbnail((512, 512))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"v{fr['vid']:02d}_{fr['n']:06d}.jpg"
        img.save(path, quality=90)
        preview_rows.append({"file": str(path), "reason": reason, "score": score})

    try:
        threshold = threshold or DEFAULT_THRESHOLD
        own = own_images(own_dir, cache) if has_own and (add_own or own_refs) else []
        chosen, confirmed, others, other_ids = {}, None, None, []
        if use_episodes:
            step(t("Finding the character"))
            refs = reference_features(project, cluster_ids, ref_dir, dets, F, cache, own if own_refs else ())
            confirmed_names, confirmed = positives.load(project.char_dir(name))
            neg_names, negs = negatives.load(project.char_dir(name))
            others, other_ids = (other_characters(project, cluster_ids, refs, dets, F, threshold, cache, confirmed)
                                 if auto_reject else (None, []))
            negs = negatives.combine(negs, others)
            chosen, best_scores, n_rejected = select(frames, dets, F, refs, threshold, relax, cache, negs, confirmed)
            if confirmed_names:
                say("  • " + t("{n} images you confirmed help to find the character", n=len(confirmed_names)))
            n_track = sum(1 for v in chosen.values() if v[2] == "track")
            say("  • " + t("{n} frames show the character (match threshold {threshold})", n=len(chosen),
                           threshold=threshold)
                + (t(", {n} of them found by following the shot", n=n_track) if n_track else ""))
            sources = ([t("{n} other clusters", n=len(other_ids))] if other_ids else []) + (
                [t("{n} images rejected in the review", n=len(neg_names))] if neg_names else [])
            if sources:
                say("  • " + t("{n} frames left out because the character there looks more like someone else "
                               "({sources})", n=n_rejected, sources=t(" and ").join(sources)))
            near = sum(threshold < score <= threshold + NEAR_MISS for score in best_scores)
            if near:
                say("  • " + t("{n} more frames are just above the match threshold. Raising it to {value} would "
                               "add them, but other characters may slip in.", n=near,
                               value=round(threshold + NEAR_MISS, 3)))
            if not chosen and not preview_limit and not add_own:
                raise SystemExit("no matches - try a higher --threshold or other clusters/refs")
        else:
            refs = np.stack([o["feat"] for o in own]).astype(np.float32)

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

        step(t("Checking each scene") if use_episodes else t("Tagging your images"))
        for fi in tqdm(sorted(chosen), desc=t("Checking each scene"), unit=t("scenes")):
            check_cancel()
            det, score, how = chosen[fi]
            fr = frames[fi]
            rec = cache.entry(det, fr)["crops"].setdefault("scene", {})
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
        n_scenes = len(items) + sum(dropped.values())
        keep = dedup(items, sim)
        dropped["near-duplicate"] = len(items) - len(keep)
        if use_episodes:
            say("  • " + t("{kept} of {n} scenes kept. Only scenes with the character alone and at least {share} of "
                           "the frame height are used.", kept=len(keep), n=n_scenes, share=f"{min_height:.0%}"))
        if any(dropped.values()):
            say("  • " + t("Left out: {reasons}", reasons=t(", ").join(
                t("{reason}: {n}", reason=t(k), n=v) for k, v in dropped.items() if v)))
        if add_own:
            for o in tqdm(own, desc=t("Tagging your images"), unit=t("images")):
                check_cancel()
                rec = o["rec"]["crops"]["scene"]
                sharp, _ = cache.get(rec, "stats", lambda: image_stats(o["image"]()))
                rating, general, emb = cache.get(rec.setdefault("tags", {}), tagger, lambda: wd14(o["image"]()))
                portrait = None
                if not any(t in general for t, _ in FRAMING_TAGS):
                    portrait = cache.get(rec, "portrait", lambda: anime_portrait(o["image"]().crop(o["box"]))[0])
                score = float(identity_score(o["feat"][None], refs, confirmed)[0])
                keep.append({"own": o, "type": "own", "box": o["box"], "score": round(score, 4), "how": "own",
                             "sharp": sharp, "rating": rating, "general": general, "emb": emb, "portrait": portrait,
                             "head": o["head"]})
            say("  • " + t("{n} of your images added. They skip the filters: every one you add is kept.",
                           n=len(own)))

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
            say("")
            say(t("✅ Preview ready: {accepted} of {frames} sampled frames accepted. Enlarging and outfits are done "
                  "only in the full build.", accepted=len(keep), frames=len(sampled)))
            return result

        if not keep:
            raise SystemExit("no usable scenes after filtering - preview the settings before rebuilding")

        step(t("Saving the images and captions, enlarging the small scenes") if upscale_to
             else t("Saving the images and captions"))
        from imgutils.detect import detect_eyes, detect_faces
        recovered = Counter()
        try:
            found, recovered = recover_details([it["general"] for it in keep],
                                               low_scores([it["emb"] for it in keep], tagger))
        except Exception as e:
            found = [it["general"] for it in keep]
            say("  • " + t("Small details were not checked again: {error}", error=e))
        for it, general in zip(keep, found):
            it["caption_tags"] = general
        appearance = appearance_tags(found)
        review_cut = threshold * 0.85
        meta, dist, n_review, n_up, stems, embs, ccips = [], Counter(), 0, 0, [], [], []
        sizes = {v["id"]: (v["width"], v["height"]) for v in project.load("project.json", {"videos": []})["videos"]}
        open_key = open_img = None

        def frame_img(fr):
            nonlocal open_key, open_img
            if open_key != fr["file"]:
                open_key, open_img = fr["file"], Image.open(project.path(fr["file"])).convert("RGB")
            return open_img

        order = lambda x: ("own" in x, x.get("frame", 0), x["own"]["stem"] if "own" in x else "")
        for it in tqdm(sorted(keep, key=order), desc=t("Saving the images"), unit=t("images")):
            check_cancel()
            mine = it.get("own")
            fr = None if mine else frames[it["frame"]]
            source = mine["image"] if mine else functools.partial(frame_img, fr)
            poses = mine["rec"]["poses"] if mine else cache.entries[it["det"]]["poses"]
            pose = None
            if it["head"]:
                pose = cache.get(poses, tuple(it["head"]),
                                 lambda: face_pose(source(), it["head"], detect_faces, detect_eyes))
            framing, view = classify(it["type"], it["general"], it["portrait"], pose)
            review = not mine and (it["how"] == "track" or it["score"] > review_cut)
            n_review += review
            folder = sorted_dir / ("_review" if review else "") / framing / view
            folder.mkdir(parents=True, exist_ok=True)
            stem = mine["stem"] if mine else f"v{fr['vid']:02d}_{fr['t']:07.1f}s_scene"
            stems.append(stem)
            embs.append(it["emb"])
            ccips.append(mine["feat"] if mine else F[dets[it["det"]]["feat"]])
            size = mine["size"] if mine else sizes[fr["vid"]]
            factor = factor_for(*size, upscale_to) if upscale_to else 1.0
            n_up += factor > 1
            key = f"{upscale_to}{upscaler}" + ("" if upscale_version == "auto" else f"x{upscale_version}")
            png = cache.image(mine["key"] if mine else it["det"], "scene", key if factor > 1 else 0,
                              lambda: (upscale_image(source(), factor, upscaler, upscale_version) if factor > 1
                                       else source()))
            link_or_copy(png, folder / f"{stem}.png")
            caption = make_caption(name, it["rating"], it["caption_tags"], series, screencap)
            (folder / f"{stem}.txt").write_text(caption, encoding="utf-8")
            dist[(framing, view)] += 1
            meta.append({"file": str((folder / f"{stem}.png").relative_to(out_dir)), "det": it.get("det"),
                         "vid": fr["vid"] if fr else None, "t": fr["t"] if fr else None, "type": it["type"],
                         "ccip": it["score"], "how": it["how"], "sharp": round(it["sharp"], 1), "framing": framing,
                         "view": view, "caption": caption, "upscaled": round(factor, 2),
                         "upscaler": upscaler if factor > 1 else None, "pose": pose,
                         **({"own": mine["path"].name} if mine else {})})
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
                               "screencap": screencap,
                               **({"own_in_set": own_in_set, "own_refs": own_refs} if has_own else {})}})
    say("  • " + t("{n} images saved, {r} of them marked ⚠ to check", n=len(keep), r=n_review))
    if upscale_to:
        model = t(UPSCALER_LABELS[upscaler]) + ("" if upscale_version == "auto" else f" · {upscale_version}x")
        say("  • " + t("{n} small scenes enlarged to about {size} px with {model}", n=n_up, size=upscale_to,
                       model=model))
    if recovered:
        say("  • " + t("Small details also found by comparing the images: {tags}",
                       tags=", ".join(f"{tag} +{c}" for tag, c in recovered.most_common())))
    if outfits:
        from .outfits import run_outfits
        step(t("Separating the outfits"))
        run_outfits(project, name, say)
    say("")
    say(t("✅ Done: {n} images of {name}.", n=len(keep), name=name))
    say(t("Shots and angles:"))
    for framing in FRAMING:
        row = [(view, dist[(framing, view)]) for view in VIEW if dist[(framing, view)]]
        if row:
            say("  • " + t("{shot}: {angles} (total {n})", shot=t(FRAMING[framing]), n=sum(c for _, c in row),
                           angles=t(", ").join(f"{t(VIEW[view]).lower()} {c}" for view, c in row)))
    say(t("Appearance tags (all stay in the captions; in the Tags tab you pick the ones {name} should learn): "
          "{tags}", name=name, tags=", ".join(appearance) or "-"))
    tag_cnt = Counter(tag for it in keep for tag in it["caption_tags"])
    say(t("Most common tags: {tags}", tags=", ".join(f"{tag} ({c})" for tag, c in tag_cnt.most_common(30))))
    (out_dir / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
