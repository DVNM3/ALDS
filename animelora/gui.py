import contextlib
import io
import os
import re
import shutil
from collections import Counter
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr
from PIL import Image

from . import cancel, txn
from .cancel import Cancelled
from .common import PROJECTS_DIR, Project, mmss, parse_ranges, safe_name
from .i18n import AR, LANGS, bound, lang, t, use


def ltr(text) -> str:
    return f"\u2066{text}\u2069"


FRAMING = {"close_up": "Close-up", "upper_body": "Upper body", "cowboy_shot": "Cowboy shot", "full_body": "Full body"}
VIEW = {"front": "Front", "three_quarter": "Three-quarter", "side": "Side", "back": "Back", "above": "From above",
        "below": "From below"}
CROP = {"full": "Whole character", "half": "Upper body", "head": "Head"}


def shot_name(key):
    return t(FRAMING[key]) if key in FRAMING else key


def angle_name(key):
    return t(VIEW[key]) if key in VIEW else key


def build_options():
    return [(t("Separate outfits automatically (a tag per outfit after the trigger word)"), "outfits"),
            (t("Put anime screencap at the start of every caption"), "screencap"),
            (t("Keep hair and eye tags in the captions"), "keep_core"),
            (t("Keep images with text on screen"), "keep_text"),
            (t("Keep images crowded with other characters"), "keep_crowded"),
            (t("Keep chibi and blurry drawings"), "keep_offmodel"),
            (t("Save the left-out images in a {folder} folder", folder="_dropped"), "save_dropped"),
            (t("Analyse from scratch, ignore the saved analysis (much slower, rarely needed)"), "fresh")]


CSS = """
html[dir="rtl"] .gradio-container, html[dir="rtl"] .gradio-container [dir="ltr"] { direction: rtl; }
html[dir="rtl"] .gradio-container .body-cell, html[dir="rtl"] .gradio-container .body-cell .text { text-align: right; }
.gradio-container .body-cell .text, .gradio-container .caption-label { unicode-bidi: plaintext; }
input[type=range] { direction: ltr; }
.ltr textarea, .ltr input { direction: ltr !important; text-align: left !important; }
#log textarea { direction: ltr; text-align: left; font-family: Consolas, monospace; font-size: 12px; }
#preview img { object-fit: contain; }
html[lang="ar"] .toast-title, html[lang="ar"] .wrap.default > span.error { font-size: 0; }
html[lang="ar"] .toast-title::before, html[lang="ar"] .wrap.default > span.error::before { font-size: 16px; }
html[lang="ar"] .wrap.default > span.error::before { content: "%s"; }
""" % AR["Error"] + "".join(f'html[lang="ar"] .toast-title.{kind}::before {{ content: "{AR[word]}"; }}\n'
                            for kind, word in (("error", "Error"), ("warning", "Warning"), ("info", "Info")))

HEAD ="""<script>
const setDir = () => {
  const en = /\\/en\\/?$/.test(location.pathname);
  document.documentElement.dir = en ? 'ltr' : 'rtl';
  document.documentElement.lang = en ? 'en' : 'ar';
};
setDir();
window.addEventListener('popstate', setDir);
for (const m of ['pushState', 'replaceState']) {
  const orig = history[m];
  history[m] = function () { const r = orig.apply(this, arguments); setDir(); return r; };
}
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'textarea' || tag === 'input') return;
  const click = (id) => { const b = document.getElementById(id); if (b && b.offsetParent !== null) { b.click(); e.preventDefault(); } };
  const rtl = document.documentElement.dir === 'rtl';
  if (e.key === 'Delete') click('btn-del');
  else if (e.code === 'KeyN' && !e.ctrlKey && !e.metaKey && !e.altKey) click('btn-reject');
  else if (e.key === 'ArrowLeft') click(rtl ? 'btn-next' : 'btn-prev');
  else if (e.key === 'ArrowRight') click(rtl ? 'btn-prev' : 'btn-next');
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { click('btn-undo'); click('btn-tag-undo'); }
});
</script>"""


def projects():
    return sorted(p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()) if PROJECTS_DIR.exists() else []


def need_project(pname) -> Project:
    if not pname or not safe_name(pname):
        raise gr.Error(t("Pick a project or type a new project name at the top"))
    return Project(safe_name(pname))


def characters(pname):
    if not pname:
        return []
    d = Project(safe_name(pname)).chars_dir
    return sorted(p.name for p in d.iterdir() if (p / "sorted").exists()) if d.exists() else []


ERROR_HINTS = [("not found:", "The file or folder doesn't exist"),
               ("already exists", "There are results with this name already. Tick “Replace earlier results” to "
                                  "build it again, or pick another name"),
               ("no matches", "The character wasn't found. Raise “Match threshold” a little or pick other clusters"),
               ("no characters detected", "No characters were found in the episodes"),
               ("nothing scanned yet", "Scan at least one episode first (tab 1)"),
               ("no clusters yet", "Scan at least one episode first (tab 1)"),
               ("does not exist", "That cluster number doesn't exist. Numbers change after every scan, refresh "
                                  "the page"),
               ("no images in", "There are no images in the uploaded references"),
               ("not enough clear", "Not enough clear views to cluster"),
               ("were deleted to save space", "This project's frames were deleted to save space. To build a new "
                                              "character, scan the episodes in a new project"),
               ("didn't split", "The cluster didn't split this strongly, lower “Split strength”"),
               ("too small to split", "The cluster is too small to split")]


def gui_error(e: SystemExit):
    msg = str(e) or "failed"
    hint = next((h for key, h in ERROR_HINTS if key in msg), None)
    return gr.Error(f"{t(hint)}\n\n{ltr(msg)}" if hint else ltr(msg))


def captured(fn, *args, txn=None):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if txn is None:
                fn(*args)
            else:
                with txn:
                    fn(*args)
    except Cancelled:
        raise gr.Error(t("Stopped: everything it generated was removed, the project is back as it was."),
                       title=t("⏹ Stopped"))
    except SystemExit as e:
        raise gui_error(e)
    return buf.getvalue()


def stop_label():
    return t("⏹ Stop and remove what it made")


def start_ui():
    cancel.reset()
    return gr.update(visible=True, value=stop_label(), interactive=True)


def end_ui():
    return gr.update(visible=False)


def press_stop():
    cancel.request()
    return gr.update(value=t("⏳ Stopping and undoing..."), interactive=False)


