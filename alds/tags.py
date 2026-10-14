import json
import time
from collections import Counter
from pathlib import Path

from .common import load_json, save_json

HISTORY_KEEP = 20
EDITS = "tag_edits.json"


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
    (hist / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**6:06d}.json").write_text(
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
    where = {f.name: f for f in caption_files(char_dir)}
    restored = 0
    for name, text in data.items():
        if name in where:
            where[name].write_text(text, encoding="utf-8")
            restored += 1
    snaps[-1].unlink()
    _save_edits(char_dir, load_edits(char_dir)[:-1])
    return restored


def history_size(char_dir: Path) -> int:
    hist = char_dir / "_caption_history"
    return len(list(hist.glob("*.json"))) if hist.exists() else 0
