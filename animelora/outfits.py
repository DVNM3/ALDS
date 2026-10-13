"""Automatic outfit separation for one built character.

WD14 tags alone don't work on screencaps: in a test only 36 of 173 vest images were tagged "vest", and tags
like "armor" came from *another* character standing nearby. So tags only provide seeds and the pictures
decide:
  1. seeds   - garment nouns ("open vest"/"black vest" -> vest) that separate images; garments worn in most
               images (e.g. a signature scarf) carry no outfit information and are ignored
  2. check   - seed groups that look alike (k-NN purity on WD14 embeddings) are merged, which removes
               noise groups such as "armor"
  3. spread  - every body crop takes the outfit its nearest seed images agree on (or none when unclear)
  4. heads   - head crops show little clothing; they inherit from a body crop of the same frame or shot
Each outfit gets a token right after the trigger word (e.g. `natsu_ft_outfit1`).
"""
import re
from collections import Counter
from pathlib import Path

import numpy as np

from .tags import split_tags

# garments that show on the upper body, i.e. in both full and half crops (pants/shoes only show in full shots,
# so they would separate framings rather than outfits)
GARMENTS = {
    "shirt", "jacket", "coat", "vest", "dress", "uniform", "kimono", "yukata", "armor", "armour", "swimsuit",
    "bikini", "hoodie", "sweater", "cape", "cloak", "robe", "cardigan", "blazer", "serafuku", "tuxedo", "suit",
    "top", "camisole", "leotard", "bodysuit", "gown", "blouse", "tunic", "parka", "raincoat", "apron",
    "overalls", "sleeveless", "scarf", "haori", "poncho", "shawl", "corset", "bra", "necktie",
}
CONSTANT_SHARE = 0.6   # a garment in this share of body crops is part of every outfit
SEED_MIN = 5           # images a garment / seed group needs
PURITY_MIN = 0.75      # k-NN purity a seed group needs to count as visually its own outfit
VOTE_MIN = 0.7         # neighbour agreement needed to give an image an outfit
K = 7
MIN_COUNT, MIN_SHARE = 8, 0.08  # final outfit size


def garment_nouns(tags):
    out = set()
    for t in tags:
        if t.endswith(" sleeves"):  # long / short sleeves
            out.add(t)
            continue
        hits = [w for w in re.split(r"[\s\-_()]+", t) if w in GARMENTS]
        if hits:
            out.add(hits[-1])
    return out


def _token_re(trigger):
    return re.compile(rf"^{re.escape(trigger)}_outfit\d+$")


def sync_tokens(project, char, remove=(), replace=None):
    """Keep build.json's outfit list in step when outfit tokens are renamed/removed in the tag editor."""
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
    """After a caption undo, point outfit entries back at the token the captions actually use again."""
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
    """share of each seed's k nearest other seeds that carry the same label, averaged per label"""
    S = E @ E.T
    np.fill_diagonal(S, -np.inf)
    nn = np.argsort(-S, axis=1)[:, :k]
    same = (labels[nn] == labels[:, None]).mean(1)
    return {l: float(same[labels == l].mean()) for l in set(labels.tolist())}, nn


def run_outfits(project, name, apply=True):
    from scipy.spatial.distance import pdist, squareform
    from sklearn.cluster import AgglomerativeClustering

    char_dir = project.char_dir(name)
    build = project.load(f"characters/{char_dir.name}/build.json")
    if not build:
        raise SystemExit(f"no build for '{name}' - run build first")
    name = build.get("name", name)  # the trigger word as typed (the folder name may be sanitised)
    pattern = _token_re(name)
    renamed = {o["token"] for o in build.get("outfits", [])}  # tokens possibly renamed in the tag editor
    token_re = re.compile("|".join([pattern.pattern] + [rf"^{re.escape(t)}$" for t in renamed]))
    files = {p.stem: p for p in (char_dir / "sorted").rglob("*.png")}
    frames = project.load("scan/frames.json", [])
    shot_of = {(f["vid"], f["t"]): f["shot"] for f in frames}
    emb = {}
    if (char_dir / "emb.npz").exists():
        z = np.load(char_dir / "emb.npz")
        emb = dict(zip(z["stems"].tolist(), z["emb"].astype(np.float32)))

    rows = []  # (meta item, png path, tags without outfit tokens)
    for it in build["items"]:
        p = files.get(Path(it["file"]).stem)
        if p is None or not p.with_suffix(".txt").exists():
            continue  # deleted in review
        tags = [t for t in split_tags(p.with_suffix(".txt").read_text(encoding="utf-8")) if not token_re.match(t)]
        rows.append((it, p, tags))

    body = [r for r in rows if r[0]["type"] != "head" and r[1].stem in emb]
    outfits, assign = [], {}
    if len(body) >= 2 * MIN_COUNT:
        E = np.stack([emb[r[1].stem] for r in body])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        nouns = [garment_nouns(r[2]) for r in body]
        freq = Counter(n for s in nouns for n in s)
        cand = sorted(n for n, c in freq.items() if c >= SEED_MIN and c < CONSTANT_SHARE * len(body))

        # 1. seed groups: images clustered by their candidate garments
        seed_idx = [i for i, s in enumerate(nouns) if s & set(cand)]
        groups = {}
        if len(cand) >= 2 and len(seed_idx) >= 2 * SEED_MIN:
            X = np.array([[n in nouns[i] for n in cand] for i in seed_idx], dtype=bool)
            lab = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                          distance_threshold=0.6).fit(squareform(pdist(X, "jaccard"))).labels_
            for i, l in zip(seed_idx, lab):
                groups.setdefault(int(l), []).append(i)
            groups = {l: g for l, g in groups.items() if len(g) >= SEED_MIN}

        # 2. merge seed groups that don't look different
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

        # 3. spread to every body crop by neighbour vote among the seeds
        if len(groups) >= 2:
            idx = np.array([i for g in groups.values() for i in g])
            labs = np.array([l for l, g in groups.items() for _ in g])
            S = E @ E[idx].T
            final = {}
            for i in range(len(body)):
                s = S[i].copy()
                s[idx == i] = -np.inf  # a seed doesn't vote for itself
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

    # 4. head crops (and undecided body crops) inherit from the same frame, else the same shot
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
                if c and len(c) == 1:  # only when the frame/shot is unambiguous
                    assign[p.stem] = next(iter(c))

    if apply:
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
            print(f"[outfits] {o['token']}: {total} images - {', '.join(o['tags']) or '(visual only)'}")
        if len(rows) - len(assign):
            print(f"[outfits] {len(rows) - len(assign)} images without a clear outfit (no token)")
    else:
        print("[outfits] one outfit only (or not enough clothing visible) - no outfit tokens added")
    return outfits