def videos_table(pname):
    if not pname:
        return []
    proj = Project(safe_name(pname)).load("project.json", {"videos": []})
    rows = []
    for v in proj["videos"]:
        segs = " | ".join(f"{lab} {mmss(s)}–{mmss(e)}" for s, e, lab in v.get("auto_skip", []))
        segs = ltr(segs) if segs else "—"
        rows.append([v["id"], v["name"], round(v.get("duration", 0) / 60, 1), v.get("kept_frames", 0), segs])
    return rows


def clusters_view(pname):
    if not pname:
        return [], []
    p = Project(safe_name(pname))
    data = p.load("scan/clusters.json")
    if not data:
        return [], []
    items = []
    for c in data["clusters"]:
        card = p.clusters_dir / f"card_{c['id']:02d}.jpg"
        if not card.exists():
            card = p.clusters_dir / f"cluster_{c['id']:02d}.jpg"
        items.append((str(card), t("{id}  ·  {n} views", id=f"#{c['id']}", n=len(c["members"]))))
    return items, [f"#{c['id']}" for c in data["clusters"]]


def load_project(pname):
    items, choices = clusters_view(pname)
    chars = characters(pname)
    first = chars[0] if chars else None
    return (videos_table(pname), items, gr.update(choices=choices, value=[]),
            gr.update(choices=chars, value=first), gr.update(choices=chars, value=first),
            gr.update(choices=chars, value=first), usage_md(pname))


def do_scan(pname, videos_text, skip_text, auto, auto_min, min_gap, keep_diff,
            progress=gr.Progress(track_tqdm=True)):
    from .scan import run_scan
    p = need_project(pname)
    paths = [l.strip().strip('"').strip("'") for l in (videos_text or "").splitlines() if l.strip()]
    if not paths:
        raise gr.Error(t("Enter at least one episode path or a folder of episodes"))
    try:
        text = re.sub(r"\s*-\s*", "-", (skip_text or "").strip())
        skip = parse_ranges([s for s in re.split(r"[,\s]+", text) if s])
    except ValueError:
        raise gr.Error(t("The times to skip aren't valid. Example: 0:00-1:55, 21:55-24:30"))
    progress(0, desc=t("Starting the scan..."))
    log = captured(run_scan, p, paths, skip, min_gap, keep_diff, auto, auto_min, txn=txn.scan_txn(p))
    return (log, gr.update(choices=projects()), *load_project(p.name))


def do_autoskip(pname, auto, auto_min, progress=gr.Progress(track_tqdm=True)):
    from .repeats import clear_repeats, detect_repeats
    from .scan import run_clusters
    p = need_project(pname)
    if not p.load("project.json"):
        raise gr.Error(t("Scan at least one episode first"))
    def redo():
        if auto:
            detect_repeats(p, auto_min)
        else:
            clear_repeats(p)
        run_clusters(p)

    progress(0, desc=t("Comparing the episodes..."))
    log = captured(redo, txn=txn.clusters_txn(p))
    return (log, *load_project(p.name))


def do_recluster(pname, cut, min_size, progress=gr.Progress(track_tqdm=True)):
    from .scan import run_clusters
    p = need_project(pname)
    log = captured(run_clusters, p, cut, int(min_size), txn=txn.clusters_txn(p))
    items, choices = clusters_view(p.name)
    return log, items, gr.update(choices=choices, value=[])


def do_split(pname, selected, cut, progress=gr.Progress(track_tqdm=True)):
    from .scan import split_cluster
    p = need_project(pname)
    ids = [int(s.lstrip("#")) for s in selected or []]
    if len(ids) != 1:
        raise gr.Error(t("Select exactly one cluster (the mixed one), then press “Split”"))
    log = captured(split_cluster, p, ids[0], cut, txn=txn.clusters_txn(p))
    items, choices = clusters_view(p.name)
    return log, items, gr.update(choices=choices, value=[])


USAGE = {"frames": "Extracted frames", "scan": "Scan data", "clusters": "Cluster images",
         "cache": "Saved analysis for rebuilds"}


def usage_md(pname):
    from .cleanup import disk_usage, fmt_bytes
    if not pname or not Project(safe_name(pname)).dir.exists():
        return ""
    p = Project(safe_name(pname))
    rows = [(l, b) for l, b in disk_usage(p) if b]
    gone = p.load("project.json", {}).get("frames_deleted")
    part = lambda l: t(USAGE[l]) if l in USAGE else t("Character {name}", name=l.replace("characters/", ""))
    lines = [t("**Project size: {size}**", size=fmt_bytes(sum(b for _, b in rows)))
             + (t(" — frames deleted, no more builds") if gone else ""), "",
             t("| Part | Size |"), "|---|---|"]
    lines += [f"| {part(l)} | {ltr(fmt_bytes(b))} |" for l, b in rows]
    return "\n".join(lines)


def do_clean(pname, all_frames, confirm):
    from .cleanup import clean
    p = need_project(pname)
    if all_frames and not confirm:
        raise gr.Error(t("Tick the confirmation first: deleting all frames is final and stops any rebuild"))
    log = captured(clean, p, "all" if all_frames else "safe")
    return log, usage_md(pname)


def pick_cluster(pname, selected, evt: gr.SelectData):
    p = need_project(pname)
    c = p.load("scan/clusters.json")["clusters"][evt.index]
    tag = f"#{c['id']}"
    sel = list(selected or [])
    sel = [s for s in sel if s != tag] if tag in sel else sel + [tag]
    sel.sort(key=lambda s: int(s.lstrip("#")))
    return sel, str(p.clusters_dir / f"cluster_{c['id']:02d}.jpg")


