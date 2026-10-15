import json
import time
from collections import Counter
from pathlib import Path

from .common import load_json, save_json

HISTORY_KEEP = 20
EDITS = "tag_edits.json"
BOX = "trigger_tags.json"
BOX_KEY = ":box"


def split_tags(text: str):
    return [t.strip() for t in text.split(",") if t.strip()]


def caption_files(char_dir: Path):
    return sorted((char_dir / "sorted").rglob("*.txt"))


def tag_counts(char_dir: Path):
    files = caption_files(char_dir)
    cnt = Counter(t for f in files for t in dict.fromkeys(split_tags(f.read_text(encoding="utf-8"))))
    return cnt, len(files)


def _snapshot(char_dir: Path, files):
    hist = char_dir / "_caption_history"
    hist.mkdir(exist_ok=True)
    data = {f.name: f.read_text(encoding="utf-8") for f in files}
    data[BOX_KEY] = load_box(char_dir)
    second = time.strftime("%Y%m%d-%H%M%S")
    same = [int(f.stem.rsplit("-", 1)[1]) for f in hist.glob(f"{second}-*.json") if f.stem.rsplit("-", 1)[1].isdigit()]
    (hist / f"{second}-{max(same, default=-1) + 1:06d}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for old in sorted(hist.glob("*.json"))[:-HISTORY_KEEP]:
        old.unlink()


def apply_edit(tags, remove, replace, add):
    new = []
    for t in tags:
        if t in remove:
            continue
        new += split_tags(replace[t]) if t in replace else [t]
    return list(dict.fromkeys([*new, *add]))


def load_edits(char_dir: Path):
    return load_json(Path(char_dir) / EDITS, [])


def _save_edits(char_dir: Path, edits):
    if edits:
        save_json(Path(char_dir) / EDITS, edits)
    else:
        (Path(char_dir) / EDITS).unlink(missing_ok=True)


def edit_tags(char_dir: Path, remove=(), replace=None, add=(), is_token=lambda tag: False) -> int:
    files = caption_files(char_dir)
    remove = {t.strip() for t in remove if t.strip()}
    replace = {k.strip(): v for k, v in (replace or {}).items() if k.strip()}
    add = [t.strip() for t in add if t.strip()]
    if not files or not (remove or replace or add):
        return 0
    _snapshot(char_dir, files)
    _save_edits(char_dir, load_edits(char_dir) + [{"remove": sorted(t for t in remove if not is_token(t)),
                                                   "replace": {k: v for k, v in replace.items() if not is_token(k)},
                                                   "add": add}])
    changed = 0
    for f in files:
        old = split_tags(f.read_text(encoding="utf-8"))
        new = apply_edit(old, remove, replace, add)
        if new != old:
            f.write_text(", ".join(new), encoding="utf-8")
            changed += 1
    return changed


def undo_last(char_dir: Path) -> int:
    hist = char_dir / "_caption_history"
    snaps = sorted(hist.glob("*.json")) if hist.exists() else []
    if not snaps:
        raise SystemExit("nothing to undo")
    data = json.loads(snaps[-1].read_text(encoding="utf-8"))
    box = data.pop(BOX_KEY, None)
    where = {f.name: f for f in caption_files(char_dir)}
    restored = 0
    for name, text in data.items():
        if name in where:
            where[name].write_text(text, encoding="utf-8")
            restored += 1
    snaps[-1].unlink()
    _save_edits(char_dir, load_edits(char_dir)[:-1])
    if box is not None:
        save_box(char_dir, box)
    return restored


def history_size(char_dir: Path) -> int:
    hist = char_dir / "_caption_history"
    return len(list(hist.glob("*.json"))) if hist.exists() else 0


def load_box(char_dir: Path):
    return load_json(Path(char_dir) / BOX, {})


def save_box(char_dir: Path, box):
    if box:
        save_json(Path(char_dir) / BOX, box)
    else:
        (Path(char_dir) / BOX).unlink(missing_ok=True)


def strip_box(tags, box, stem=None):
    kept = []
    for i, t in enumerate(tags):
        if t in box:
            if stem is not None:
                box[t][stem] = tags[i - 1] if i else ""
            continue
        kept.append(t)
    return kept


def anchors(tags, wanted, box, stem):
    found = {}
    for t, prev in wanted.items():
        seen = set()
        while prev and prev not in tags and prev not in wanted and stem in box.get(prev, {}) and prev not in seen:
            seen.add(prev)
            prev = box[prev][stem]
        found[t] = prev
    return found


def put_back(tags, wanted):
    tags, pending = list(tags), dict(wanted)
    while pending:
        ready = [t for t, prev in pending.items() if not prev or prev in tags]
        if not ready:
            break
        for t in ready:
            prev = pending.pop(t)
            if t not in tags:
                tags.insert(tags.index(prev) + 1 if prev else 0, t)
    return tags + [t for t in pending if t not in tags]


def absorb(char_dir: Path, tags, is_token=lambda tag: False) -> int:
    files = caption_files(char_dir)
    tags = [t for t in dict.fromkeys(t.strip() for t in tags) if t and not is_token(t)]
    if not files or not tags:
        return 0
    _snapshot(char_dir, files)
    _save_edits(char_dir, load_edits(char_dir) + [{"remove": [], "replace": {}, "add": [], "trigger": tags}])
    box = load_box(char_dir)
    moving = {t: box.setdefault(t, {}) for t in tags}
    changed = 0
    for f in files:
        old = split_tags(f.read_text(encoding="utf-8"))
        new = strip_box(old, moving, f.stem)
        if new != old:
            f.write_text(", ".join(new), encoding="utf-8")
            changed += 1
    save_box(char_dir, box)
    return changed


def restore(char_dir: Path, tags) -> int:
    files = caption_files(char_dir)
    box = load_box(char_dir)
    tags = [t for t in dict.fromkeys(tags) if t in box]
    if not tags:
        return 0
    _snapshot(char_dir, files)
    _save_edits(char_dir, load_edits(char_dir) + [{"remove": [], "replace": {}, "add": [], "restore": tags}])
    changed = 0
    for f in files:
        wanted = {t: box[t][f.stem] for t in tags if f.stem in box[t]}
        if not wanted:
            continue
        old = split_tags(f.read_text(encoding="utf-8"))
        new = put_back(old, anchors(old, wanted, box, f.stem))
        if new != old:
            f.write_text(", ".join(new), encoding="utf-8")
            changed += 1
    for t in tags:
        del box[t]
    save_box(char_dir, box)
    return changed
