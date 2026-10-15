import re
from collections import Counter
from pathlib import Path

import numpy as np

from .i18n import t
from .tags import absorb, edit_tags, restore, split_tags

GARMENTS = {
    "shirt", "jacket", "coat", "vest", "dress", "uniform", "kimono", "yukata", "armor", "armour", "swimsuit",
    "bikini", "hoodie", "sweater", "cape", "cloak", "robe", "cardigan", "blazer", "serafuku", "tuxedo", "suit",
    "top", "camisole", "leotard", "bodysuit", "gown", "blouse", "tunic", "parka", "raincoat", "apron",
    "overalls", "sleeveless", "scarf", "haori", "poncho", "shawl", "corset", "bra", "necktie",
}
CONSTANT_SHARE = 0.6
SEED_MIN = 5
PURITY_MIN = 0.75
VOTE_MIN = 0.7
K = 7
MIN_COUNT, MIN_SHARE = 8, 0.08


def garment_nouns(tags):
    out = set()
    for t in tags:
        if t.endswith(" sleeves"):
            out.add(t)
            continue
        hits = [w for w in re.split(r"[\s\-_()]+", t) if w in GARMENTS]
        if hits:
            out.add(hits[-1])
    return out


def _token_re(trigger):
    return re.compile(rf"^{re.escape(trigger)}_outfit\d+$")


def token_matcher(build, name):
    pattern = _token_re(build.get("name", name))
    named = {o["token"] for o in build.get("outfits", [])}
    return lambda tag: bool(pattern.match(tag)) or tag in named


def edit_captions(project, char, remove=(), replace=None, add=()):
    char_dir = project.char_dir(char)
    is_token = token_matcher(project.load(f"characters/{char_dir.name}/build.json", {}), char)
    changed = edit_tags(char_dir, remove, replace, add, is_token)
    sync_tokens(project, char, remove, replace)
    return changed


def protected(project, char):
    char_dir = project.char_dir(char)
    build = project.load(f"characters/{char_dir.name}/build.json", {})
    is_token = token_matcher(build, char)
    fixed = {build.get("name", char), build.get("series")}
    return lambda tag: is_token(tag) or tag in fixed


def absorb_captions(project, char, tags):
    return absorb(project.char_dir(char), tags, protected(project, char))


def restore_captions(project, char, tags):
    return restore(project.char_dir(char), tags)


def sync_tokens(project, char, remove=(), replace=None):
    char_dir = project.char_dir(char)
    build = project.load(f"characters/{char_dir.name}/build.json")
    if not build or not build.get("outfits"):
        return
    replace = replace or {}
    kept = []
    for o in build["outfits"]:
        if o["token"] in remove or (o["token"] in replace and not replace[o["token"]].strip()):
            continue
        o["token"] = replace.get(o["token"], o["token"]).strip()
        kept.append(o)
    build["outfits"] = kept
    project.save(f"characters/{char_dir.name}/build.json", build)


def resync_after_undo(project, char):
    from .tags import caption_files
    char_dir = project.char_dir(char)
    build = project.load(f"characters/{char_dir.name}/build.json")
    if not build or not build.get("outfits"):
        return
    used = {t for f in caption_files(char_dir) for t in split_tags(f.read_text(encoding="utf-8"))}
    for o in build["outfits"]:
        default = f"{build.get('name', char)}_outfit{o['id']}"
        if o["token"] not in used and default in used:
            o["token"] = default
    project.save(f"characters/{char_dir.name}/build.json", build)


def _knn_purity(E, labels, k=K):
    S = E @ E.T
    np.fill_diagonal(S, -np.inf)
    nn = np.argsort(-S, axis=1)[:, :k]
    same = (labels[nn] == labels[:, None]).mean(1)
    return {l: float(same[labels == l].mean()) for l in set(labels.tolist())}, nn