def do_build(pname, selected, ref_files, name, series, upscale_on, upscale_to, threshold, min_size, sim, relax,
             tagger, opts, overwrite, progress=gr.Progress(track_tqdm=True)):
    from .build import check_overwrite, run_build
    p = need_project(pname)
    name = (name or "").strip()
    if not name:
        raise gr.Error(t("Type the trigger word (the character's name)"))
    ids = sorted(int(s.lstrip("#")) for s in selected or [])
    if not ids and not ref_files:
        raise gr.Error(t("Pick at least one cluster of images, or upload reference images"))
    try:
        check_overwrite(p, name, overwrite)
    except SystemExit as e:
        raise gui_error(e)
    ref_dir = p.dir / "refs" / safe_name(name) if ref_files else None
    opts = set(opts or [])

    def run():
        if ref_dir:
            shutil.rmtree(ref_dir, ignore_errors=True)
            ref_dir.mkdir(parents=True)
            for f in ref_files:
                shutil.copy2(f, ref_dir / Path(f).name)
        run_build(p, name, ids, ref_dir, threshold, relax, int(min_size), sim,
                  (series or "").strip() or None, "keep_core" in opts, "screencap" in opts, tagger,
                  "keep_text" in opts, "keep_crowded" in opts, "keep_offmodel" in opts, "save_dropped" in opts,
                  overwrite, int(upscale_to) if upscale_on else 0, "outfits" in opts, "fresh" in opts)

    progress(0, desc=t("Starting the build..."))
    log = captured(run, txn=txn.build_txn(p, name, ref_dir))
    chars = characters(p.name)
    char = p.char_dir(name).name
    return (log, gr.update(choices=chars, value=char), gr.update(choices=chars, value=char),
            gr.update(choices=chars, value=char), gr.Tabs(selected="review"))


def sorted_root(pname, char):
    return Project(safe_name(pname)).chars_dir / char / "sorted"


def group_of(root, f):
    parts = f.relative_to(root).parts[:-1]
    return parts[1:] if parts and parts[0] == "_review" else parts


def is_review(root, f):
    return f.relative_to(root).parts[0] == "_review"


_alike_cache = {}


def look_alikes(pname, char):
    from . import negatives
    char_dir = sorted_root(pname, char).parent
    key = tuple((char_dir / f).stat().st_mtime_ns if (char_dir / f).exists() else 0
                for f in (negatives.FILE, negatives.FEATS))
    if _alike_cache.get(char_dir, (None,))[0] != key:
        _alike_cache[char_dir] = (key, negatives.look_alikes(char_dir) if key[0] else {})
    return _alike_cache[char_dir][1]


def list_files(pname, char, flt):
    if not pname or not char:
        return []
    root = sorted_root(pname, char)
    files = list(root.rglob("*.png")) if root.exists() else []
    files.sort(key=lambda f: (not is_review(root, f), group_of(root, f), f.name))
    if flt == "_review":
        files = [f for f in files if is_review(root, f)]
    elif flt == "_alike":
        alike = look_alikes(pname, char)
        files = sorted((f for f in files if f.stem in alike), key=lambda f: -alike[f.stem])
    elif flt and flt.startswith("outfit:"):
        files = [f for f in files if flt[7:] in caption_tags(f)]
    elif flt and flt != "all":
        files = [f for f in files if "/".join(group_of(root, f)) == flt]
    return [str(f) for f in files]


def caption_tags(png: Path):
    from .tags import split_tags
    txt = png.with_suffix(".txt")
    return split_tags(txt.read_text(encoding="utf-8")) if txt.exists() else []


def outfits_of(pname, char):
    return Project(safe_name(pname)).load(f"characters/{char}/build.json", {}).get("outfits", [])


def filter_choices(pname, char):
    root = sorted_root(pname, char) if pname and char else None
    files = [Path(f) for f in list_files(pname, char, "all")]
    choices = [(t("All ({n})", n=len(files)), "all")]
    if not files:
        return choices
    n_review = sum(is_review(root, f) for f in files)
    if n_review:
        choices.append((t("⚠ To check ({n})", n=n_review), "_review"))
    alike = look_alikes(pname, char)
    n_alike = sum(f.stem in alike for f in files)
    if n_alike:
        choices.append((t("🚫 Like what you rejected ({n})", n=n_alike), "_alike"))
    for o in outfits_of(pname, char):
        n = sum(o["token"] in caption_tags(f) for f in files)
        choices.append((t("🧥 Outfit {id}: {tags} ({n})", id=o["id"], tags=", ".join(o["tags"][:2]), n=n),
                        f"outfit:{o['token']}"))
    counts = Counter("/".join(group_of(root, f)) for f in files)
    order = lambda g: (list(FRAMING).index(g.split("/")[0]) if g.split("/")[0] in FRAMING else 9, g)
    for g in sorted(counts, key=order):
        fr, vw = (g.split("/") + [""])[:2]
        choices.append((t("{shot} · {angle} ({n})", shot=shot_name(fr), angle=angle_name(vw), n=counts[g]), g))
    return choices


def thumb(char_dir, f: Path):
    tp = char_dir / "_thumbs" / (f.stem + ".jpg")
    if not tp.exists() or tp.stat().st_mtime < f.stat().st_mtime:
        tp.parent.mkdir(exist_ok=True)
        im = Image.open(f).convert("RGB")
        im.thumbnail((320, 320))
        im.save(tp, quality=85)
    return tp


def gallery_items(pname, char, files):
    if not files:
        return []
    root = sorted_root(pname, char)
    alike = look_alikes(pname, char)
    return [(str(thumb(root.parent, f)), "🚫" if f.stem in alike else "⚠" if is_review(root, f) else None)
            for f in map(Path, files)]


def panel(pname, char, files, idx):
    if not files:
        return None, "", t("No images here.")
    f = Path(files[idx])
    txt = f.with_suffix(".txt")
    caption = txt.read_text(encoding="utf-8") if txt.exists() else ""
    root = sorted_root(pname, char)
    build = Project(safe_name(pname)).load(f"characters/{char}/build.json", {"items": []})
    meta = next((it for it in build["items"] if Path(it["file"]).stem == f.stem), None)
    fr, vw = (list(group_of(root, f)) + ["", ""])[:2]
    info = t("**{i} / {n}** — {shot} · {angle}", i=idx + 1, n=len(files), shot=shot_name(fr), angle=angle_name(vw))
    if is_review(root, f):
        info += t(" — ⚠ needs a check")
    if f.stem in look_alikes(pname, char):
        info += t(" — 🚫 looks like an image you rejected as another character")
    if meta:
        m, s = divmod(int(meta["t"]), 60)
        info += "\n\n" + t("Crop: {crop} — episode {ep} at {at} — match score {score} (lower is better) — "
                           "sharpness {sharp}", crop=t(CROP.get(meta["type"], meta["type"])),
                           ep=f"v{meta['vid']:02d}", at=f"{m}:{s:02d}", score=f"{meta['ccip']:.3f}",
                           sharp=f"{meta['sharp']:.0f}")
        if meta.get("upscaled", 1) > 1:
            info += t(" — upscaled ×{f}", f=f"{meta['upscaled']:.1f}")
    return str(f), caption, info


