import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import negatives
from .cache import file_hash, link_or_copy, unlinked
from .cancel import check as check_cancel
from .common import inside, load_json, plain_name, save_json
from .outfits import token_matcher
from .tags import BOX, apply_edit, load_box, load_edits, save_box, split_tags, strip_box
from .txn import Transaction

PARTS = ("sorted", "_deleted", "_dropped", "_caption_history", "build.json", "emb.npz",
         "ccip.npz", "report.txt", "negatives.npz", "positives.npz", "confirmed", "review.json", "tag_edits.json",
         BOX)
KEPT_ON_REBUILD = ("negatives.npz", "positives.npz", "confirmed", "tag_edits.json", BOX)
STORE = ".images"


def copy_part(src, dst, store=None):
    if src.is_symlink():
        raise ValueError(f"Cannot snapshot a symbolic link: {src}")
    check_cancel()
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            copy_part(child, dst / child.name, store)
    elif src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if store is None or src.suffix.lower() != ".png":
            shutil.copy2(src, dst)
            return
        image = store / (file_hash(src) + ".png")
        if not image.exists():
            store.mkdir(parents=True, exist_ok=True)
            tmp = image.with_name(image.name + ".tmp")
            shutil.copy2(src, tmp)
            tmp.replace(image)
        link_or_copy(image, dst)


def prune_store(root):
    for image in unlinked(root / STORE):
        image.unlink()


def version_path(project, name, version):
    if not plain_name(version) or version.startswith("."):
        raise SystemExit("invalid version name")
    path = project.char_dir(name) / "versions" / version
    if path.is_symlink() or not (path / "manifest.json").is_file():
        raise SystemExit(f"version not found: {version}")
    return path


def list_versions(project, name):
    root = project.char_dir(name) / "versions"
    return [{**load_json(path), "id": path.parent.name}
            for path in sorted(root.glob("*/manifest.json"), reverse=True) if not path.parent.name.startswith(".")]


