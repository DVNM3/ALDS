import numpy as np

from . import negatives, positives
from .cancel import check as check_cancel

THRESHOLD_GAP = 0.015
COMPETITOR_GAP = 0.02


def last_build(project, char):
    from .build import DEFAULT_THRESHOLD
    meta = project.load(f"characters/{char.name}/build.json", {})
    return meta, meta.get("threshold", DEFAULT_THRESHOLD)


def review_scores(project, name):
    from .build import identity_score
    char = project.char_dir(name)
    features, refs = negatives.build_features(char)
    if refs is None or not features:
        return {}
    _, threshold = last_build(project, char)
    confirmed_names, confirmed = positives.load(char)
    _, rejected = negatives.load(char)
    others = negatives.other_features(char)
    if others is not None and len(others):
        others = others[identity_score(others, refs, confirmed) > threshold]
    competitors = negatives.combine(rejected, others)
    names = list(features)
    feats = np.stack(list(features.values()))
    scores = identity_score(feats, refs, confirmed)
    near = negatives.nearest(feats, competitors) if competitors is not None else [None] * len(names)
    result = {}
    for stem, score, neg in zip(names, scores, near):
        margin = None if neg is None else float(neg - score)
        risk = min((threshold - float(score)) / THRESHOLD_GAP,
                   margin / COMPETITOR_GAP if margin is not None else float("inf"))
        result[stem] = {"score": float(score), "margin": margin,
                        "confirmed": stem in confirmed_names,
                        "uncertain": stem not in confirmed_names and risk <= 1,
                        "risk": risk}
    return result


class MemoryCache:
    def __init__(self):
        self.central = {}
        self.matches = {}

    def get(self, data, key, compute):
        if key not in data:
            data[key] = compute()
        return data[key]

    def scores(self, key, ids, compute):
        return self.get(self.matches, (key, tuple(ids)), lambda: compute(ids))


def preview_impact(project, name, limit=24):
    from .build import other_characters, select
    from .scan import load_state
    char = project.char_dir(name)
    _, refs = negatives.build_features(char)
    if refs is None or not len(refs):
        raise SystemExit("Build this character once to save its identity features.")
    frames, dets, features = load_state(project)
    if not dets or features is None or not len(features):
        raise SystemExit("Scan the episodes before previewing identity feedback.")
    frames = [dict(frame, deleted=False) for frame in frames]
    meta, threshold = last_build(project, char)
    settings = meta.get("settings", {})
    relax = settings.get("relax", 1.0)
    clusters = meta.get("clusters", [])
    confirmed_names, confirmed = positives.load(char)
    rejected_names, rejected = negatives.load(char)
    cache = MemoryCache()

    def choose(positive=None, negative=None):
        check_cancel()
        others = (other_characters(project, clusters, refs, dets, features, threshold, cache, positive)[0]
                  if settings.get("auto_reject", True) else None)
        return select(frames, dets, features, refs, threshold, relax, cache,
                      negatives.combine(others, negative), positive)[0]

    before, after = choose(), choose(confirmed, rejected)
    added, removed = set(after) - set(before), set(before) - set(after)
    switched = {i for i in set(before) & set(after) if before[i][0]["id"] != after[i][0]["id"]}
    rows = []
    for index in sorted(added | removed | switched)[:limit]:
        check_cancel()
        old, new, frame = before.get(index), after.get(index), frames[index]
        row = {"vid": frame["vid"], "t": frame["t"], "frame": frame["file"],
               "change": "new match" if index in added else "no longer matched" if index in removed else "different person",
               "before": float(old[1]) if old else None, "after": float(new[1]) if new else None,
               "before_box": old[0]["box"] if old else None, "after_box": new[0]["box"] if new else None}
        rows.append(row)
    return {"before": len(before), "after": len(after), "added": len(added), "removed": len(removed),
            "switched": len(switched), "confirmed": len(confirmed_names), "rejected": len(rejected_names),
            "threshold": threshold, "items": rows, "project": project.name, "character": name}