def stats_text(pname, char):
    files = list_files(pname, char, "all")
    if not char:
        return t("Pick a character.")
    root = sorted_root(pname, char)
    n_review = sum(is_review(root, Path(f)) for f in files)
    from . import negatives
    trash = root.parent / "_deleted"
    n_del = len(list(trash.rglob("*.png"))) if trash.exists() else 0
    n_rej = len(negatives.load(root.parent)[0])
    return (t("**{n}** images — **{r}** to check — deleted: {d}", n=len(files), r=n_review, d=n_del)
            + (t(" — rejected as another character: {n}", n=n_rej) if n_rej else ""))


def review_outputs(pname, char, files, idx, regallery=True):
    idx = max(0, min(idx, len(files) - 1)) if files else 0
    img, cap, info = panel(pname, char, files, idx)
    gal = (gr.update(value=gallery_items(pname, char, files), selected_index=idx if files else None)
           if regallery else gr.update(selected_index=idx if files else None))
    return gal, img, cap, info, files, idx, stats_text(pname, char)


def load_review(pname, char, flt):
    return review_outputs(pname, char, list_files(pname, char, flt or "all"), 0)


def change_char(pname, char):
    return (gr.update(choices=filter_choices(pname, char), value="all"), move_choices(),
            *load_review(pname, char, "all"))


def move_choices():
    return gr.update(choices=[(t("{shot} · {angle}", shot=shot_name(f), angle=angle_name(v)), f"{f}/{v}")
                              for f in FRAMING for v in VIEW])


def select_image(pname, char, files, evt: gr.SelectData):
    return review_outputs(pname, char, files, evt.index, regallery=False)


def step(delta):
    def fn(pname, char, files, idx):
        return review_outputs(pname, char, files, idx + delta, regallery=False)
    return fn


def _move_pair(src: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.move(str(src), str(dst))
    txt = src.with_suffix(".txt")
    if txt.exists():
        shutil.move(str(txt), str(dst.with_suffix(".txt")))
    return dst


def _trash(pname, char, files, idx, undo, kind):
    root = sorted_root(pname, char)
    src = Path(files[idx])
    dst = _move_pair(src, root.parent / "_deleted" / src.parent.relative_to(root))
    return (undo or []) + [(str(src), str(dst), kind)]


def filter_update(pname, char, flt):
    choices = filter_choices(pname, char)
    return gr.update(choices=choices, value=flt if flt in [v for _, v in choices] else "all")


def delete_image(pname, char, flt, files, idx, undo):
    if not files:
        raise gr.Error(t("No image selected"))
    undo = _trash(pname, char, files, idx, undo, "delete")
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


def reject_image(pname, char, flt, files, idx, undo):
    from . import negatives
    if not files:
        raise gr.Error(t("No image selected"))
    if not negatives.reject(sorted_root(pname, char).parent, Path(files[idx]).stem):
        raise gr.Error(t("This character was built by an older version of the program: build it again once so it "
                         "can learn from rejections. Or remove the image with “Bad image”."))
    undo = _trash(pname, char, files, idx, undo, "reject")
    alike = look_alikes(pname, char)
    n = sum(Path(f).stem in alike for f in list_files(pname, char, "all"))
    gr.Info(t("Rejected as another character. {n} remaining images look like it: pick “🚫 Like what you "
              "rejected” under “Show”.", n=n)
            if n else t("Rejected as another character; every later build leaves out what looks like it."))
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


def undo_delete(pname, char, flt, files, idx, undo):
    from . import negatives
    if not undo:
        raise gr.Error(t("Nothing to undo"))
    undo = list(undo)
    orig, moved, *kind = undo.pop()
    orig, moved = Path(orig), Path(moved)
    _move_pair(moved, orig.parent)
    if kind == ["reject"]:
        negatives.remove(sorted_root(pname, char).parent, orig.stem)
    files = list_files(pname, char, flt)
    idx = files.index(str(orig)) if str(orig) in files else idx
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


def forget_rejected(pname, char, flt, files, idx):
    from . import negatives
    if not char:
        raise gr.Error(t("Pick a character"))
    char_dir = sorted_root(pname, char).parent
    n = len(negatives.load(char_dir)[0])
    negatives.clear(char_dir)
    gr.Info(t("The program forgot {n} rejected images. The images themselves stay deleted.", n=n))
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), filter_update(pname, char, flt))


def move_image(pname, char, flt, files, idx, target):
    if not files or not target:
        raise gr.Error(t("Pick an image and the target group"))
    _move_pair(Path(files[idx]), sorted_root(pname, char) / target)
    return review_outputs(pname, char, list_files(pname, char, flt), idx)


def save_caption(files, idx, caption):
    if not files:
        raise gr.Error(t("No image selected"))
    Path(files[idx]).with_suffix(".txt").write_text((caption or "").strip(), encoding="utf-8")
    gr.Info(t("Caption saved"))


def char_dir_of(pname, char):
    return Project(safe_name(pname)).chars_dir / char


def _tag_state(pname, char, query=""):
    from .tags import history_size, tag_counts
    if not pname or not char or not (char_dir_of(pname, char) / "sorted").exists():
        return [], t("Pick a built character."), []
    cnt, n = tag_counts(char_dir_of(pname, char))
    q = (query or "").strip().lower()
    rows = [[tag, c, round(100 * c / max(n, 1), 1)] for tag, c in cnt.most_common() if q in tag.lower()]
    status = t("**{n}** captions — **{k}** different tags — changes you can undo: {u}",
               n=n, k=len(cnt), u=history_size(char_dir_of(pname, char)))
    outfits = outfits_of(pname, char)
    if outfits:
        status += "\n\n" + "\n".join(f"- 🧥 {ltr('`' + o['token'] + '`')}: {', '.join(o['tags'])}" for o in outfits)
    return rows, status, list(cnt)


def tag_view(pname, char, query=""):
    rows, status, tags = _tag_state(pname, char, query)
    return rows, status, gr.update(choices=tags, value=[])


def pick_tag(selected, evt: gr.SelectData):
    tag = evt.row_value[0] if getattr(evt, "row_value", None) else evt.value
    sel = list(selected or [])
    if tag and tag not in sel:
        sel.append(tag)
    return sel