def run_outfits(project, name, say=print):
    from scipy.spatial.distance import pdist, squareform
    from sklearn.cluster import AgglomerativeClustering

    char_dir = project.char_dir(name)
    build = project.load(f"characters/{char_dir.name}/build.json")
    if not build:
        raise SystemExit(f"no build for '{name}' - run build first")
    name = build.get("name", name)
    is_token = token_matcher(build, name)
    files = {p.stem: p for p in (char_dir / "sorted").rglob("*.png")}
    frames = project.load("scan/frames.json", [])
    shot_of = {(f["vid"], f["t"]): f["shot"] for f in frames}
    emb = {}
    if (char_dir / "emb.npz").exists():
        z = np.load(char_dir / "emb.npz")
        emb = dict(zip(z["stems"].tolist(), z["emb"].astype(np.float32)))

    rows = []
    for it in build["items"]:
        p = files.get(Path(it["file"]).stem)
        if p is None or not p.with_suffix(".txt").exists():
            continue
        tags = [t for t in split_tags(p.with_suffix(".txt").read_text(encoding="utf-8")) if not is_token(t)]
        rows.append((it, p, tags))

    body = [r for r in rows if r[0]["type"] != "head" and r[1].stem in emb]
    outfits, assign = [], {}
    if len(body) >= 2 * MIN_COUNT:
        E = np.stack([emb[r[1].stem] for r in body])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        nouns = [garment_nouns(r[2]) for r in body]
        freq = Counter(n for s in nouns for n in s)
        cand = sorted(n for n, c in freq.items() if c >= SEED_MIN and c < CONSTANT_SHARE * len(body))

        seed_idx = [i for i, s in enumerate(nouns) if s & set(cand)]
        groups = {}
        if len(cand) >= 2 and len(seed_idx) >= 2 * SEED_MIN:
            X = np.array([[n in nouns[i] for n in cand] for i in seed_idx], dtype=bool)
            lab = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                          distance_threshold=0.6).fit(squareform(pdist(X, "jaccard"))).labels_
            for i, l in zip(seed_idx, lab):
                groups.setdefault(int(l), []).append(i)
            groups = {l: g for l, g in groups.items() if len(g) >= SEED_MIN}

        while len(groups) >= 2:
            idx = np.array([i for g in groups.values() for i in g])
            labs = np.array([l for l, g in groups.items() for _ in g])
            purity, nn = _knn_purity(E[idx], labs, min(K, len(idx) - 1))
            worst = min(purity, key=purity.get)
            if purity[worst] >= PURITY_MIN:
                break
            confused = Counter(labs[nn[labs == worst]].ravel().tolist())
            confused.pop(worst, None)
            into = confused.most_common(1)[0][0] if confused else next(l for l in groups if l != worst)
            groups[into] += groups.pop(worst)

        if len(groups) >= 2:
            idx = np.array([i for g in groups.values() for i in g])
            labs = np.array([l for l, g in groups.items() for _ in g])
            S = E @ E[idx].T
            final = {}
            for i in range(len(body)):
                s = S[i].copy()
                s[idx == i] = -np.inf
                nn = np.argsort(-s)[:K]
                votes = Counter(labs[nn].tolist())
                l, v = votes.most_common(1)[0]
                if v / K >= VOTE_MIN:
                    final[i] = l
            sizes = Counter(final.values())
            keep = [l for l, n in sizes.most_common() if n >= max(MIN_COUNT, MIN_SHARE * len(body))]
            if len(keep) >= 2:
                for n, l in enumerate(keep, 1):
                    members = [i for i, x in final.items() if x == l]
                    inside = Counter(g for i in members for g in nouns[i])
                    others = Counter(g for i, x in final.items() if x != l for g in nouns[i])
                    n_out = max(1, sum(1 for x in final.values() if x != l))
                    desc = sorted(inside, key=lambda g: -(inside[g] / len(members) - others[g] / n_out))
                    desc = [g for g in desc if inside[g] / len(members) - others[g] / n_out > 0.1][:3]
                    outfits.append({"id": n, "token": f"{name}_outfit{n}", "count": len(members), "tags": desc})
                    for i in members:
                        assign[body[i][1].stem] = n

    if outfits:
        by_frame, by_shot = {}, {}
        for it, p, _ in rows:
            n = assign.get(p.stem)
            if n:
                by_frame.setdefault((it["vid"], it["t"]), Counter())[n] += 1
                by_shot.setdefault((it["vid"], shot_of.get((it["vid"], it["t"]))), Counter())[n] += 1
        for it, p, _ in rows:
            if p.stem not in assign:
                c = by_frame.get((it["vid"], it["t"])) or by_shot.get((it["vid"], shot_of.get((it["vid"], it["t"]))))
                if c and len(c) == 1:
                    assign[p.stem] = next(iter(c))

    for it, p, tags in rows:
        n = assign.get(p.stem)
        if n:
            i = tags.index(name) + 1 if name in tags else 0
            tags = tags[:i] + [f"{name}_outfit{n}"] + tags[i:]
        p.with_suffix(".txt").write_text(", ".join(tags), encoding="utf-8")
    build["outfits"] = outfits
    project.save(f"characters/{char_dir.name}/build.json", build)

    if outfits:
        for o in outfits:
            total = sum(1 for v in assign.values() if v == o["id"])
            say("  • " + t("{token}: {n} images ({tags})", token=o["token"], n=total,
                           tags=", ".join(o["tags"]) or t("told apart by look only")))
        if len(rows) - len(assign):
            say("  • " + t("{n} images without a clear outfit get no outfit tag", n=len(rows) - len(assign)))
    else:
        say("  • " + t("One outfit only, or too little clothing in view: no outfit tags added"))
    return outfits
