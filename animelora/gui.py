"""Gradio GUI (Arabic, right-to-left) over the CLI stages: scan -> pick -> review -> tags -> export."""
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
from .common import PROJECTS_DIR, Project, parse_ranges, safe_name

FRAMING_AR = {"close_up": "لقطة قريبة", "upper_body": "نصف علوي", "cowboy_shot": "حتى الفخذ", "full_body": "جسم كامل"}
VIEW_AR = {"front": "أمام", "three_quarter": "ثلاثة أرباع", "side": "جانب", "back": "خلف", "above": "من الأعلى",
           "below": "من الأسفل"}
TYPE_AR = {"full": "الشخصية كاملة", "half": "نصف علوي", "head": "الرأس"}
BUILD_OPTIONS = [("فصل الأزياء تلقائيًا (وسم لكل زي بعد كلمة التفعيل)", "outfits"),
                 ("وسم anime screencap في أول كل وصف", "screencap"),
                 ("إبقاء صفات الشعر والعيون في الوصف", "keep_core"),
                 ("إبقاء الصور التي فيها نصوص", "keep_text"),
                 ("إبقاء الصور المزدحمة بشخصيات أخرى", "keep_crowded"),
                 ("إبقاء الرسم المصغّر (chibi) والضبابي", "keep_offmodel"),
                 ("حفظ الصور المستبعدة في مجلد _dropped", "save_dropped"),
                 ("إعادة التحليل من الصفر وتجاهل المحفوظ (أبطأ بكثير، نادرًا ما تحتاجه)", "fresh")]

CSS = """
.gradio-container { direction: rtl; }
.ltr textarea, .ltr input { direction: ltr !important; text-align: left !important; }
#log textarea { direction: ltr; text-align: left; font-family: Consolas, monospace; font-size: 12px; }
#preview img { object-fit: contain; }
"""
# Review shortcuts. Only fire when the button is visible (its tab is open) and the user isn't typing.
HEAD = """<script>
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'textarea' || tag === 'input') return;
  const click = (id) => { const b = document.getElementById(id); if (b && b.offsetParent !== null) { b.click(); e.preventDefault(); } };
  if (e.key === 'Delete') click('btn-del');
  else if (e.code === 'KeyN' && !e.ctrlKey && !e.metaKey && !e.altKey) click('btn-reject');
  else if (e.key === 'ArrowLeft') click('btn-next');
  else if (e.key === 'ArrowRight') click('btn-prev');
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { click('btn-undo'); click('btn-tag-undo'); }
});
</script>"""


# ---------- helpers ----------

def projects():
    return sorted(p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()) if PROJECTS_DIR.exists() else []


def need_project(pname) -> Project:
    if not pname or not safe_name(pname):
        raise gr.Error("اختر مشروعًا أو اكتب اسم مشروع جديد في الأعلى")
    return Project(safe_name(pname))


def characters(pname):
    if not pname:
        return []
    d = Project(safe_name(pname)).chars_dir
    return sorted(p.name for p in d.iterdir() if (p / "sorted").exists()) if d.exists() else []


# Arabic hints for the pipeline's (English) error messages, matched by prefix/substring
ERRORS_AR = [("not found:", "الملف أو المجلد غير موجود"),
             ("already exists", "توجد نتائج سابقة بهذا الاسم. فعّل «استبدال نتائج سابقة» لإعادة البناء، "
                                "أو اختر اسمًا آخر"),
             ("no matches", "لم يُعثر على الشخصية. ارفع «حد التطابق» قليلًا أو اختر مجموعات أخرى"),
             ("no characters detected", "لم تُكتشف أي شخصيات في الحلقات"),
             ("nothing scanned yet", "امسح حلقة واحدة على الأقل أولًا (التبويب ١)"),
             ("no clusters yet", "امسح حلقة واحدة على الأقل أولًا (التبويب ١)"),
             ("does not exist", "رقم مجموعة غير موجود. الأرقام تتغير بعد كل مسح، حدّث الصفحة"),
             ("no images in", "لا توجد صور في المراجع المرفوعة"),
             ("not enough clear", "لا توجد مشاهد واضحة كافية للتجميع"),
             ("were deleted to save space", "إطارات هذا المشروع حُذفت لتوفير المساحة. لبناء شخصية جديدة امسح الحلقات "
                                            "في مشروع جديد"),
             ("didn't split", "لم تنقسم المجموعة بهذه الشدة، اخفض «شدة التقسيم»"),
             ("too small to split", "المجموعة أصغر من أن تُقسم"),
             ("was not made by animelora", "يوجد مجلد بيانات بهذا الاسم في AI Toolkit لم يُنشئه البرنامج، "
                                           "ولن يُستبدل. اختر اسم مجلد بيانات آخر"),
             ("AI Toolkit folder not found", "مجلد AI Toolkit غير صحيح: يجب أن يحتوي على مجلد datasets")]


def gui_error(e: SystemExit):
    msg = str(e) or "failed"
    hint = next((ar for key, ar in ERRORS_AR if key in msg), None)
    return gr.Error(f"{hint}\n\n{msg}" if hint else msg)