def _tag_edit(pname, char, query, **kw):
    from .tags import edit_tags
    if not char:
        raise gr.Error(t("Pick the character"))
    from .outfits import sync_tokens
    n = edit_tags(char_dir_of(pname, char), **kw)
    sync_tokens(Project(safe_name(pname)), char, kw.get("remove", ()), kw.get("replace"))
    gr.Info(t("Changed {n} captions", n=n))
    return tag_view(pname, char, query)


def tag_remove(pname, char, selected, query):
    if not selected:
        raise gr.Error(t("Pick one or more tags in the table"))
    return _tag_edit(pname, char, query, remove=selected)


def tag_replace(pname, char, selected, new_text, query):
    if not selected:
        raise gr.Error(t("Pick one or more tags in the table"))
    return _tag_edit(pname, char, query, replace={tag: new_text or "" for tag in selected})


def tag_add(pname, char, add_text, query):
    from .tags import split_tags
    if not split_tags(add_text or ""):
        raise gr.Error(t("Type the tag to add"))
    return _tag_edit(pname, char, query, add=split_tags(add_text))


def tag_undo(pname, char, query):
    from .tags import undo_last
    if not char:
        raise gr.Error(t("Pick the character"))
    from .outfits import resync_after_undo
    try:
        n = undo_last(char_dir_of(pname, char))
    except SystemExit:
        raise gr.Error(t("No change to undo"))
    resync_after_undo(Project(safe_name(pname)), char)
    gr.Info(t("Restored {n} captions", n=n))
    return tag_view(pname, char, query)


def rerun_outfits(pname, char, query):
    from .outfits import run_outfits
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    log = captured(run_outfits, p, char)
    return (*tag_view(pname, char, query), log)


def save_target(char, parent):
    parent = (parent or "").strip().strip('"').strip("'")
    if not parent:
        raise gr.Error(t("Type or paste the path of the place to save in"))
    parent = Path(parent)
    if not parent.is_absolute():
        raise gr.Error(t("Type the full path, such as {example}", example="D:\\datasets"))
    out = (parent / char).resolve()
    if PROJECTS_DIR.resolve() in out.parents or out == PROJECTS_DIR.resolve():
        raise gr.Error(t("Pick a place outside the program's projects folder, or the images would be deleted "
                         "with the project"))
    return out


def save_summary(pname, char, parent):
    from .export import group_of as export_group
    if not pname or not char:
        return t("Pick a character."), []
    p = Project(safe_name(pname))
    root = sorted_root(pname, char)
    files = sorted(root.rglob("*.png")) if root.exists() else []
    if not files:
        return t("There are no images for this character. Build it first (tab 2)."), []
    build = p.load(f"characters/{char}/build.json", {})
    n_review = sum(is_review(root, f) for f in files)
    alike = look_alikes(pname, char)
    n_alike = sum(f.stem in alike for f in files)
    n_txt = sum(f.with_suffix(".txt").exists() for f in files)
    upscaled = {Path(it["file"]).stem for it in build.get("items", []) if it.get("upscaled", 1) > 1}
    stems = {f.stem for f in files}
    lines = [t("**{n} images** will be saved with {c} caption files.", n=len(files), c=n_txt),
             t("- Trigger word: `{name}`", name=build.get("name", char))
             + (t(" — anime name: `{series}`", series=build["series"]) if build.get("series") else "")]
    if upscaled & stems:
        lines.append(t("- Upscaled with the anime model: {n}", n=len(upscaled & stems)))
    for o in build.get("outfits", []):
        n = sum(o["token"] in caption_tags(f) for f in files)
        lines.append(t("- Outfit {id} `{token}`: {n} images ({tags})", id=o["id"], token=o["token"], n=n,
                       tags=", ".join(o["tags"][:3])))
    if n_review:
        lines.append(t("- ⚠ **{n} images are still marked to check**, and will be saved with the rest. Check them "
                       "in tab 3 first.", n=n_review))
    if n_alike:
        lines.append(t("- 🚫 **{n} images look like one you rejected as another character**. Check them in tab 3.",
                       n=n_alike))
    if n_txt < len(files):
        lines.append(t("- ⚠ {n} images have no caption file.", n=len(files) - n_txt))
    try:
        lines.append("\n" + t("**Saving to:** `{path}`", path=save_target(char, parent)))
    except gr.Error:
        pass
    counts = Counter(export_group(root, f) for f in files)
    rows = []
    for g in sorted(counts, key=lambda g: -counts[g]):
        fr, vw = (g.split("/") + [""])[:2]
        rows.append([shot_name(fr), angle_name(vw), counts[g]])
    rows.append([t("Total"), "", len(files)])
    return "\n".join(lines), rows


def do_save(pname, char, parent):
    from .aitk import MARKER, save_settings
    from .export import run_export
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    out = save_target(char, parent)
    if out.exists() and any(out.iterdir()) and not (out / MARKER).exists():
        raise gr.Error(t("There is a folder named {name} in that place that the program didn't make, so it won't "
                         "be overwritten. Pick another place.", name=out.name))
    save_settings(save_dir=str(out.parent))
    log = captured(run_export, p, char, str(out), txn=txn.export_txn(p, char, out))
    proj = p.load("project.json", {"videos": []})
    proj.setdefault("saved", {})[char] = str(out)
    p.save("project.json", proj)
    return log


def delete_hint(pname):
    from .cleanup import disk_usage, fmt_bytes
    if not pname or not Project(safe_name(pname)).dir.exists():
        return ""
    p = Project(safe_name(pname))
    size = fmt_bytes(sum(b for _, b in disk_usage(p)))
    saved = p.load("project.json", {}).get("saved", {})
    text = t("Deletes the whole project folder **{name}** from the program folder ({size}): frames, characters "
             "and saved analysis. The original episodes and the images you saved elsewhere aren't touched.",
             name=p.name, size=size)
    if saved:
        text += "\n\n" + t("Saved from it: ") + t(", ").join(t("`{char}` → `{path}`", char=c, path=d)
                                                             for c, d in saved.items())
    else:
        text += "\n\n" + t("⚠ **No character of this project was saved yet.**")
    return text


def delete_project(pname, confirm):
    from .cleanup import disk_usage, fmt_bytes
    p = need_project(pname)
    if not p.dir.exists():
        raise gr.Error(t("The project doesn't exist"))
    if not confirm:
        raise gr.Error(t("Tick the confirmation first: deleting the project is final"))
    size = fmt_bytes(sum(b for _, b in disk_usage(p)))
    try:
        shutil.rmtree(p.dir)
    except OSError as e:
        raise gr.Error(t("Some files couldn't be deleted (open in another program?): {error}", error=e))
    left = projects()
    gr.Info(t("Deleted the project {name} and freed {size}.", name=p.name, size=size))
    return gr.update(choices=left, value=left[0] if left else None), gr.update(value=False)