def save_version(project, name, reason="manual"):
    char = project.char_dir(name)
    if not (char / "sorted").is_dir():
        raise SystemExit(f"no built images for '{name}'")
    now = datetime.now(timezone.utc)
    vid = now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    root = char / "versions"
    stage, final = root / (".pending-" + vid), root / vid
    try:
        stage.mkdir(parents=True)
        for part in PARTS:
            copy_part(char / part, stage / "data" / part, root / STORE)
        copy_part(project.dir / "refs" / char.name, stage / "refs", root / STORE)
        save_json(stage / "manifest.json", {"created": now.isoformat(), "reason": reason,
                                            "images": len(list((char / "sorted").rglob("*.png")))})
        check_cancel()
        stage.rename(final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        prune_store(root)
        raise
    return vid


def delete_version(project, name, version):
    path = version_path(project, name, version)
    shutil.rmtree(path)
    prune_store(path.parent)


def _images(folder):
    return {p.stem: p for p in (folder / "sorted").rglob("*.png")}


def _text(png):
    txt = png.with_suffix(".txt")
    return txt.read_text(encoding="utf-8") if txt.exists() else None


def compare_version(project, name, version):
    old = version_path(project, name, version) / "data"
    current = project.char_dir(name)
    before, after = _images(old), _images(current)
    common = before.keys() & after.keys()
    a = load_json(old / "build.json", {}).get("settings", {})
    b = load_json(current / "build.json", {}).get("settings", {})
    return {"saved": len(before), "current": len(after),
            "added": len(after.keys() - before.keys()), "removed": len(before.keys() - after.keys()),
            "captions": sum(_text(before[k]) != _text(after[k]) for k in common),
            "moved": sum(before[k].relative_to(old) != after[k].relative_to(current) for k in common),
            "settings": {key: [a.get(key), b.get(key)] for key in a.keys() | b.keys() if a.get(key) != b.get(key)}}


def replay(tags, edits):
    for edit in edits:
        tags = apply_edit(tags, edit["remove"], edit["replace"], edit["add"])
    return tags


def with_tokens(tags, tokens, trigger):
    i = tags.index(trigger) + 1 if trigger in tags else 0
    return tags[:i] + [t for t in tokens if t not in tags] + tags[i:]


def carry_review(project, name, version):
    old = version_path(project, name, version) / "data"
    current = project.char_dir(name)
    meta = load_json(old / "build.json")
    if meta is None:
        return
    new_meta = load_json(current / "build.json", {})
    trigger = new_meta.get("name", name)
    before, after = _images(old), _images(current)
    previous = {Path(it["file"]).stem: it for it in meta.get("items", [])}
    state = load_json(old / "review.json", {})
    deleted = (set(state.get("removed", [])) | previous.keys()) - before.keys()
    captions, groups = state.get("captions", {}), state.get("groups", {})
    edits = load_edits(current)
    box = load_box(current)
    old_token, new_token = token_matcher(meta, name), token_matcher(new_meta, name)
    for stem in before.keys() & previous.keys():
        prior = previous[stem]
        text = _text(before[stem])
        mine = [t for t in split_tags(text) if not old_token(t)] if text is not None else None
        expected = ([t for t in strip_box(replay(split_tags(prior["caption"]), edits), box) if not old_token(t)]
                    if prior.get("caption") is not None else None)
        if mine is not None and mine != expected:
            captions[stem] = ", ".join(mine)
        else:
            captions.pop(stem, None)
        rel = before[stem].relative_to(old)
        if rel != Path(prior["file"]):
            groups[stem] = str(rel)
        else:
            groups.pop(stem, None)
    for entry in box.values():
        for stem in after:
            entry.pop(stem, None)
    changed = moved = removed = replayed = 0
    for stem, png in after.items():
        check_cancel()
        if stem in deleted:
            negatives.trash(current, png)
            removed += 1
            continue
        fresh = _text(png)
        tags = split_tags(fresh or "")
        rebuilt = strip_box(replay(tags, edits), box, stem)
        if stem in captions:
            text = ", ".join(strip_box(with_tokens(split_tags(captions[stem]), [t for t in tags if new_token(t)],
                                                trigger), box))
            changed += 1
        else:
            text = ", ".join(rebuilt) if fresh is not None else None
        if text is not None and text != fresh:
            png.with_suffix(".txt").write_text(text, encoding="utf-8")
            replayed += stem not in captions
        if stem in groups:
            dest = current / groups[stem]
            if not inside(dest, current / "sorted"):
                raise SystemExit("invalid review group path")
            if png != dest:
                negatives.move_pair(png, dest.parent)
                moved += 1
    save_box(current, box)
    save_json(current / "review.json", {"removed": sorted(deleted), "captions": captions, "groups": groups})
    print(f"[versions] review carried forward: {removed} removals, {changed} captions, {moved} groups"
          + (f", bulk tag edits applied to {replayed} new captions" if replayed else ""))
    print(f"[versions] current reviewed result: {len(_images(current))} images")


@contextmanager
def _with_backup(project, name, reason, replace, remove_if_new=()):
    version = save_version(project, name, reason) if (project.char_dir(name) / "sorted").exists() else None
    transaction = Transaction(project.dir, replace=replace, remove_if_new=remove_if_new)
    try:
        with transaction:
            yield version
            check_cancel()
    except BaseException:
        if version and transaction.rolled_back:
            delete_version(project, name, version)
        raise


@contextmanager
def rebuilding(project, name, ref_dir=None):
    char = project.char_dir(name)
    replace = [char / p for p in PARTS if p not in KEPT_ON_REBUILD] + [char / "_thumbs"]
    with _with_backup(project, name, "before rebuild", replace + ([Path(ref_dir)] if ref_dir else []),
                      [char]) as version:
        yield
        if version:
            carry_review(project, name, version)
    if version:
        print(f"[versions] previous result saved: {version}")


def restore_version(project, name, version):
    saved = version_path(project, name, version)
    if not (saved / "data" / "sorted").is_dir():
        raise SystemExit("version has no saved image folder")
    char = project.char_dir(name)
    refs = project.dir / "refs" / char.name
    with _with_backup(project, name, "before restore", [char / p for p in PARTS] + [char / "_thumbs", refs]) as previous:
        for part in PARTS:
            copy_part(saved / "data" / part, char / part)
        copy_part(saved / "refs", refs)
    print(f"[versions] restored {version}; previous current result saved as {previous}")
