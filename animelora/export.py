import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np

from .cancel import check as check_cancel
from .common import safe_name


def group_of(sorted_dir: Path, png: Path) -> str:
    parts = png.parent.relative_to(sorted_dir).parts
    parts = parts[1:] if parts and parts[0] == "_review" else parts
    return "/".join(parts)


def water_fill(sizes: dict, total: int, power: float = 0.5) -> dict:
    quota = {g: 0 for g in sizes}
    remaining = min(total, sum(sizes.values()))
    while remaining > 0:
        open_groups = [g for g in sizes if quota[g] < sizes[g]]
        if not open_groups:
            break
        weight = {g: sizes[g] ** power for g in open_groups}
        W = sum(weight.values())
        ideal = {g: remaining * weight[g] / W for g in open_groups}
        alloc = {g: min(sizes[g] - quota[g], int(ideal[g])) for g in open_groups}
        left = remaining - sum(alloc.values())
        for g in sorted(open_groups, key=lambda g: ideal[g] - int(ideal[g]), reverse=True):
            if left and alloc[g] < sizes[g] - quota[g]:
                alloc[g] += 1
                left -= 1
        if left == remaining:
            break
        for g, n in alloc.items():
            quota[g] += n
        remaining = left
    return quota


def select_diverse(files, k, sharp, emb):
    files = sorted(files, key=lambda p: -sharp.get(p.stem, 0))
    if k >= len(files):
        return files
    if any(p.stem not in emb for p in files):
        return files[:k]
    E = np.stack([emb[p.stem] for p in files])
    S = (E @ E.T + 1) / 2
    quality = 0.6 + 0.4 * np.linspace(1, 0, len(files))
    covered = np.zeros(len(files))
    chosen = []
    for _ in range(k):
        gain = (np.maximum(S, covered[None, :]) - covered[None, :]).sum(1) * quality
        gain[chosen] = -1
        j = int(np.argmax(gain))
        chosen.append(j)
        covered = np.maximum(covered, S[j])
    return [files[i] for i in chosen]


def plan_export(project, name, total=None, max_per_group=None):
    char_dir = project.char_dir(name)
    sorted_dir = char_dir / "sorted"
    if not sorted_dir.exists():
        raise SystemExit(f"{sorted_dir} not found - run build first")
    build = project.load(f"characters/{char_dir.name}/build.json", {"items": []})
    sharp = {Path(it["file"]).stem: it["sharp"] for it in build["items"]}
    emb = {}
    if (char_dir / "emb.npz").exists():
        z = np.load(char_dir / "emb.npz")
        E = z["emb"].astype(np.float32)
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        emb = dict(zip(z["stems"].tolist(), E))

    groups = defaultdict(list)
    for png in sorted_dir.rglob("*.png"):
        groups[group_of(sorted_dir, png)].append(png)
    caps = {g: len(v) for g, v in groups.items()}
    if max_per_group:
        caps = {g: min(n, max_per_group) for g, n in caps.items()}
    if total:
        caps = water_fill(caps, total)
    picked = {g: select_diverse(files, caps[g], sharp, emb) for g, files in groups.items()}
    return groups, picked


def export_target(project, name, out=None, aitk=None) -> Path:
    char_dir = project.char_dir(name)
    if aitk:
        root = Path(aitk["root"])
        if not (root / "datasets").is_dir():
            raise SystemExit(f"AI Toolkit folder not found: {root} (expected a 'datasets' folder inside)")
        return root / "datasets" / safe_name(aitk.get("dataset_name") or char_dir.name)
    return Path(out) if out else char_dir / "train"


def run_export(project, name, out, max_per_group=None, total=None, aitk=None):
    from .aitk import MARKER, check_dataset_dir
    char_dir = project.char_dir(name)
    groups, picked = plan_export(project, name, total, max_per_group)
    out = export_target(project, name, out, aitk)
    if out != char_dir / "train":
        check_dataset_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("exported by animelora\n", encoding="utf-8")
    for old in list(out.glob("*.png")) + list(out.glob("*.txt")):
        old.unlink()
    missing = n = 0
    captions = []
    for files in picked.values():
        for png in files:
            check_cancel()
            shutil.copy2(png, out / png.name)
            n += 1
            txt = png.with_suffix(".txt")
            if txt.exists():
                shutil.copy2(txt, out / txt.name)
                captions.append([t.strip() for t in txt.read_text(encoding="utf-8").split(",")])
            else:
                missing += 1
    print(f"[export] {n} of {sum(len(v) for v in groups.values())} images -> {out}")
    if total or max_per_group:
        for g in sorted(groups, key=lambda g: -len(groups[g])):
            print(f"   {g:<28} {len(picked[g]):>4} / {len(groups[g])}")
    if missing:
        print(f"[export] warning: {missing} images have no caption .txt")
    if aitk:
        write_aitk_config(project, name, out, n, captions, aitk)
    else:
        print(f"\nAI Toolkit: point the dataset folder_path at\n  {out.as_posix()}\n"
              f"with caption extension 'txt'. The captions already contain the trigger '{name}'.")


def write_aitk_config(project, name, out, n_images, captions, aitk):
    from .aitk import DEFAULT_RES, GA, count_tag_of, dump, make_config, next_job_name, schedule, schedule_notes
    char_dir = project.char_dir(name)
    build = project.load(f"characters/{char_dir.name}/build.json", {})
    root = Path(aitk["root"])
    sched = schedule(n_images, sorted(aitk.get("resolutions") or DEFAULT_RES), int(aitk.get("epochs") or 40))
    base = "_".join(w.capitalize() for w in out.name.split("_"))
    job = aitk.get("job_name") or next_job_name(base, root)
    cfg = make_config(job, build.get("name", name), out, root / "output", sched, count_tag_of(captions),
                      build.get("series"), [o["token"] for o in build.get("outfits", [])])
    text = dump(cfg)
    paths = [char_dir / f"{job}.yaml"]
    if (root / "config").is_dir():
        paths.append(root / "config" / f"{job}.yaml")
    for p in paths:
        p.write_text(text, encoding="utf-8")
    print(f"\n[aitk] job '{job}': {n_images} images x {len(sched['resolutions'])} resolutions "
          f"{sched['resolutions']}, {sched['epochs']} epochs")
    print(f"       steps {sched['steps']} | save/sample every {sched['save_every']} | keep {sched['keep']} "
          f"| batch 1 x GA {GA} | warmup 100")
    for note in schedule_notes(sched):
        print("       " + note)
    print("[aitk] config written to:\n" + "\n".join(f"       {p}" for p in paths))
    print("       In AI Toolkit: new job -> Advanced (YAML) -> paste the file's content.")