def remember_language():
    from .aitk import save_settings
    save_settings(ui_lang=lang())


def build_ui():
    import onnxruntime as ort
    gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    with gr.Blocks(title="animelora", analytics_enabled=False) as demo, use("ar"):
        build_page(demo, "ar", gpu)
    with demo.route(LANGS["en"], "en"), use("en"):
        build_page(demo, "en", gpu)
    return demo


def build_page(demo, language, gpu):
    from .aitk import load_settings
    L = lambda fn: bound(language, fn)
    gr.Navbar(main_page_name=LANGS["ar"])
    gr.Markdown("## " + t("animelora — LoRA datasets of a character from anime episodes") + "\n"
                + (t("🟢 The graphics card is used (CUDA)") if gpu else t("🔴 Running on the CPU only (slow)")))
    with gr.Row():
        project = gr.Dropdown(choices=projects(), value=(projects() or [None])[0], allow_custom_value=True,
                              label=t("Project (pick one or type a new name)"), scale=4)
        refresh = gr.Button(t("🔄 Refresh"), scale=1)

    with gr.Tabs() as tabs:
        with gr.Tab(t("1. Scan episodes"), id="scan"):
            gr.Markdown(t("Paste one episode path per line, or the path of a whole folder. "
                          "(In Windows Explorer: Shift + right-click the file → Copy as path)"))
            with gr.Row():
                with gr.Column(scale=3):
                    videos = gr.Textbox(lines=4, label=t("Episodes"), elem_classes="ltr",
                                        placeholder="D:\\anime\\ep01.mkv\nD:\\anime\\Season 1")
                    auto = gr.Checkbox(True, label=t("Find the OP/ED automatically: parts repeated between episodes "
                                                     "are left out. With one episode, the next episode in its folder "
                                                     "is used for the comparison"))
                    skip = gr.Textbox(label=t("More times to ignore (optional)"), elem_classes="ltr",
                                      placeholder="0:00-1:55, 21:55-24:30")
                    with gr.Accordion(t("Advanced settings"), open=False):
                        auto_min = gr.Slider(15, 120, 40, step=5,
                                             label=t("Shortest repeated part counted as OP/ED (seconds)"))
                        autoskip_btn = gr.Button(t("Find the OP/ED again for the scanned episodes"))
                        stop_auto = gr.Button(stop_label(), variant="stop", visible=False)
                        min_gap = gr.Slider(0.1, 2.0, 0.35, step=0.05,
                                            label=t("Shortest gap between two kept frames (seconds)"))
                        keep_diff = gr.Slider(1, 20, 5, step=0.5, label=t("How much a frame must change to be kept "
                                                                          "again"))
                    scan_btn = gr.Button(t("▶ Start scanning"), variant="primary")
                    stop_scan = gr.Button(stop_label(), variant="stop", visible=False)
                with gr.Column(scale=3):
                    vids_df = gr.Dataframe(headers=["#", t("Episode"), t("Length (min)"), t("Frames"),
                                                    t("Left out automatically")],
                                           interactive=False, wrap=True, label=t("Episodes scanned in this project"),
                                           column_widths=["5%", "31%", "13%", "13%", "38%"])
                    with gr.Accordion(t("💾 Disk space"), open=False):
                        usage = gr.Markdown()
                        clean_safe_btn = gr.Button(t("🧹 Safe clean: delete frames the program doesn't need + "
                                                     "thumbnails"))
                        gr.Markdown(t("**Deleting all frames** saves more and keeps the finished images, but the "
                                      "project can't be built or clustered again."))
                        clean_confirm = gr.Checkbox(label=t("I understand this deletion is final"))
                        clean_all_btn = gr.Button(t("Delete all frames"), variant="stop")
            scan_log = gr.Textbox(lines=12, label=t("Log"), elem_id="log", autoscroll=True)

        with gr.Tab(t("2. Pick the character"), id="pick"):
            gr.Markdown(t("Click a character's image to select it, click again to unselect. If the character shows up "
                          "in more than one cluster (another outfit, say), pick all of them. **The numbers change "
                          "after every scan.**"))
            with gr.Row():
                with gr.Column(scale=3):
                    clusters_gal = gr.Gallery(label=t("Characters found"), columns=5, height=560,
                                              allow_preview=False, object_fit="contain", buttons=[])
                    with gr.Accordion(t("Re-cluster (if two characters got mixed, or one got split)"), open=False):
                        cut = gr.Slider(0.10, 0.40, 0.20, step=0.01,
                                        label=t("Merge distance: lower = more, smaller clusters"))
                        min_csize = gr.Slider(3, 40, 8, step=1, label=t("Hide clusters smaller than"))
                        recluster_btn = gr.Button(t("Re-cluster the whole project"))
                        gr.Markdown(t("**Or split one mixed cluster on its own:** select it (only that one), then "
                                      "press “Split”. The other clusters keep their numbers; the new parts get "
                                      "numbers at the end of the list."))
                        split_cut = gr.Slider(0.06, 0.19, 0.14, step=0.01,
                                              label=t("Split strength: lower = more parts"))
                        split_btn = gr.Button(t("✂ Split the selected cluster"))
                        stop_clu = gr.Button(stop_label(), variant="stop", visible=False)
                        recluster_log = gr.Textbox(lines=6, label=t("Log"), elem_id="log")
                with gr.Column(scale=2):
                    chosen = gr.CheckboxGroup(label=t("Selected clusters"), choices=[])
                    sheet = gr.Image(label=t("Cluster preview"), interactive=False, height=320,
                                     buttons=["fullscreen"])
                    refs = gr.File(file_count="multiple", file_types=["image"], type="filepath", height=150,
                                   label=t("Or/and: reference images of the character (optional, useful for side "
                                           "characters)"))
                    name = gr.Textbox(label=t("Trigger word (the character's name)"), elem_classes="ltr",
                                      placeholder="natsu_ft")
                    series = gr.Textbox(label=t("Anime name as a tag (optional)"), elem_classes="ltr",
                                        placeholder="fairy tail")
                    upscale_on = gr.Checkbox(label=t("Enlarge small images with an anime upscaler (CDC): cleaner "
                                                     "lines than plain resizing, and small crops become usable"))
                    upscale_to = gr.Slider(512, 1536, 1024, step=64, visible=False,
                                           label=t("Enlarge every image smaller than this to it (pixels; use your "
                                                   "training resolution)"))
                    with gr.Accordion(t("Advanced settings"), open=False):
                        threshold = gr.Slider(0.06, 0.25, 0.13, step=0.005,
                                              label=t("Match threshold: lower = stricter and fewer images, higher = "
                                                      "more images and more mistakes"))
                        sim = gr.Slider(0.60, 0.98, 0.80, step=0.01,
                                        label=t("Duplicate threshold: lower = more duplicates removed"))
                        min_size = gr.Slider(256, 1024, 448, step=32, label=t("Smallest crop size (pixels)"))
                        relax = gr.Slider(1.0, 2.0, 1.0, step=0.05,
                                          label=t("Shot tracking (1 = off; may let wrong characters in)"))
                        tagger = gr.Dropdown(["EVA02_Large", "SwinV2_v3", "ConvNext_v3", "ViT_v3"],
                                             value="EVA02_Large", label=t("Tagging model"))
                        opts = gr.CheckboxGroup(build_options(), value=["outfits", "screencap"], label=t("Options"))
                    overwrite = gr.Checkbox(label=t("Replace earlier results with the same name (clears your earlier "
                                                    "review)"))
                    build_btn = gr.Button(t("▶ Build the image set"), variant="primary")
                    stop_build = gr.Button(stop_label(), variant="stop", visible=False)
            build_log = gr.Textbox(lines=14, label=t("Report"), elem_id="log")

        with gr.Tab(t("3. Review"), id="review"):
            gr.Markdown(t("Remove every image that isn't the character, starting with the ones marked ⚠. **N** (not "
                          "this character): an image of another character - the program learns from it, marks what "
                          "looks like it with 🚫 and leaves it out of every later build. **Delete**: a bad image of "
                          "the character itself; nothing is learned. **← →** to move, **Ctrl+Z** to undo."))
            with gr.Row():
                r_char = gr.Dropdown(label=t("Character"), choices=[], scale=2)
                r_filter = gr.Dropdown(label=t("Show"), choices=[(t("All"), "all")], value="all", scale=2)
                r_stats = gr.Markdown()
            with gr.Row():
                with gr.Column(scale=3):
                    r_gal = gr.Gallery(columns=6, height=720, allow_preview=False, object_fit="contain",
                                       show_label=False, buttons=[])
                with gr.Column(scale=2):
                    r_img = gr.Image(interactive=False, height=460, show_label=False, elem_id="preview",
                                     buttons=["fullscreen"])
                    r_info = gr.Markdown()
                    with gr.Row():
                        prev_btn = gr.Button(t("← Previous"), elem_id="btn-prev")
                        next_btn = gr.Button(t("Next →"), elem_id="btn-next")
                    with gr.Row():
                        reject_btn = gr.Button(t("🚫 Not this character (N)"), variant="stop", elem_id="btn-reject")
                        del_btn = gr.Button(t("🗑 Bad image (Delete)"), elem_id="btn-del")
                        undo_btn = gr.Button(t("↶ Undo"), elem_id="btn-undo")
                    r_caption = gr.Textbox(lines=4, label=t("Caption"), elem_classes="ltr")
                    save_btn = gr.Button(t("💾 Save caption"))
                    with gr.Row():
                        move_to = gr.Dropdown(label=t("Wrong group? Move it to"), choices=[], scale=3)
                        move_btn = gr.Button(t("↪ Move"), scale=1)
                    forget_btn = gr.Button(t("Forget all images rejected as another character"), size="sm")
            files_st, idx_st, undo_st = gr.State([]), gr.State(0), gr.State([])

        with gr.Tab(t("4. Tags"), id="tags"):
            gr.Markdown(t("All tags in the character's captions and how often they appear. Click a tag in the table "
                          "to select it, then remove or replace it in **all** captions at once. Every change can be "
                          "undone."))
            with gr.Row():
                with gr.Column(scale=3):
                    with gr.Row():
                        t_char = gr.Dropdown(label=t("Character"), choices=[], scale=2)
                        t_search = gr.Textbox(label=t("Search"), elem_classes="ltr", scale=2)
                    t_table = gr.Dataframe(headers=[t("Tag"), t("Count"), "%"], interactive=False, max_height=620,
                                           column_widths=["70%", "15%", "15%"])
                with gr.Column(scale=2):
                    t_status = gr.Markdown()
                    t_selected = gr.Dropdown(label=t("Selected tags"), choices=[], multiselect=True,
                                             allow_custom_value=True, elem_classes="ltr")
                    t_remove_btn = gr.Button(t("🗑 Remove the selected from all captions"), variant="stop")
                    with gr.Row():
                        t_new = gr.Textbox(label=t("Replace the selected with (empty = remove)"), elem_classes="ltr",
                                           scale=3, placeholder="brown eyes")
                        t_replace_btn = gr.Button(t("↔ Replace"), scale=1)
                    with gr.Row():
                        t_add_text = gr.Textbox(label=t("Add a tag to every caption"), elem_classes="ltr", scale=3)
                        t_add_btn = gr.Button(t("➕ Add"), scale=1)
                    t_undo_btn = gr.Button(t("↶ Undo the last change (Ctrl+Z)"), elem_id="btn-tag-undo")
                    gr.Markdown(t("**Outfits:** after deleting images in review, separate the outfits again to update "
                                  "them."))
                    t_outfits_btn = gr.Button(t("🧥 Separate the outfits again"))
                    t_log = gr.Textbox(lines=4, label=t("Log"), elem_id="log")

        with gr.Tab(t("5. Save the result"), id="export"):
            gr.Markdown(t("Saves the reviewed images with their captions in a folder named after the character, inside "
                          "the place you choose. That folder is the dataset you train on."))
            saved_dir = load_settings().get("save_dir", "")
            with gr.Row():
                with gr.Column(scale=2):
                    e_char = gr.Dropdown(label=t("Character"), choices=[])
                    e_out = gr.Textbox(saved_dir, label=t("Save to (paste a folder path; a folder named after the "
                                                          "character is made in it)"),
                                       elem_classes="ltr", placeholder="D:\\datasets")
                    export_btn = gr.Button(t("💾 Save the images and captions"), variant="primary")
                    stop_export = gr.Button(stop_label(), variant="stop", visible=False)
                    export_log = gr.Textbox(lines=6, label=t("Log"), elem_id="log")
                with gr.Column(scale=2):
                    e_summary = gr.Markdown()
                    groups_df = gr.Dataframe(headers=[t("Shot"), t("Angle"), t("Count")], interactive=False,
                                             label=t("Distribution"))
            with gr.Accordion(t("🗑 Delete the project from the program folder (after saving)"), open=False):
                del_hint = gr.Markdown()
                del_confirm = gr.Checkbox(label=t("I understand deleting the project is final and can't be undone"))
                del_project_btn = gr.Button(t("🗑 Delete the project"), variant="stop")

    proj_outputs = [vids_df, clusters_gal, chosen, r_char, e_char, t_char, usage]
    project.change(L(load_project), project, proj_outputs)
    refresh.click(L(lambda p: (gr.update(choices=projects()), *load_project(p))), project, [project, *proj_outputs])

    def init_page(p):
        names = projects()
        p = p if p in names else (names[0] if names else p)
        return (gr.update(choices=names, value=p), *load_project(p))

    demo.load(L(init_page), project, [project, *proj_outputs])
    demo.load(L(remember_language), None, None)

    def long_action(btn, stop, fn, inputs, outputs):
        ev = btn.click(L(start_ui), None, stop, queue=False).then(L(fn), inputs, outputs, concurrency_id="gpu")
        ev.then(end_ui, None, stop, queue=False)
        ev.failure(end_ui, None, stop, queue=False)
        return ev

    for stop in (stop_scan, stop_auto, stop_clu, stop_build, stop_export):
        stop.click(L(press_stop), None, stop, queue=False)

    long_action(scan_btn, stop_scan, do_scan, [project, videos, skip, auto, auto_min, min_gap, keep_diff],
                [scan_log, project, *proj_outputs])
    long_action(autoskip_btn, stop_auto, do_autoskip, [project, auto, auto_min], [scan_log, *proj_outputs])
    long_action(recluster_btn, stop_clu, do_recluster, [project, cut, min_csize],
                [recluster_log, clusters_gal, chosen])
    long_action(split_btn, stop_clu, do_split, [project, chosen, split_cut], [recluster_log, clusters_gal, chosen])
    clean_safe_btn.click(L(lambda p: do_clean(p, False, False)), project, [scan_log, usage])
    clean_all_btn.click(L(lambda p, c: do_clean(p, True, c)), [project, clean_confirm], [scan_log, usage])
    clusters_gal.select(L(pick_cluster), [project, chosen], [chosen, sheet])
    upscale_on.change(lambda on: (gr.update(visible=on), gr.update(value=320 if on else 448)),
                      upscale_on, [upscale_to, min_size])
    long_action(build_btn, stop_build, do_build,
                [project, chosen, refs, name, series, upscale_on, upscale_to, threshold, min_size, sim, relax,
                 tagger, opts, overwrite],
                [build_log, r_char, e_char, t_char, tabs]) \
        .success(L(change_char), [project, r_char],
                 [r_filter, move_to, r_gal, r_img, r_caption, r_info, files_st, idx_st, r_stats])

    rv_out = [r_gal, r_img, r_caption, r_info, files_st, idx_st, r_stats]
    r_char.change(L(change_char), [project, r_char], [r_filter, move_to, *rv_out])
    r_filter.change(L(load_review), [project, r_char, r_filter], rv_out)
    r_gal.select(L(select_image), [project, r_char, files_st], rv_out)
    prev_btn.click(L(step(-1)), [project, r_char, files_st, idx_st], rv_out)
    next_btn.click(L(step(+1)), [project, r_char, files_st, idx_st], rv_out)
    trash_in = [project, r_char, r_filter, files_st, idx_st, undo_st]
    del_btn.click(L(delete_image), trash_in, [*rv_out, undo_st, r_filter])
    reject_btn.click(L(reject_image), trash_in, [*rv_out, undo_st, r_filter])
    undo_btn.click(L(undo_delete), trash_in, [*rv_out, undo_st, r_filter])
    forget_btn.click(L(forget_rejected), [project, r_char, r_filter, files_st, idx_st], [*rv_out, r_filter])
    move_btn.click(L(move_image), [project, r_char, r_filter, files_st, idx_st, move_to], rv_out)
    save_btn.click(L(save_caption), [files_st, idx_st, r_caption], None)

    t_out = [t_table, t_status, t_selected]
    t_char.change(L(tag_view), [project, t_char, t_search], t_out)
    t_search.change(L(tag_view), [project, t_char, t_search], t_out)
    t_table.select(pick_tag, t_selected, t_selected)
    t_remove_btn.click(L(tag_remove), [project, t_char, t_selected, t_search], t_out)
    t_replace_btn.click(L(tag_replace), [project, t_char, t_selected, t_new, t_search], t_out)
    t_add_btn.click(L(tag_add), [project, t_char, t_add_text, t_search], t_out)
    t_undo_btn.click(L(tag_undo), [project, t_char, t_search], t_out)
    t_outfits_btn.click(L(rerun_outfits), [project, t_char, t_search], [*t_out, t_log])

    sum_in, sum_out = [project, e_char, e_out], [e_summary, groups_df]
    e_char.change(L(save_summary), sum_in, sum_out)
    e_out.change(L(save_summary), sum_in, sum_out)
    tabs.select(L(save_summary), sum_in, sum_out)
    tabs.select(L(delete_hint), project, del_hint)
    project.change(L(delete_hint), project, del_hint)
    tabs.select(L(tag_view), [project, t_char, t_search], t_out)
    long_action(export_btn, stop_export, do_save, [project, e_char, e_out], [export_log]) \
        .success(L(delete_hint), project, del_hint)
    del_project_btn.click(L(delete_project), [project, del_confirm], [project, del_confirm])


def launch(port=7860, open_browser=True):
    import webbrowser
    from .aitk import load_settings
    from .common import setup_runtime
    setup_runtime()
    PROJECTS_DIR.mkdir(exist_ok=True)
    demo = build_ui()
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=port, inbrowser=False, prevent_thread_lock=True,
        allowed_paths=[str(PROJECTS_DIR)], theme=gr.themes.Soft(), css=CSS, head=HEAD)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/" + ("en" if load_settings().get("ui_lang") == "en" else ""))
    demo.block_thread()