def captured(fn, *args, txn=None):
    """Run a pipeline stage, return what it printed; its SystemExit messages become GUI errors.
    txn: a txn.Transaction - if the stage is stopped or fails, what it generated is removed."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if txn is None:
                fn(*args)
            else:
                with txn:
                    fn(*args)
    except Cancelled:
        raise gr.Error("أُوقفت العملية، وحُذف كل ما ولّدته، فعاد المشروع كما كان قبلها.", title="⏹ تم الإيقاف")
    except SystemExit as e:
        raise gui_error(e)
    return buf.getvalue()


# ---------- stop buttons ----------
# Every long action shows its own stop button while it runs. Pressing it sets the cancel flag; the pipeline
# stops at its next frame/image and the action's Transaction removes what it had generated.

STOP_LABEL = "⏹ إيقاف وحذف ما وُلّد"


def start_ui():
    cancel.reset()
    return gr.update(visible=True, value=STOP_LABEL, interactive=True)


def end_ui():
    return gr.update(visible=False)


def press_stop():
    cancel.request()
    return gr.update(value="⏳ جارٍ الإيقاف والتراجع...", interactive=False)


def _mmss(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def videos_table(pname):
    if not pname:
        return []
    proj = Project(safe_name(pname)).load("project.json", {"videos": []})
    rows = []
    for v in proj["videos"]:
        # kept all-Latin ("OP 0:30–2:02 | ED 22:00–24:21"): mixing Arabic words with times scrambled on wrap
        segs = " | ".join(f"{lab} {_mmss(s)}–{_mmss(e)}" for s, e, lab in v.get("auto_skip", []))
        segs = f"⁦{segs}⁩" if segs else "—"
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
        items.append((str(card), f"#{c['id']}  ·  {len(c['members'])} ظهور"))
    return items, [f"#{c['id']}" for c in data["clusters"]]


def load_project(pname):
    items, choices = clusters_view(pname)
    chars = characters(pname)
    first = chars[0] if chars else None
    return (videos_table(pname), items, gr.update(choices=choices, value=[]),
            gr.update(choices=chars, value=first), gr.update(choices=chars, value=first),
            gr.update(choices=chars, value=first), usage_md(pname))


# ---------- tab 1: scan ----------

def do_scan(pname, videos_text, skip_text, auto, auto_min, min_gap, keep_diff,
            progress=gr.Progress(track_tqdm=True)):
    from .scan import run_scan
    p = need_project(pname)
    paths = [l.strip().strip('"').strip("'") for l in (videos_text or "").splitlines() if l.strip()]
    if not paths:
        raise gr.Error("أدخل مسار حلقة واحدة على الأقل أو مجلد حلقات")
    try:
        text = re.sub(r"\s*-\s*", "-", (skip_text or "").strip())
        skip = parse_ranges([s for s in re.split(r"[,\s]+", text) if s])
    except ValueError:
        raise gr.Error("صيغة أوقات التخطي غير صحيحة. مثال: 0:00-1:55, 21:55-24:30")
    progress(0, desc="بدء المسح...")
    log = captured(run_scan, p, paths, skip, min_gap, keep_diff, auto, auto_min, txn=txn.scan_txn(p))
    return (log, gr.update(choices=projects()), *load_project(p.name))


def do_autoskip(pname, auto, auto_min, progress=gr.Progress(track_tqdm=True)):
    from .repeats import clear_repeats, detect_repeats
    from .scan import run_clusters
    p = need_project(pname)
    if not p.load("project.json"):
        raise gr.Error("امسح حلقة واحدة على الأقل أولًا")
    def redo():
        if auto:
            detect_repeats(p, auto_min)
        else:
            clear_repeats(p)
        run_clusters(p)

    progress(0, desc="مقارنة الحلقات...")
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
        raise gr.Error("حدّد مجموعة واحدة فقط (المختلطة) ثم اضغط «قسّم»")
    log = captured(split_cluster, p, ids[0], cut, txn=txn.clusters_txn(p))
    items, choices = clusters_view(p.name)
    return log, items, gr.update(choices=choices, value=[])


USAGE_AR = {"frames": "الإطارات المستخرجة", "scan": "بيانات المسح", "clusters": "صور المجموعات",
            "cache": "التحليل المحفوظ لإعادة البناء"}


def usage_md(pname):
    from .cleanup import disk_usage, fmt_bytes
    if not pname or not Project(safe_name(pname)).dir.exists():
        return ""
    p = Project(safe_name(pname))
    rows = [(l, b) for l, b in disk_usage(p) if b]
    gone = p.load("project.json", {}).get("frames_deleted")
    lines = [f"**حجم المشروع: {fmt_bytes(sum(b for _, b in rows))}**"
             + (" — الإطارات محذوفة، لا يمكن البناء من جديد" if gone else ""), "",
             "| الجزء | الحجم |", "|---|---|"]
    lines += [f"| {USAGE_AR.get(l, l.replace('characters/', 'الشخصية '))} | ⁦{fmt_bytes(b)}⁩ |" for l, b in rows]
    return "\n".join(lines)


def do_clean(pname, all_frames, confirm):
    from .cleanup import clean
    p = need_project(pname)
    if all_frames and not confirm:
        raise gr.Error("فعّل خانة التأكيد أولًا: حذف كل الإطارات نهائي ويمنع إعادة البناء")
    log = captured(clean, p, "all" if all_frames else "safe")
    return log, usage_md(pname)


# ---------- tab 2: pick + build ----------

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
        raise gr.Error("اكتب كلمة التفعيل (اسم الشخصية)")
    ids = sorted(int(s.lstrip("#")) for s in selected or [])
    if not ids and not ref_files:
        raise gr.Error("اختر مجموعة واحدة على الأقل من الصور، أو ارفع صورًا مرجعية")
    try:
        check_overwrite(p, name, overwrite)  # before the undo snapshot, which moves the old sorted/ aside
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

    progress(0, desc="بدء البناء...")
    log = captured(run, txn=txn.build_txn(p, name, ref_dir))
    chars = characters(p.name)
    char = p.char_dir(name).name
    return (log, gr.update(choices=chars, value=char), gr.update(choices=chars, value=char),
            gr.update(choices=chars, value=char), gr.Tabs(selected="review"))


# ---------- tab 3: review ----------

def sorted_root(pname, char):
    return Project(safe_name(pname)).chars_dir / char / "sorted"


def group_of(root, f):
    parts = f.relative_to(root).parts[:-1]
    return parts[1:] if parts and parts[0] == "_review" else parts


def is_review(root, f):
    return f.relative_to(root).parts[0] == "_review"


_alike_cache = {}


def look_alikes(pname, char):
    """{image name: margin} of images that look like one rejected as another character (negatives.py),
    recomputed only when the rejections or the build change."""
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
    elif flt == "_alike":  # most alike first
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
    choices = [(f"الكل ({len(files)})", "all")]
    if not files:
        return choices
    n_review = sum(is_review(root, f) for f in files)
    if n_review:
        choices.append((f"⚠ للمراجعة ({n_review})", "_review"))
    alike = look_alikes(pname, char)
    n_alike = sum(f.stem in alike for f in files)
    if n_alike:
        choices.append((f"🚫 تشبه ما رفضته ({n_alike})", "_alike"))
    for o in outfits_of(pname, char):
        n = sum(o["token"] in caption_tags(f) for f in files)
        choices.append((f"🧥 زي {o['id']}: {', '.join(o['tags'][:2])} ({n})", f"outfit:{o['token']}"))
    counts = Counter("/".join(group_of(root, f)) for f in files)
    for g in sorted(counts, key=lambda g: (list(FRAMING_AR).index(g.split("/")[0]) if g.split("/")[0] in FRAMING_AR else 9, g)):
        fr, vw = (g.split("/") + [""])[:2]
        choices.append((f"{FRAMING_AR.get(fr, fr)} · {VIEW_AR.get(vw, vw)} ({counts[g]})", g))
    return choices


def thumb(char_dir, f: Path):
    t = char_dir / "_thumbs" / (f.stem + ".jpg")
    if not t.exists() or t.stat().st_mtime < f.stat().st_mtime:
        t.parent.mkdir(exist_ok=True)
        im = Image.open(f).convert("RGB")
        im.thumbnail((320, 320))
        im.save(t, quality=85)
    return t


def gallery_items(pname, char, files):
    if not files:
        return []
    root = sorted_root(pname, char)
    alike = look_alikes(pname, char)
    # full labels don't fit on thumbnails; the side panel shows them, the grid only flags images to check
    return [(str(thumb(root.parent, f)), "🚫" if f.stem in alike else "⚠" if is_review(root, f) else None)
            for f in map(Path, files)]


def panel(pname, char, files, idx):
    """Large preview, caption and info line for files[idx]."""
    if not files:
        return None, "", "لا توجد صور هنا."
    f = Path(files[idx])
    txt = f.with_suffix(".txt")
    caption = txt.read_text(encoding="utf-8") if txt.exists() else ""
    root = sorted_root(pname, char)
    build = Project(safe_name(pname)).load(f"characters/{char}/build.json", {"items": []})
    meta = next((it for it in build["items"] if Path(it["file"]).stem == f.stem), None)
    fr, vw = (list(group_of(root, f)) + ["", ""])[:2]
    info = f"**{idx + 1} / {len(files)}** — {FRAMING_AR.get(fr, fr)} · {VIEW_AR.get(vw, vw)}"
    if is_review(root, f):
        info += " — ⚠ تحتاج تأكيدًا"
    if f.stem in look_alikes(pname, char):
        info += " — 🚫 تشبه صورة رفضتها كشخصية أخرى"
    if meta:
        m, s = divmod(int(meta["t"]), 60)
        # ⁦..⁩ isolate Latin text/numbers so they don't scramble the right-to-left line
        ep, at = f"⁦v{meta['vid']:02d}⁩", f"⁦{m}:{s:02d}⁩"
        score, sharp = f"⁦{meta['ccip']:.3f}⁩", f"⁦{meta['sharp']:.0f}⁩"
        info += (f"\n\nالقص: {TYPE_AR.get(meta['type'], meta['type'])} — الحلقة {ep} عند {at}"
                 f" — درجة التطابق {score} (الأقل أفضل) — الحدة {sharp}")
        if meta.get("upscaled", 1) > 1:
            info += f" — مُكبّرة ⁦×{meta['upscaled']:.1f}⁩"
    return str(f), caption, info


def stats_text(pname, char):
    files = list_files(pname, char, "all")
    if not char:
        return "اختر شخصية."
    root = sorted_root(pname, char)
    n_review = sum(is_review(root, Path(f)) for f in files)
    from . import negatives
    trash = root.parent / "_deleted"
    n_del = len(list(trash.rglob("*.png"))) if trash.exists() else 0
    n_rej = len(negatives.load(root.parent)[0])
    return (f"**{len(files)}** صورة — منها **{n_review}** للمراجعة — المحذوفة: {n_del}"
            + (f" — رُفضت كشخصية أخرى: {n_rej}" if n_rej else ""))


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
    return gr.update(choices=[(f"{FRAMING_AR[f]} · {VIEW_AR[v]}", f"{f}/{v}") for f in FRAMING_AR for v in VIEW_AR])


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
    """A bad image of the right character: removed, nothing is learned."""
    if not files:
        raise gr.Error("لا توجد صورة محددة")
    undo = _trash(pname, char, files, idx, undo, "delete")
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


def reject_image(pname, char, flt, files, idx, undo):
    """Another character: removed, and learned as a negative (negatives.py) - review points at the images that
    look like it, and every later build leaves such crops out."""
    from . import negatives
    if not files:
        raise gr.Error("لا توجد صورة محددة")
    if not negatives.reject(sorted_root(pname, char).parent, Path(files[idx]).stem):
        raise gr.Error("هذه الشخصية بُنيت بإصدار أقدم من البرنامج: أعد بناءها مرة واحدة ليتعلّم من الرفض. "
                       "أو احذف الصورة بزر «صورة سيئة».")
    undo = _trash(pname, char, files, idx, undo, "reject")
    alike = look_alikes(pname, char)
    n = sum(Path(f).stem in alike for f in list_files(pname, char, "all"))
    gr.Info(f"رُفضت كشخصية أخرى. {n} صورة باقية تشبه ما رفضته: اخترها من «🚫 تشبه ما رفضته» في قائمة العرض."
            if n else "رُفضت كشخصية أخرى، وسيستبعد البرنامج ما يشبهها في كل بناء قادم.")
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


def undo_delete(pname, char, flt, files, idx, undo):
    from . import negatives
    if not undo:
        raise gr.Error("لا يوجد حذف للتراجع عنه")
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
        raise gr.Error("اختر شخصية")
    char_dir = sorted_root(pname, char).parent
    n = len(negatives.load(char_dir)[0])
    negatives.clear(char_dir)
    gr.Info(f"نسي البرنامج {n} صورة مرفوضة. الصور نفسها تبقى في المحذوفات.")
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), filter_update(pname, char, flt))


def move_image(pname, char, flt, files, idx, target):
    if not files or not target:
        raise gr.Error("اختر صورة والمجلد المطلوب")
    _move_pair(Path(files[idx]), sorted_root(pname, char) / target)
    return review_outputs(pname, char, list_files(pname, char, flt), idx)


def save_caption(files, idx, caption):
    if not files:
        raise gr.Error("لا توجد صورة محددة")
    Path(files[idx]).with_suffix(".txt").write_text((caption or "").strip(), encoding="utf-8")
    gr.Info("تم حفظ الوصف")


# ---------- tab 4: bulk tag editor ----------

def char_dir_of(pname, char):
    return Project(safe_name(pname)).chars_dir / char


def _tag_state(pname, char, query=""):
    """-> table rows, status markdown, all tags"""
    from .tags import history_size, tag_counts
    if not pname or not char or not (char_dir_of(pname, char) / "sorted").exists():
        return [], "اختر شخصية مبنية.", []
    cnt, n = tag_counts(char_dir_of(pname, char))
    q = (query or "").strip().lower()
    rows = [[t, c, round(100 * c / max(n, 1), 1)] for t, c in cnt.most_common() if q in t.lower()]
    status = f"**{n}** وصف — **{len(cnt)}** وسم مختلف — تعديلات قابلة للتراجع: {history_size(char_dir_of(pname, char))}"
    outfits = outfits_of(pname, char)
    if outfits:
        status += "\n\n" + "\n".join(f"- 🧥 ⁦`{o['token']}`⁩: {', '.join(o['tags'])}" for o in outfits)
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
        raise gr.Error("اختر الشخصية")
    from .outfits import sync_tokens
    n = edit_tags(char_dir_of(pname, char), **kw)
    sync_tokens(Project(safe_name(pname)), char, kw.get("remove", ()), kw.get("replace"))
    gr.Info(f"عُدّل {n} وصف")
    return tag_view(pname, char, query)


def tag_remove(pname, char, selected, query):
    if not selected:
        raise gr.Error("اختر وسمًا أو أكثر من الجدول")
    return _tag_edit(pname, char, query, remove=selected)


def tag_replace(pname, char, selected, new_text, query):
    if not selected:
        raise gr.Error("اختر وسمًا أو أكثر من الجدول")
    return _tag_edit(pname, char, query, replace={t: new_text or "" for t in selected})


def tag_add(pname, char, add_text, query):
    from .tags import split_tags
    if not split_tags(add_text or ""):
        raise gr.Error("اكتب الوسم المراد إضافته")
    return _tag_edit(pname, char, query, add=split_tags(add_text))


def tag_undo(pname, char, query):
    from .tags import undo_last
    if not char:
        raise gr.Error("اختر الشخصية")
    from .outfits import resync_after_undo
    try:
        n = undo_last(char_dir_of(pname, char))
    except SystemExit:
        raise gr.Error("لا يوجد تعديل للتراجع عنه")
    resync_after_undo(Project(safe_name(pname)), char)
    gr.Info(f"استُرجع {n} وصف")
    return tag_view(pname, char, query)


def rerun_outfits(pname, char, query):
    from .outfits import run_outfits
    p = need_project(pname)
    if not char:
        raise gr.Error("اختر الشخصية")
    log = captured(run_outfits, p, char)
    return (*tag_view(pname, char, query), log)


# ---------- tab 5: save the result ----------
# Only three things: where the finished images + captions go, a summary of them, and deleting the project
# from the program folder once it's saved. (The CLI's `export` still has balancing and AI Toolkit configs.)

def save_target(pname, char, parent):
    """The folder the images go to: <chosen place>/<character>. Refuses places inside the projects folder,
    which deleting the project would take with it."""
    parent = (parent or "").strip().strip('"').strip("'")
    if not parent:
        raise gr.Error("اكتب أو الصق مسار المكان الذي تريد الحفظ فيه")
    parent = Path(parent)
    if not parent.is_absolute():
        raise gr.Error("اكتب المسار كاملًا، مثل D:\\datasets")
    out = (parent / char).resolve()
    if PROJECTS_DIR.resolve() in out.parents or out == PROJECTS_DIR.resolve():
        raise gr.Error("اختر مكانًا خارج مجلد مشاريع البرنامج، وإلا حُذفت الصور مع المشروع")
    return out


def save_summary(pname, char, parent):
    """-> (summary markdown, rows: shot, angle, count) of what saving will write."""
    from .export import group_of as export_group
    if not pname or not char:
        return "اختر شخصية.", []
    p = Project(safe_name(pname))
    root = sorted_root(pname, char)
    files = sorted(root.rglob("*.png")) if root.exists() else []
    if not files:
        return "لا توجد صور لهذه الشخصية. ابنِها أولًا (التبويب ٢).", []
    build = p.load(f"characters/{char}/build.json", {})
    n_review = sum(is_review(root, f) for f in files)
    alike = look_alikes(pname, char)
    n_alike = sum(f.stem in alike for f in files)
    n_txt = sum(f.with_suffix(".txt").exists() for f in files)
    upscaled = {Path(it["file"]).stem for it in build.get("items", []) if it.get("upscaled", 1) > 1}
    stems = {f.stem for f in files}
    num = lambda x: f"⁦{x}⁩"
    lines = [f"**سيُحفظ {num(len(files))} صورة** مع {num(n_txt)} ملف وصف (caption).",
             f"- كلمة التفعيل: ⁦`{build.get('name', char)}`⁩"
             + (f" — اسم الأنمي: ⁦`{build['series']}`⁩" if build.get("series") else "")]
    if upscaled & stems:
        lines.append(f"- مُكبّرة بنموذج الأنمي: {num(len(upscaled & stems))}")
    for o in build.get("outfits", []):
        n = sum(o["token"] in caption_tags(f) for f in files)
        lines.append(f"- زي {num(o['id'])} ⁦`{o['token']}`⁩: {num(n)} صورة ({', '.join(o['tags'][:3])})")
    if n_review:
        lines.append(f"- ⚠ **{num(n_review)} صورة ما زالت معلّمة للمراجعة**، وستُحفظ معها. راجعها أولًا في التبويب ٣.")
    if n_alike:
        lines.append(f"- 🚫 **{num(n_alike)} صورة تشبه صورة رفضتها كشخصية أخرى**. راجعها في التبويب ٣.")
    if n_txt < len(files):
        lines.append(f"- ⚠ {num(len(files) - n_txt)} صورة بلا ملف وصف.")
    try:
        lines.append(f"\n**مكان الحفظ:** ⁦`{save_target(pname, char, parent)}`⁩")
    except gr.Error:
        pass
    counts = Counter(export_group(root, f) for f in files)
    rows = []
    for g in sorted(counts, key=lambda g: -counts[g]):
        fr, vw = (g.split("/") + [""])[:2]
        rows.append([FRAMING_AR.get(fr, fr), VIEW_AR.get(vw, vw), counts[g]])
    rows.append(["المجموع", "", len(files)])
    return "\n".join(lines), rows


def do_save(pname, char, parent):
    from .aitk import MARKER, save_settings
    from .export import run_export
    p = need_project(pname)
    if not char:
        raise gr.Error("اختر الشخصية")
    out = save_target(pname, char, parent)
    if out.exists() and any(out.iterdir()) and not (out / MARKER).exists():
        raise gr.Error(f"يوجد مجلد بالاسم {out.name} في هذا المكان ولم يُنشئه البرنامج، فلن يُكتب فوقه. "
                       "اختر مكانًا آخر.")
    save_settings(save_dir=str(out.parent))
    log = captured(run_export, p, char, str(out), txn=txn.export_txn(p, char, out))
    proj = p.load("project.json", {"videos": []})
    proj.setdefault("saved", {})[char] = str(out)
    p.save("project.json", proj)
    return log


def delete_hint(pname):
    """What deleting the project would remove, and whether anything of it was saved elsewhere first."""
    from .cleanup import disk_usage, fmt_bytes
    if not pname or not Project(safe_name(pname)).dir.exists():
        return ""
    p = Project(safe_name(pname))
    size = fmt_bytes(sum(b for _, b in disk_usage(p)))
    saved = p.load("project.json", {}).get("saved", {})
    text = (f"يحذف مجلد المشروع **{p.name}** كله من مجلد البرنامج (⁦{size}⁩): الإطارات والشخصيات والتحليل "
            "المحفوظ. الحلقات الأصلية والصور التي حفظتها في مكان آخر لا تُمس.")
    if saved:
        text += "\n\nحُفظ منه: " + "، ".join(f"⁦`{c}`⁩ ← ⁦`{d}`⁩" for c, d in saved.items())
    else:
        text += "\n\n⚠ **لم تحفظ أي شخصية من هذا المشروع بعد.**"
    return text


def delete_project(pname, confirm):
    from .cleanup import disk_usage, fmt_bytes
    p = need_project(pname)
    if not p.dir.exists():
        raise gr.Error("المشروع غير موجود")
    if not confirm:
        raise gr.Error("فعّل خانة التأكيد أولًا: حذف المشروع نهائي")
    size = fmt_bytes(sum(b for _, b in disk_usage(p)))
    try:
        shutil.rmtree(p.dir)
    except OSError as e:
        raise gr.Error(f"تعذّر حذف بعض الملفات (ربما مفتوحة في برنامج آخر): {e}")
    left = projects()
    gr.Info(f"حُذف المشروع {p.name} وتحرّرت ⁦{size}⁩.")
    return gr.update(choices=left, value=left[0] if left else None), gr.update(value=False)


# ---------- layout ----------

def build_ui():
    import onnxruntime as ort
    from .aitk import load_settings
    gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    with gr.Blocks(title="animelora", analytics_enabled=False) as demo:
        gr.Markdown("## animelora — تجهيز صور LoRA لشخصية من حلقات الأنمي\n"
                    f"{'🟢 كرت الشاشة يعمل (CUDA)' if gpu else '🔴 يعمل على المعالج فقط (بطيء)'}")
        with gr.Row():
            project = gr.Dropdown(choices=projects(), value=(projects() or [None])[0], allow_custom_value=True,
                                  label="المشروع (اختر مشروعًا أو اكتب اسمًا جديدًا)", scale=4)
            refresh = gr.Button("🔄 تحديث", scale=1)

        with gr.Tabs() as tabs:
            # --- 1
            with gr.Tab("١. مسح الحلقات", id="scan"):
                gr.Markdown("الصق مسار حلقة في كل سطر، أو مسار مجلد كامل. "
                            "(في مستكشف ويندوز: Shift + زر الفأرة الأيمن على الملف ← Copy as path)")
                with gr.Row():
                    with gr.Column(scale=3):
                        videos = gr.Textbox(lines=4, label="الحلقات", elem_classes="ltr",
                                            placeholder="D:\\anime\\ep01.mkv\nD:\\anime\\Season 1")
                        auto = gr.Checkbox(True, label="اكتشاف الشارة (OP/ED) تلقائيًا: المقاطع المتكررة بين الحلقات "
                                                       "تُستبعد. مع حلقة واحدة تُستخدم الحلقة المجاورة في المجلد للمقارنة")
                        skip = gr.Textbox(label="أوقات إضافية تُتجاهل يدويًا (اختياري)", elem_classes="ltr",
                                          placeholder="0:00-1:55, 21:55-24:30")
                        with gr.Accordion("إعدادات متقدمة", open=False):
                            auto_min = gr.Slider(15, 120, 40, step=5,
                                                 label="أقل طول لمقطع متكرر حتى يُعدّ شارة (ثانية)")
                            autoskip_btn = gr.Button("أعد اكتشاف الشارة للحلقات الممسوحة")
                            stop_auto = gr.Button(STOP_LABEL, variant="stop", visible=False)
                            min_gap = gr.Slider(0.1, 2.0, 0.35, step=0.05, label="أقل فاصل بين إطارين محفوظين (ثانية)")
                            keep_diff = gr.Slider(1, 20, 5, step=0.5, label="مقدار التغيّر المطلوب لحفظ إطار جديد")
                        scan_btn = gr.Button("▶ ابدأ المسح", variant="primary")
                        stop_scan = gr.Button(STOP_LABEL, variant="stop", visible=False)
                    with gr.Column(scale=3):
                        vids_df = gr.Dataframe(headers=["#", "الحلقة", "المدة (دقيقة)", "إطارات", "مستبعد تلقائيًا"],
                                               interactive=False, wrap=True, label="الحلقات الممسوحة في المشروع",
                                               column_widths=["6%", "34%", "11%", "10%", "39%"])
                        with gr.Accordion("💾 المساحة على القرص", open=False):
                            usage = gr.Markdown()
                            clean_safe_btn = gr.Button("🧹 تنظيف آمن: حذف الإطارات التي لا يحتاجها البرنامج + المصغّرات")
                            gr.Markdown("**حذف كل الإطارات** يوفر أكثر، وتبقى الصور النهائية، "
                                        "لكن لا يمكن بعده البناء أو التجميع في هذا المشروع.")
                            clean_confirm = gr.Checkbox(label="أفهم أن هذا الحذف نهائي")
                            clean_all_btn = gr.Button("حذف كل الإطارات", variant="stop")
                scan_log = gr.Textbox(lines=12, label="السجل", elem_id="log", autoscroll=True)

            # --- 2
            with gr.Tab("٢. اختيار الشخصية", id="pick"):
                gr.Markdown("اضغط على صورة الشخصية لتحديدها، واضغط مرة أخرى لإلغاء التحديد. إن ظهرت الشخصية في أكثر "
                            "من مجموعة (زي مختلف مثلًا) فاختر كل مجموعاتها. **الأرقام تتغير بعد كل مسح.**")
                with gr.Row():
                    with gr.Column(scale=3):
                        clusters_gal = gr.Gallery(label="الشخصيات المكتشفة", columns=5, height=560,
                                                  allow_preview=False, object_fit="contain", buttons=[])
                        with gr.Accordion("إعادة التجميع (إن اختلطت شخصيتان أو انقسمت شخصية)", open=False):
                            cut = gr.Slider(0.10, 0.40, 0.20, step=0.01,
                                            label="مسافة الدمج: أقل = مجموعات أكثر وأصغر")
                            min_csize = gr.Slider(3, 40, 8, step=1, label="إخفاء المجموعات الأصغر من")
                            recluster_btn = gr.Button("أعد تجميع المشروع كله")
                            gr.Markdown("**أو قسّم مجموعة مختلطة وحدها:** حدّدها (واحدة فقط) ثم اضغط «قسّم». "
                                        "أرقام بقية المجموعات لا تتغير، والأجزاء الجديدة تأخذ أرقامًا في آخر القائمة.")
                            split_cut = gr.Slider(0.06, 0.19, 0.14, step=0.01,
                                                  label="شدة التقسيم: أقل = أجزاء أكثر")
                            split_btn = gr.Button("✂ قسّم المجموعة المحددة")
                            stop_clu = gr.Button(STOP_LABEL, variant="stop", visible=False)
                            recluster_log = gr.Textbox(lines=6, label="السجل", elem_id="log")
                    with gr.Column(scale=2):
                        chosen = gr.CheckboxGroup(label="المجموعات المختارة", choices=[])
                        sheet = gr.Image(label="معاينة المجموعة", interactive=False, height=320,
                                         buttons=["fullscreen"])
                        refs = gr.File(file_count="multiple", file_types=["image"], type="filepath", height=150,
                                       label="أو/و: صور مرجعية للشخصية (اختياري، مفيد للشخصيات الثانوية)")
                        name = gr.Textbox(label="كلمة التفعيل (اسم الشخصية)", elem_classes="ltr",
                                          placeholder="natsu_ft")
                        series = gr.Textbox(label="اسم الأنمي كوسم (اختياري)", elem_classes="ltr",
                                            placeholder="fairy tail")
                        upscale_on = gr.Checkbox(label="تكبير الصور الصغيرة بنموذج مخصص للأنمي (CDC): خطوط أوضح من "
                                                       "التكبير العادي، ويُنقذ القصّات الصغيرة")
                        upscale_to = gr.Slider(512, 1536, 1024, step=64, visible=False,
                                               label="كبّر كل صورة أصغر من هذا الحجم إليه (بكسل؛ اجعله بدقة التدريب)")
                        with gr.Accordion("إعدادات متقدمة", open=False):
                            threshold = gr.Slider(0.06, 0.25, 0.13, step=0.005,
                                                  label="حد التطابق: أقل = أدق وصور أقل، أعلى = صور أكثر وأخطاء أكثر")
                            sim = gr.Slider(0.60, 0.98, 0.80, step=0.01,
                                            label="حد التكرار: أقل = حذف تكرار أكثر")
                            min_size = gr.Slider(256, 1024, 448, step=32, label="أقل حجم للقصة (بكسل)")
                            relax = gr.Slider(1.0, 2.0, 1.0, step=0.05,
                                              label="تتبع اللقطة (1 = متوقف؛ قد يُدخل شخصيات خاطئة)")
                            tagger = gr.Dropdown(["EVA02_Large", "SwinV2_v3", "ConvNext_v3", "ViT_v3"],
                                                 value="EVA02_Large", label="نموذج الوسوم")
                            opts = gr.CheckboxGroup(BUILD_OPTIONS, value=["outfits", "screencap"], label="خيارات")
                        overwrite = gr.Checkbox(label="استبدال نتائج سابقة بنفس الاسم (يمسح مراجعتك السابقة)")
                        build_btn = gr.Button("▶ ابنِ مجموعة الصور", variant="primary")
                        stop_build = gr.Button(STOP_LABEL, variant="stop", visible=False)
                build_log = gr.Textbox(lines=14, label="التقرير", elem_id="log")

            # --- 3
            with gr.Tab("٣. المراجعة", id="review"):
                gr.Markdown("أزل كل صورة ليست للشخصية، وابدأ بالصور المعلّمة ⚠. "
                            "**N** (ليست الشخصية): لصورة شخصية أخرى، فيتعلّم منها البرنامج: يعلّم ما يشبهها بـ🚫 "
                            "ويستبعده في كل بناء قادم. **Delete**: لصورة سيئة للشخصية نفسها، ولا يتعلّم منها شيئًا. "
                            "**← →** للتنقل، و**Ctrl+Z** للتراجع.")
                with gr.Row():
                    r_char = gr.Dropdown(label="الشخصية", choices=[], scale=2)
                    r_filter = gr.Dropdown(label="عرض", choices=[("الكل", "all")], value="all", scale=2)
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
                            prev_btn = gr.Button("→ السابق", elem_id="btn-prev")
                            next_btn = gr.Button("التالي ←", elem_id="btn-next")
                        with gr.Row():
                            reject_btn = gr.Button("🚫 ليست الشخصية (N)", variant="stop", elem_id="btn-reject")
                            del_btn = gr.Button("🗑 صورة سيئة (Delete)", elem_id="btn-del")
                            undo_btn = gr.Button("↶ تراجع", elem_id="btn-undo")
                        r_caption = gr.Textbox(lines=4, label="الوصف (caption)", elem_classes="ltr")
                        save_btn = gr.Button("💾 حفظ الوصف")
                        with gr.Row():
                            move_to = gr.Dropdown(label="تصنيف خاطئ؟ انقلها إلى", choices=[], scale=3)
                            move_btn = gr.Button("↪ نقل", scale=1)
                        forget_btn = gr.Button("نسيان كل الصور المرفوضة كشخصية أخرى", size="sm")
                files_st, idx_st, undo_st = gr.State([]), gr.State(0), gr.State([])

            # --- 4
            with gr.Tab("٤. الوسوم", id="tags"):
                gr.Markdown("كل الوسوم في أوصاف الشخصية وعدد مرات ظهورها. اضغط على وسم في الجدول لتحديده، "
                            "ثم احذفه أو استبدله في **كل** الأوصاف دفعة واحدة. كل تعديل يمكن التراجع عنه.")
                with gr.Row():
                    with gr.Column(scale=3):
                        with gr.Row():
                            t_char = gr.Dropdown(label="الشخصية", choices=[], scale=2)
                            t_search = gr.Textbox(label="بحث", elem_classes="ltr", scale=2)
                        t_table = gr.Dataframe(headers=["الوسم", "العدد", "%"], interactive=False, max_height=620,
                                               column_widths=["70%", "15%", "15%"])
                    with gr.Column(scale=2):
                        t_status = gr.Markdown()
                        t_selected = gr.Dropdown(label="الوسوم المحددة", choices=[], multiselect=True,
                                                 allow_custom_value=True, elem_classes="ltr")
                        t_remove_btn = gr.Button("🗑 احذف المحدد من كل الأوصاف", variant="stop")
                        with gr.Row():
                            t_new = gr.Textbox(label="استبدل المحدد بـ (فارغ = حذف)", elem_classes="ltr", scale=3,
                                               placeholder="brown eyes")
                            t_replace_btn = gr.Button("↔ استبدل", scale=1)
                        with gr.Row():
                            t_add_text = gr.Textbox(label="أضف وسمًا لكل الأوصاف", elem_classes="ltr", scale=3)
                            t_add_btn = gr.Button("➕ أضف", scale=1)
                        t_undo_btn = gr.Button("↶ تراجع عن آخر تعديل (Ctrl+Z)", elem_id="btn-tag-undo")
                        gr.Markdown("**الأزياء:** بعد حذف صور في المراجعة أعد فصل الأزياء ليُحدَّث توزيعها.")
                        t_outfits_btn = gr.Button("🧥 أعد فصل الأزياء")
                        t_log = gr.Textbox(lines=4, label="السجل", elem_id="log")

            # --- 5
            with gr.Tab("٥. حفظ الناتج", id="export"):
                gr.Markdown("يحفظ الصور بعد المراجعة مع ملفات الوصف في مجلد باسم الشخصية داخل المكان الذي تختاره. "
                            "هذا المجلد هو مجموعة البيانات التي تدرّب عليها.")
                saved_dir = load_settings().get("save_dir", "")
                with gr.Row():
                    with gr.Column(scale=2):
                        e_char = gr.Dropdown(label="الشخصية", choices=[])
                        e_out = gr.Textbox(saved_dir, label="مكان الحفظ (الصق مسار مجلد؛ يُنشأ فيه مجلد باسم الشخصية)",
                                           elem_classes="ltr", placeholder="D:\\datasets")
                        export_btn = gr.Button("💾 احفظ الصور والأوصاف", variant="primary")
                        stop_export = gr.Button(STOP_LABEL, variant="stop", visible=False)
                        export_log = gr.Textbox(lines=6, label="السجل", elem_id="log")
                    with gr.Column(scale=2):
                        e_summary = gr.Markdown()
                        groups_df = gr.Dataframe(headers=["اللقطة", "الزاوية", "العدد"], interactive=False,
                                                 label="التوزيع")
                with gr.Accordion("🗑 حذف المشروع من مجلد البرنامج (بعد الحفظ)", open=False):
                    del_hint = gr.Markdown()
                    del_confirm = gr.Checkbox(label="أفهم أن حذف المشروع نهائي ولا يمكن التراجع عنه")
                    del_project_btn = gr.Button("🗑 احذف المشروع", variant="stop")

        # ---- events ----
        proj_outputs = [vids_df, clusters_gal, chosen, r_char, e_char, t_char, usage]
        project.change(load_project, project, proj_outputs)
        refresh.click(lambda p: (gr.update(choices=projects()), *load_project(p)), project, [project, *proj_outputs])
        def init_page(p):
            """The project list is read again on every page load (projects made after the server started)."""
            names = projects()
            p = p if p in names else (names[0] if names else p)
            return (gr.update(choices=names, value=p), *load_project(p))

        demo.load(init_page, project, [project, *proj_outputs])

        def long_action(btn, stop, fn, inputs, outputs):
            """btn shows `stop` while fn runs; fn's event is returned so .success() can chain on it."""
            ev = btn.click(start_ui, None, stop, queue=False).then(fn, inputs, outputs, concurrency_id="gpu")
            # Gradio 6's frontend fires .then() follow-ups only after success (despite its docs), and only
            # .failure() ones after an error - a stopped run ends in an error, so hide the button on both
            ev.then(end_ui, None, stop, queue=False)
            ev.failure(end_ui, None, stop, queue=False)
            return ev

        for stop in (stop_scan, stop_auto, stop_clu, stop_build, stop_export):
            stop.click(press_stop, None, stop, queue=False)

        long_action(scan_btn, stop_scan, do_scan, [project, videos, skip, auto, auto_min, min_gap, keep_diff],
                    [scan_log, project, *proj_outputs])
        long_action(autoskip_btn, stop_auto, do_autoskip, [project, auto, auto_min], [scan_log, *proj_outputs])
        long_action(recluster_btn, stop_clu, do_recluster, [project, cut, min_csize],
                    [recluster_log, clusters_gal, chosen])
        long_action(split_btn, stop_clu, do_split, [project, chosen, split_cut], [recluster_log, clusters_gal, chosen])
        clean_safe_btn.click(lambda p: do_clean(p, False, False), project, [scan_log, usage])
        clean_all_btn.click(lambda p, c: do_clean(p, True, c), [project, clean_confirm], [scan_log, usage])
        clusters_gal.select(pick_cluster, [project, chosen], [chosen, sheet])
        # upscaling makes small crops usable, so allow smaller ones in when it's switched on
        upscale_on.change(lambda on: (gr.update(visible=on), gr.update(value=320 if on else 448)),
                          upscale_on, [upscale_to, min_size])
        long_action(build_btn, stop_build, do_build,
                    [project, chosen, refs, name, series, upscale_on, upscale_to, threshold, min_size, sim, relax,
                     tagger, opts, overwrite],
                    [build_log, r_char, e_char, t_char, tabs]) \
            .success(change_char, [project, r_char],
                     [r_filter, move_to, r_gal, r_img, r_caption, r_info, files_st, idx_st, r_stats])

        rv_out = [r_gal, r_img, r_caption, r_info, files_st, idx_st, r_stats]
        r_char.change(change_char, [project, r_char], [r_filter, move_to, *rv_out])
        r_filter.change(load_review, [project, r_char, r_filter], rv_out)
        r_gal.select(select_image, [project, r_char, files_st], rv_out)
        prev_btn.click(step(-1), [project, r_char, files_st, idx_st], rv_out)
        next_btn.click(step(+1), [project, r_char, files_st, idx_st], rv_out)
        trash_in = [project, r_char, r_filter, files_st, idx_st, undo_st]
        del_btn.click(delete_image, trash_in, [*rv_out, undo_st, r_filter])
        reject_btn.click(reject_image, trash_in, [*rv_out, undo_st, r_filter])
        undo_btn.click(undo_delete, trash_in, [*rv_out, undo_st, r_filter])
        forget_btn.click(forget_rejected, [project, r_char, r_filter, files_st, idx_st], [*rv_out, r_filter])
        move_btn.click(move_image, [project, r_char, r_filter, files_st, idx_st, move_to], rv_out)
        save_btn.click(save_caption, [files_st, idx_st, r_caption], None)

        t_out = [t_table, t_status, t_selected]
        t_char.change(tag_view, [project, t_char, t_search], t_out)
        t_search.change(tag_view, [project, t_char, t_search], t_out)
        t_table.select(pick_tag, t_selected, t_selected)
        t_remove_btn.click(tag_remove, [project, t_char, t_selected, t_search], t_out)
        t_replace_btn.click(tag_replace, [project, t_char, t_selected, t_new, t_search], t_out)
        t_add_btn.click(tag_add, [project, t_char, t_add_text, t_search], t_out)
        t_undo_btn.click(tag_undo, [project, t_char, t_search], t_out)
        t_outfits_btn.click(rerun_outfits, [project, t_char, t_search], [*t_out, t_log])

        sum_in, sum_out = [project, e_char, e_out], [e_summary, groups_df]
        e_char.change(save_summary, sum_in, sum_out)
        e_out.change(save_summary, sum_in, sum_out)
        tabs.select(save_summary, sum_in, sum_out)
        tabs.select(delete_hint, project, del_hint)
        project.change(delete_hint, project, del_hint)
        tabs.select(tag_view, [project, t_char, t_search], t_out)
        long_action(export_btn, stop_export, do_save, [project, e_char, e_out], [export_log]) \
            .success(delete_hint, project, del_hint)
        del_project_btn.click(delete_project, [project, del_confirm], [project, del_confirm])
    return demo


def launch(port=7860, open_browser=True):
    from .common import setup_runtime
    setup_runtime()
    PROJECTS_DIR.mkdir(exist_ok=True)
    demo = build_ui()
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=port, inbrowser=open_browser,
        allowed_paths=[str(PROJECTS_DIR)], theme=gr.themes.Soft(), css=CSS, head=HEAD)
