import contextlib
import contextvars
import functools
import io
import json
import os
import re
import shutil
import sys
import threading
from collections import Counter
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr
import pandas as pd
from PIL import Image

from . import cancel, txn
from .cancel import Cancelled
from .common import (DEFAULT_MIN_HEIGHT, FRAMING, OWN_IMAGES, PROJECTS_DIR, VIDEO_EXTS, VIEW, Project, inside,
                     mmss, parse_ranges, release_models, safe_name)
from .upscale import DEFAULT as DEFAULT_UPSCALER, LABELS as UPSCALERS
from .i18n import AR, LANGS, lang, t, use


def ltr(text) -> str:
    return f"\u2066{text}\u2069"


CROP = {"full": "Whole character", "half": "Upper body", "head": "Head"}


def shot_name(key):
    return t(FRAMING[key]) if key in FRAMING else key


def angle_name(key):
    return t(VIEW[key]) if key in VIEW else key


def upscaler_choices():
    return [(t(label), key) for key, label in UPSCALERS.items()]


def model_version_choices():
    return [(t("Automatic (recommended)"), "auto"), ("2x", "2"), ("4x", "4")]


def model_versions(model, version):
    from .upscale import versions
    both = len(versions(model)) > 1
    return gr.update(visible=both, value=version if both else "auto")


def model_info_json():
    from .upscale import INFO
    return json.dumps({key: {"en": [label, INFO[key]], "ar": [AR.get(label, label), AR.get(INFO[key], INFO[key])]}
                       for key, label in UPSCALERS.items()}, ensure_ascii=False)


def model_status(model, version="auto"):
    from .upscale import downloaded_size, megabytes, size_mb, versions
    if not model:
        return ""
    if version != "auto" and int(version) not in versions(model):
        version = "auto"
    size = downloaded_size(model, version)
    name = t(UPSCALERS[model]) + ("" if version == "auto" else f" · {version}x")
    if size:
        return t("✅ {name} is downloaded ({size} MB).", name=name, size=megabytes(size))
    return t("⬇ {name} isn't downloaded yet ({size} MB). It's downloaded when you choose it.",
             name=name, size=size_mb(model, version))


def do_model(upscale_on, model, version="auto", progress=gr.Progress()):
    from .upscale import download, downloaded_size, versions
    if not upscale_on or not model:
        return gr.update(), gr.update()
    if version != "auto" and int(version) not in versions(model):
        version = "auto"
    if not downloaded_size(model, version):
        progress(0.5, desc=t("Downloading {name}...", name=t(UPSCALERS[model])))
        try:
            download(model, version)
        except Cancelled:
            raise
        except Exception:
            raise gr.Error(t("Couldn't download {name}. Check the internet connection and try again.",
                             name=t(UPSCALERS[model])))
    return model_status(model, version), gr.update(visible=True)


def model_view(upscale_on, model, version="auto"):
    from .upscale import downloaded_size, versions
    if not upscale_on or not model:
        return "", gr.update(visible=False)
    if version != "auto" and int(version) not in versions(model):
        version = "auto"
    return model_status(model, version), gr.update(visible=bool(downloaded_size(model, version)))


def delete_model(model, version="auto"):
    from .upscale import delete, megabytes
    if not model:
        raise gr.Error(t("Pick a model"))
    freed = delete(model)
    gr.Info(t("Deleted {name} and freed {size} MB. It's downloaded again when you choose it.",
              name=t(UPSCALERS[model]), size=megabytes(freed)))
    return model_status(model, version), gr.update(visible=False)


def build_options():
    return [(t("Leave out other characters, using the clusters you didn't pick"), "auto_reject"),
            (t("Separate outfits automatically (a tag per outfit after the trigger word)"), "outfits"),
            (t("Put anime screencap at the start of every caption"), "screencap"),
            (t("Keep images with text on screen"), "keep_text"),
            (t("Keep chibi and blurry drawings"), "keep_offmodel"),
            (t("Keep black-and-white and sepia images (flashbacks)"), "keep_mono"),
            (t("Save the left-out images in a {folder} folder", folder="_dropped"), "save_dropped"),
            (t("Analyse from scratch, ignore the saved analysis (much slower, rarely needed)"), "fresh")]


CSS = """
html[dir="rtl"] .gradio-container, html[dir="rtl"] .gradio-container [dir="ltr"] { direction: rtl; }
html[dir="rtl"] .gradio-container .body-cell, html[dir="rtl"] .gradio-container .body-cell .text { text-align: right; }
.gradio-container .body-cell .text, .gradio-container .caption-label { unicode-bidi: plaintext; }
.tag-choices label span { unicode-bidi: plaintext; }
.slider_input_container, input[type=range] { direction: ltr; }
.ltr textarea, .ltr input { direction: ltr !important; text-align: left !important; }
.log textarea { unicode-bidi: plaintext; text-align: start; font-size: 13px; line-height: 1.7; }
.busy .progress-level-inner { margin: 0 0 6px !important; font-family: inherit !important; font-size: 14px !important;
  unicode-bidi: plaintext; }
.busy .progress-bar-wrap { width: 100% !important; height: 10px !important; border-radius: 5px; overflow: hidden; }
.busy .progress-text { position: static !important; transform: none !important; order: 2; padding: 4px 0 0 !important;
  font-family: inherit !important; }
.gradio-container table, .gradio-container table .text { font-family: var(--font) !important; }
html[dir="rtl"] .gradio-container .wrap-inner .icon-wrap { right: auto; left: var(--size-5); }
.gradio-container .wrap-inner input[role="combobox"] { padding-inline-end: var(--size-6); }
#preview img { object-fit: contain; }
.file-preview .filename, .file-preview .download { direction: ltr; unicode-bidi: isolate; }
#top-bar, .inline-row { align-items: flex-end; }
#review-gallery { position: relative; }
#review-gallery button.thumbnail-item[data-picked] { outline: 3px solid var(--color-accent); outline-offset: -3px; }
#review-gallery button.thumbnail-item[data-picked]::after { content: "✓"; position: absolute; top: 6px;
  inset-inline-start: 6px; width: 22px; height: 22px; border-radius: 50%; background: var(--color-accent);
  color: #fff; font-size: 14px; line-height: 22px; text-align: center; }
#picked-badge { position: absolute; top: 8px; inset-inline-end: 12px; z-index: 5; padding: 4px 12px;
  border-radius: 999px; background: var(--color-accent); color: #fff; font-size: 13px; pointer-events: none;
  display: none; }
#top-bar > button, .inline-row > button { align-self: flex-end; min-height: 42px; }
#upscaler-models label { align-items: center; }
.model-info { margin-inline-start: 8px; width: 22px; height: 22px; flex: none; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-secondary);
  color: var(--body-text-color); font-weight: 700; line-height: 20px; padding: 0; }
.model-info:hover { border-color: var(--color-accent); color: var(--color-accent); }
#model-info-dialog { max-width: min(520px, 90vw); padding: 18px 20px; border-radius: 10px;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-primary);
  color: var(--body-text-color); }
#model-info-dialog::backdrop { background: rgba(0, 0, 0, 0.45); }
#model-info-dialog h3 { margin: 0 0 8px; font-size: 17px; }
#model-info-dialog p { margin: 0 0 14px; line-height: 1.7; }
#model-info-dialog button { padding: 4px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-secondary);
  color: var(--body-text-color); }
.toast-title, .wrap.default > span.error { font-size: 0; }
.toast-title::before, .wrap.default > span.error::before { font-size: 16px; }
""" + "".join(f'html[lang="{lang}"] .toast-title.{kind}::before, html[lang="{lang}"] .wrap.default > span.{kind}::before '
              f'{{ content: "{text}"; }}\n'
              for kind, word in (("error", "Error"), ("warning", "Warning"), ("info", "Info"))
              for lang, text in (("en", word), ("ar", AR[word])))

TAKE_PICKED = "(...args) => { args[args.length - 1] = window.aldsTakePicked ? window.aldsTakePicked() : ''; return args; }"

HEAD = """<script>
window.aldsLang = (l) => {
  document.documentElement.lang = l;
  document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
  try { localStorage.setItem('alds-lang', l); } catch (e) {}
};
let storedLang = null;
try { storedLang = localStorage.getItem('alds-lang'); } catch (e) {}
window.aldsLang(storedLang || '__LANG__');
window.aldsSwitch = (v) => {
  const d = JSON.parse(v);
  window.aldsLang(d.lang);
  const names = new Map();
  for (const [en, ar] of d.tabs) {
    const name = d.lang === 'ar' ? ar : en;
    names.set(en, name);
    names.set(ar, name);
  }
  document.querySelectorAll('button').forEach((b) => b.childNodes.forEach((n) => {
    const key = n.nodeType === 3 ? n.nodeValue.trim() : null;
    if (key && names.has(key)) n.nodeValue = names.get(key);
  }));
};
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'textarea' || tag === 'input') return;
  const gallery = document.getElementById('review-gallery');
  if (gallery && gallery.offsetParent !== null) {
    if (e.key === 'Escape' && window.aldsPicked.size) { window.aldsPicked.clear(); aldsMark(); e.preventDefault(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
      aldsThumbs().forEach((b) => window.aldsPicked.add(aldsStem(b)));
      aldsMark();
      e.preventDefault();
      return;
    }
  }
  const click = (id) => { const b = document.getElementById(id); if (b && b.offsetParent !== null) { b.click(); e.preventDefault(); } };
  const rtl = document.documentElement.dir === 'rtl';
  if (e.key === 'Delete') click('btn-del');
  else if (e.code === 'KeyN' && !e.ctrlKey && !e.metaKey && !e.altKey) click('btn-reject');
  else if (e.key === 'ArrowLeft') click(rtl ? 'btn-next' : 'btn-prev');
  else if (e.key === 'ArrowRight') click(rtl ? 'btn-prev' : 'btn-next');
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { click('btn-undo'); click('btn-tag-undo'); }
});
window.aldsModelInfo = __MODEL_INFO__;
const aldsShowModel = (key) => {
  const info = window.aldsModelInfo[key];
  if (!info) return;
  const lang = document.documentElement.lang === 'ar' ? 'ar' : 'en';
  let d = document.getElementById('model-info-dialog');
  if (!d) {
    d = document.createElement('dialog');
    d.id = 'model-info-dialog';
    d.append(document.createElement('h3'), document.createElement('p'), document.createElement('button'));
    d.querySelector('button').type = 'button';
    d.querySelector('button').addEventListener('click', () => d.close());
    d.addEventListener('click', (e) => { if (e.target === d) d.close(); });
    document.body.appendChild(d);
  }
  d.dir = document.documentElement.dir;
  d.querySelector('h3').textContent = info[lang][0];
  d.querySelector('p').textContent = info[lang][1];
  d.querySelector('button').textContent = lang === 'ar' ? 'إغلاق' : 'Close';
  d.showModal();
};
const aldsDecorateModels = () => {
  const box = document.getElementById('upscaler-models');
  if (!box) return;
  box.querySelectorAll('input[type=radio]').forEach((input) => {
    const label = input.closest('label');
    if (!label || label.querySelector('.model-info')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'model-info';
    b.textContent = '!';
    b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); aldsShowModel(input.value); });
    label.appendChild(b);
  });
};
window.aldsPicked = new Set();
let aldsAnchor = null;
const aldsThumbs = () => {
  const g = document.getElementById('review-gallery');
  return g ? [...g.querySelectorAll('button.thumbnail-item')] : [];
};
const aldsStem = (b) => {
  const img = b.querySelector('img');
  const src = (img ? decodeURIComponent(img.getAttribute('src') || '') : '').replaceAll(String.fromCharCode(92), '/');
  return src.split(/[/=]/).pop().replace(/[.][^.]*$/, '');
};
const aldsMark = () => {
  const thumbs = aldsThumbs();
  const shown = new Set();
  thumbs.forEach((b) => {
    const s = aldsStem(b);
    shown.add(s);
    if (window.aldsPicked.has(s)) { if (!b.hasAttribute('data-picked')) b.setAttribute('data-picked', ''); }
    else if (b.hasAttribute('data-picked')) b.removeAttribute('data-picked');
  });
  if (thumbs.length) for (const s of [...window.aldsPicked]) if (!shown.has(s)) window.aldsPicked.delete(s);
  const g = document.getElementById('review-gallery');
  if (!g) return;
  let badge = document.getElementById('picked-badge');
  if (!badge) { badge = document.createElement('div'); badge.id = 'picked-badge'; g.appendChild(badge); }
  const n = window.aldsPicked.size;
  const text = !n ? '' : document.documentElement.lang === 'ar'
    ? `${n} صورة محددة · Esc يلغي التحديد` : `${n} selected · Esc clears`;
  if (badge.textContent !== text) badge.textContent = text;
  const display = n ? 'block' : 'none';
  if (badge.style.display !== display) badge.style.display = display;
};
window.aldsTakePicked = () => {
  const value = JSON.stringify([...window.aldsPicked]);
  window.aldsPicked.clear();
  aldsAnchor = null;
  aldsMark();
  return value;
};
document.addEventListener('click', (e) => {
  const b = e.target.closest ? e.target.closest('#review-gallery button.thumbnail-item') : null;
  if (!b) return;
  const thumbs = aldsThumbs();
  const i = thumbs.indexOf(b);
  if (!(e.ctrlKey || e.metaKey || e.shiftKey)) {
    window.aldsPicked.clear();
    aldsAnchor = i;
    aldsMark();
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  const current = thumbs.findIndex((x) => x.classList.contains('selected'));
  if (!window.aldsPicked.size && current >= 0) window.aldsPicked.add(aldsStem(thumbs[current]));
  if (e.shiftKey) {
    const from = aldsAnchor !== null ? aldsAnchor : Math.max(current, 0);
    for (let k = Math.min(from, i); k <= Math.max(from, i); k++) window.aldsPicked.add(aldsStem(thumbs[k]));
  } else {
    const s = aldsStem(b);
    if (window.aldsPicked.has(s)) window.aldsPicked.delete(s); else window.aldsPicked.add(s);
    aldsAnchor = i;
  }
  aldsMark();
}, true);
new MutationObserver(() => { aldsDecorateModels(); aldsMark(); }).observe(document.documentElement, {childList: true, subtree: true});
document.addEventListener('click', (e) => {
  const zone = e.target.closest ? e.target.closest('#episode-drop') : null;
  const browse = document.getElementById('episode-browse');
  if (!zone || !browse || e.target.closest('[data-testid="block-label"]')) return;
  e.preventDefault();
  e.stopPropagation();
  browse.click();
}, true);
</script>"""

VIDEO_COLUMNS = ["#", "Episode", "Length (min)", "Frames", "Left out automatically"]
TAG_COLUMNS = ["Tag", "Count", "%"]
GOAL_ICONS = {"hair_colour": "🎨", "hair_length": "📏", "hairstyle": "💇", "hair_accessory": "🎀", "eyes": "👁",
              "marks": "🖋", "piercing": "💎", "makeup": "💄", "body": "🧍", "clothing": "👕", "style": "🖌"}
CATEGORY_NAMES = {"hair_colour": "hair colour", "hair_length": "hair length", "hairstyle": "haircut and hairstyle",
                  "hair_accessory": "hair ties and accessories", "eyes": "eyes and eyebrows",
                  "marks": "tattoos, scars and marks", "piercing": "earrings and piercings", "makeup": "makeup and nails",
                  "body": "body", "clothing": "clothes and accessories", "style": "drawing style"}
GROUP_COLUMNS = ["Shot", "Angle", "Count"]
_session_langs = {}


def saved_lang():
    from .aitk import load_settings
    return load_settings().get("ui_lang", "ar")


def _session():
    from gradio.context import LocalContext
    return getattr(LocalContext.request.get(None), "session_hash", None)


def session_lang():
    return _session_langs.get(_session()) or saved_lang()


def localized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with use(session_lang()):
            return fn(*args, **kwargs)
    return wrapper


_log_to = contextvars.ContextVar("alds_log", default=None)


class LogBuffer(io.StringIO):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent

    def write(self, text):
        if self.parent is not None:
            self.parent.write(text)
        return super().write(text)


class RoutedOutput:
    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        target = _log_to.get()
        return (self.stream if target is None else target).write(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def route_output():
    if not isinstance(sys.stdout, RoutedOutput):
        sys.stdout = RoutedOutput(sys.stdout)


def streamed(fn, log_at, n_outputs):
    def partial(text):
        return text if n_outputs == 1 else tuple(text if i == log_at else gr.skip() for i in range(n_outputs))

    @functools.wraps(fn)
    def run(*args, **kwargs):
        with use(session_lang()):
            context = contextvars.copy_context()
        log, done = LogBuffer(), {}

        def work():
            _log_to.set(log)
            try:
                done["value"] = fn(*args, **kwargs)
            except BaseException as e:
                done["error"] = e
            finally:
                release_models()

        route_output()
        worker = threading.Thread(target=context.run, args=(work,), daemon=True)
        worker.start()
        shown = ""
        try:
            while worker.is_alive():
                worker.join(0.3)
                if log_at is not None and log.getvalue() != shown:
                    shown = log.getvalue()
                    yield partial(shown)
        finally:
            if worker.is_alive():
                cancel.request()
                worker.join()
        if "error" in done:
            if log_at is not None and log.getvalue() != shown:
                yield partial(log.getvalue())
            raise done["error"]
        yield done["value"]
    return run


def translated(text):
    if callable(text):
        return text()
    if isinstance(text, list):
        return [t(x) if x in AR else x for x in text]
    return t(text)


def table(rows, columns):
    return pd.DataFrame(rows, columns=translated(columns))


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
               ("no matches", "The character wasn't found. Raise “Match threshold” a little or pick other clusters"),
               ("no characters detected", "No characters were found in the episodes"),
               ("nothing scanned yet", "Scan at least one episode first (tab 1)"),
               ("no clusters yet", "Scan at least one episode first (tab 1)"),
               ("does not exist", "That cluster number doesn't exist. Numbers change after every scan, refresh "
                                  "the page"),
               ("no images in", "There are no images in the uploaded references"),
               ("not enough clear", "Not enough clear views to cluster"),
               ("were deleted to save space", "Restore this project's frames before building again: tab 5, "
                                              "“🧰 Project upkeep”."),
               ("didn't split", "The cluster didn't split this strongly, lower “Split strength”"),
               ("too small to split", "The cluster is too small to split")]


def gui_error(e: SystemExit):
    msg = str(e) or "failed"
    if msg in AR:
        return gr.Error(t(msg))
    hint = next((h for key, h in ERROR_HINTS if key in msg), None)
    return gr.Error(f"{t(hint)}\n\n{ltr(msg)}" if hint else ltr(msg))


def captured_result(fn, *args, txn=None):
    route_output()
    buf = LogBuffer(_log_to.get())
    token = _log_to.set(buf)
    try:
        with txn or contextlib.nullcontext():
            result = fn(*args)
    except Cancelled:
        cancel.reset()
        raise gr.Error(t("Stopped: everything it generated was removed, the project is back as it was."),
                       title=t("⏹ Stopped"))
    except SystemExit as e:
        raise gui_error(e)
    finally:
        _log_to.reset(token)
    return buf.getvalue(), result


def captured(fn, *args, txn=None):
    return captured_result(fn, *args, txn=txn)[0]


_busy = set()


@contextlib.contextmanager
def working_on(folder):
    folder = Path(folder).resolve()
    _busy.add(folder)
    try:
        yield
    finally:
        _busy.discard(folder)


def is_busy(path):
    path = Path(path).resolve()
    return any(path.is_relative_to(folder) for folder in tuple(_busy))


BUSY = "This character is being rebuilt, restored or saved. Try again when it finishes."


def guarded(fn):
    @functools.wraps(fn)
    def run(pname, char, *args, **kwargs):
        if pname and char and is_busy(char_dir_of(pname, char)):
            raise gr.Error(t(BUSY))
        return fn(pname, char, *args, **kwargs)
    return run


def stop_label():
    return t("⏹ Stop and remove what it made")


def start_ui():
    cancel.reset()
    return gr.update(visible=True, value=stop_label(), interactive=True), gr.update(visible=True)


def end_ui():
    return gr.update(visible=False), gr.update(visible=False)


def running():
    return (gr.Markdown(visible=False, min_height=72, elem_classes="busy"),
            gr.Button(stop_label(), variant="stop", visible=False))


def press_stop():
    cancel.request()
    return gr.update(value=t("⏳ Stopping and undoing..."), interactive=False)


def videos_table(pname):
    proj = Project(safe_name(pname)).load("project.json", {"videos": []}) if pname else {"videos": []}
    rows = []
    for v in proj["videos"]:
        segs = " | ".join(f"{lab} {mmss(s)}–{mmss(e)}" for s, e, lab in v.get("auto_skip", []))
        segs = ltr(segs) if segs else "—"
        rows.append([v["id"], v["name"], round(v.get("duration", 0) / 60, 1), v.get("kept_frames", 0), segs])
    return table(rows, VIDEO_COLUMNS)


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
            gr.update(choices=chars, value=first), usage_md(pname))


def episode_label(path):
    from .pick import EPISODES, videos_in
    p = Path(path)
    if p.is_dir():
        return f"📁 {p.name or p} ({len(videos_in(p))})"
    if not p.is_file():
        return f"⚠ {p.name or p}"
    return ("📥 " if p.parent.name == EPISODES and inside(p, PROJECTS_DIR) else "") + p.name


def episodes_update(paths):
    paths = list(dict.fromkeys(str(p).strip().strip('"').strip("'") for p in paths or [] if str(p).strip()))
    return gr.update(choices=[(episode_label(p), p) for p in paths], value=paths)


def ask_dialog(choose, title, start):
    try:
        return choose(title, start)
    except Exception:
        raise gr.Error(t("The Windows file window couldn't open. Drop the files on the box instead, or paste the "
                         "path."))


def browse_episodes(current, folder=False):
    from .aitk import load_settings, save_settings
    from .pick import choose_folder, choose_videos
    found = ask_dialog(choose_folder if folder else choose_videos,
                       t("Choose a folder of episodes") if folder else t("Choose episodes"),
                       load_settings().get("episodes_dir"))
    if not found:
        return gr.skip()
    save_settings(episodes_dir=found[0] if folder else str(Path(found[0]).parent))
    return episodes_update(list(current or []) + found)


def browse_episode_folder(current):
    return browse_episodes(current, folder=True)


def drop_episodes(pname, current, uploads, progress=gr.Progress()):
    from .cleanup import fmt_bytes
    from .pick import adopt_dropped, is_video
    if not uploads:
        return gr.skip(), gr.skip()
    p = need_project(pname)
    videos = [f for f in uploads if is_video(f)]
    if not videos:
        raise gr.Error(t("Only video files can be scanned ({types}).", types=", ".join(sorted(VIDEO_EXTS))))
    progress(0.5, desc=t("Looking for the original files on the disk..."))
    adopted = adopt_dropped(p.dir, videos)
    copies = [path for path, found in adopted if not found]
    if copies:
        gr.Info(t("{n} dropped episodes weren't found on the disk, so a copy is kept in the project ({size}). "
                  "“📂 Choose episodes” uses them where they are, without a copy.", n=len(copies),
                  size=fmt_bytes(sum(c.stat().st_size for c in copies))))
    return episodes_update(list(current or []) + [str(path) for path, _ in adopted]), None


def do_scan(pname, videos, skip_text, auto, auto_min, min_gap, keep_diff,
            progress=gr.Progress(track_tqdm=True)):
    from .scan import run_scan
    p = need_project(pname)
    paths = [str(v).strip().strip('"').strip("'") for v in videos or [] if str(v).strip()]
    if not paths:
        raise gr.Error(t("Choose or drop at least one episode, or a folder of episodes"))
    try:
        text = re.sub(r"\s*-\s*", "-", (skip_text or "").strip())
        skip = parse_ranges([s for s in re.split(r"[,\s]+", text) if s])
    except ValueError:
        raise gr.Error(t("The times to skip aren't valid. Example: 0:00-1:55, 21:55-24:30"))
    progress(0, desc=t("Starting the scan..."))
    log = captured(run_scan, p, paths, skip, min_gap, keep_diff, auto, auto_min, txn=txn.scan_txn(p))
    return (log, gr.update(choices=projects()), *load_project(p.name), episodes_update([]),
            gr.Tabs(selected="pick"))


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
         "cache": "Saved analysis for rebuilds", "previews": "Build previews", "episodes": "Copies of dropped episodes"}


def usage_md(pname):
    from .cleanup import disk_usage, fmt_bytes
    if not pname or not Project(safe_name(pname)).dir.exists():
        return ""
    p = Project(safe_name(pname))
    rows = [(l, b) for l, b in disk_usage(p) if b]
    gone = p.load("project.json", {}).get("frames_deleted")
    part = lambda l: t(USAGE[l]) if l in USAGE else t("Character {name}", name=l.replace("characters/", ""))
    lines = [t("**Project size: {size}**", size=fmt_bytes(sum(b for _, b in rows)))
             + (t(" — restore frames before building again") if gone else ""), "",
             t("| Part | Size |"), "|---|---|"]
    lines += [f"| {part(l)} | {ltr(fmt_bytes(b))} |" for l, b in rows]
    return "\n".join(lines)


def do_clean(pname, all_frames, confirm):
    from .cleanup import clean
    p = need_project(pname)
    if all_frames and not confirm:
        raise gr.Error(t("Confirm deleting the frames. The original episodes are needed to restore them."))
    with working_on(p.dir):
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


def own_files_of(pname, name):
    from .pick import image_files
    name = (name or "").strip()
    if not pname or not name:
        return []
    return [str(f) for f in image_files(Project(safe_name(pname)).char_dir(name) / OWN_IMAGES)]


def name_note(pname, name):
    name = (name or "").strip()
    if not pname or not name or not (Project(safe_name(pname)).char_dir(name) / "sorted").exists():
        return ""
    return t("🔁 **{name}** is already built. Building again saves the current result as a version first, and your "
             "review carries over.", name=name)


def name_changed(pname, name, files, loaded):
    existing = own_files_of(pname, name)
    names = [Path(f).name for f in existing]
    added = [f for f in files or [] if Path(f).name not in set(loaded or []) and Path(f).name not in set(names)]
    value = existing + added
    same = [Path(f).name for f in value] == [Path(f).name for f in files or []]
    return gr.skip() if same else gr.update(value=value or None), names, name_note(pname, name)


def scanned(p: Project):
    return (p.scan_dir / "detections.json").exists()


def char_setup(pname, char):
    build = Project(safe_name(pname)).load(f"characters/{char}/build.json") if pname and char else None
    if not build:
        return tuple(gr.skip() for _ in range(15))
    p = Project(safe_name(pname))
    s = build.get("settings", {})
    clusters = p.load("scan/clusters.json")
    ids = {c["id"] for c in clusters["clusters"]} if clusters else set()
    still_valid = (clusters and set(build.get("clusters", [])) <= ids
                   and p.path("scan/clusters.json").stat().st_mtime <= p.path(f"characters/{char}/build.json").stat().st_mtime)
    chosen = [f"#{i}" for i in sorted(build.get("clusters", []))] if still_valid else []
    opts = [key for key in ("auto_reject", "outfits", "screencap", "keep_text", "keep_offmodel", "keep_mono")
            if s.get(key, key in ("auto_reject", "outfits", "screencap"))]
    upscaler = s.get("upscaler") or DEFAULT_UPSCALER
    version = s.get("upscale_version") or "auto"
    from .upscale import versions
    return (build.get("name", char), build.get("series") or "", gr.update(value=chosen),
            s.get("own_in_set", True), s.get("own_refs", True), bool(s.get("upscale_to")),
            upscaler if upscaler in UPSCALERS else DEFAULT_UPSCALER,
            gr.update(value=version, visible=len(versions(upscaler)) > 1) if upscaler in UPSCALERS else gr.skip(),
            s.get("upscale_to") or 1024, s.get("threshold", 0.13),
            round(100 * s.get("min_height", DEFAULT_MIN_HEIGHT)), s.get("sim", 0.80), s.get("relax", 1.0),
            s.get("tagger", "EVA02_Large"), opts)


def do_build(pname, selected, own_files, own_in_set, own_refs, name, series, upscale_on, upscaler, upscale_version,
             upscale_to, threshold, min_height, sim, relax, tagger, opts, progress=gr.Progress(track_tqdm=True), *,
             preview=False):
    from .build import run_build
    from .pick import sync_images
    p = need_project(pname)
    name = (name or "").strip()
    if not name:
        raise gr.Error(t("Type the trigger word (the character's name)"))
    ids = sorted(int(s.lstrip("#")) for s in selected or [])
    own_files = list(own_files or [])
    use_refs = bool(own_files) and own_refs and scanned(p)
    if preview and not ids and not use_refs:
        raise gr.Error(t("Pick at least one cluster to preview. Your own images can help too, with “Use them to "
                         "find the character in the episodes” ticked."))
    if not ids and not use_refs and not (own_files and own_in_set):
        raise gr.Error(t("Pick at least one cluster of images, or add your own images of the character"))
    own_dir = (p.preview_dir(name) if preview else p.char_dir(name)) / OWN_IMAGES
    opts = set(opts or [])

    def run():
        sync_images(own_dir, own_files if not preview or use_refs else [])
        return run_build(p, name, ids, None, threshold, relax, min_height / 100, sim,
                         (series or "").strip() or None, "screencap" in opts, tagger,
                         "keep_text" in opts, "keep_offmodel" in opts, "save_dropped" in opts,
                         True, int(upscale_to) if upscale_on else 0, "outfits" in opts, "fresh" in opts,
                         "auto_reject" in opts, "keep_mono" in opts, 12 if preview else 0, upscaler, upscale_version,
                         own_dir, own_in_set, use_refs)

    progress(0, desc=t("Starting the build..."))
    with contextlib.nullcontext() if preview else working_on(p.char_dir(name)):
        log, data = captured_result(run, txn=txn.preview_txn(p, name) if preview else txn.build_txn(p, name))
    if preview:
        return *preview_view(data), log, data, gr.update(visible=True)
    chars = characters(p.name)
    return log, gr.update(choices=chars, value=p.char_dir(name).name), gr.Tabs(selected="review")


def do_preview(pname, selected, own_files, own_in_set, own_refs, name, series, upscale_on, upscaler, upscale_version,
               upscale_to, threshold, min_height, sim, relax, tagger, opts, progress=gr.Progress(track_tqdm=True)):
    return do_build(pname, selected, own_files, own_in_set, own_refs, name, series, upscale_on, upscaler,
                    upscale_version, upscale_to, threshold, min_height, sim, relax, tagger, opts, progress,
                    preview=True)


def browse_folder(current, title):
    from .pick import choose_folder
    current = (current or "").strip().strip('"')
    found = ask_dialog(choose_folder, title, current if current and Path(current).is_dir() else None)
    return found[0] if found else gr.skip()


def browse_save_dir(current):
    return browse_folder(current, t("Choose where to save the image set"))


def browse_episodes_dir(current):
    return browse_folder(current, t("Choose the folder the episodes are in now"))


def preview_view(data):
    if not data:
        return [], t("Preview 12 frames before building. Your finished images stay as they are.")
    gallery = [(it["file"], t(it["reason"]) + (f" · {it['score']:.3f}" if it["score"] is not None else ""))
               for it in data["items"]]
    summary = t("{frames} sampled frames · {accepted} accepted scenes. Duplicates are checked within this "
                "sample. Upscaling and outfit tags are applied in the full build.",
                frames=data["frames"], accepted=data["accepted"])
    return gallery, summary


def do_restore_frames(pname, folder, progress=gr.Progress(track_tqdm=True)):
    from .restore import restore_frames
    p = need_project(pname)
    log = captured(restore_frames, p, (folder or "").strip().strip('"') or None)
    return log, usage_md(pname), videos_table(pname)


def version_choices(pname, char):
    from .versions import list_versions
    rows = list_versions(need_project(pname), char) if pname and char else []
    choices = [(t("{date} · {n} images · {reason}", date=row["id"], n=row["images"], reason=t(row["reason"])),
                row["id"]) for row in rows]
    return gr.update(choices=choices, value=rows[0]["id"] if rows else None)


def version_comparison(pname, char, version):
    from .versions import compare_version
    if not pname or not char or not version:
        return t("No saved version selected.")
    if is_busy(char_dir_of(pname, char)):
        return t(BUSY)
    try:
        diff = compare_version(need_project(pname), char, version)
    except SystemExit as e:
        raise gui_error(e)
    summary = t("Saved: {saved} images · Current: {current}\n\nCurrent result: {added} added, {removed} removed, "
                "{captions} captions changed, {moved} moved to another group.", **diff)
    if diff["settings"]:
        summary += "\n\n" + t("Changed build settings (saved → current):") + "\n\n"
        arrow = "←" if lang() == "ar" else "→"
        summary += "\n".join(f"- `{key}`: `{values[0]}` {arrow} `{values[1]}`"
                             for key, values in sorted(diff["settings"].items()))
    return summary


def do_version(pname, char, version=None, restore=False, progress=gr.Progress(track_tqdm=True)):
    from .versions import restore_version, save_version
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    def run():
        if restore:
            if not version:
                raise gr.Error(t("No saved version selected."))
            restore_version(p, char, version)
        else:
            print(t("✅ Saved as version {id}.", id=save_version(p, char)))
    with working_on(p.char_dir(char)):
        log = captured(run)
    _alike_cache.pop(p.char_dir(char), None)
    _identity_cache.pop(p.char_dir(char), None)
    return log, version_choices(pname, char), []


def do_restore_version(pname, char, version, progress=gr.Progress(track_tqdm=True)):
    return do_version(pname, char, version, True, progress)


@guarded
def do_delete_version(pname, char, version, confirm):
    from .versions import delete_version
    p = need_project(pname)
    if not char or not version:
        raise gr.Error(t("No saved version selected."))
    if not confirm:
        raise gr.Error(t("Tick the confirmation first: a deleted version can't be restored."))
    captured(delete_version, p, char, version)
    return t("Deleted version {id}.", id=version), version_choices(pname, char), False


def sorted_root(pname, char):
    return Project(safe_name(pname)).chars_dir / char / "sorted"


def group_of(root, f):
    parts = f.relative_to(root).parts[:-1]
    return parts[1:] if parts and parts[0] == "_review" else parts


def is_review(root, f):
    return f.relative_to(root).parts[0] == "_review"


_alike_cache = {}
_identity_cache = {}


def _memo(cache, char_dir, files, compute):
    key = tuple((char_dir / f).stat().st_mtime_ns if (char_dir / f).exists() else 0 for f in files)
    if cache.get(char_dir, (None,))[0] != key:
        cache[char_dir] = (key, compute())
    return cache[char_dir][1]


def identity_review(pname, char):
    if not pname or not char:
        return {}
    from . import negatives, positives
    from .feedback import review_scores
    char_dir = char_dir_of(pname, char)
    return _memo(_identity_cache, char_dir, (negatives.FEATS, positives.FILE, negatives.FILE, "build.json"),
                 lambda: review_scores(Project(safe_name(pname)), char))


def look_alikes(pname, char):
    from . import negatives, positives
    char_dir = char_dir_of(pname, char)
    return _memo(_alike_cache, char_dir, (negatives.FILE, negatives.FEATS, positives.FILE),
                 lambda: negatives.look_alikes(char_dir))


def list_files(pname, char, flt):
    if not pname or not char:
        return []
    root = sorted_root(pname, char)
    files = list(root.rglob("*.png")) if root.exists() else []
    scores = identity_review(pname, char)
    uncertain = lambda f: scores.get(f.stem, {}).get("uncertain", False)
    files.sort(key=lambda f: (not uncertain(f), scores[f.stem]["risk"] if uncertain(f) else 0,
                              not is_review(root, f), group_of(root, f), f.name))
    if flt == "_review":
        files = [f for f in files if is_review(root, f)]
    elif flt == "_alike":
        alike = look_alikes(pname, char)
        files = sorted((f for f in files if f.stem in alike), key=lambda f: -alike[f.stem])
    elif flt in ("_uncertain", "_confirmed"):
        files = [f for f in files if scores.get(f.stem, {}).get(flt[1:], False)]
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
    scores = identity_review(pname, char)
    count = lambda key: sum(scores.get(f.stem, {}).get(key, False) for f in files)
    alike = look_alikes(pname, char)
    for label, n, value in (("❓ Unsure who it is ({n})", count("uncertain"), "_uncertain"),
                            ("⚠ To check ({n})", sum(is_review(root, f) for f in files), "_review"),
                            ("🚫 Like what you rejected ({n})", sum(f.stem in alike for f in files), "_alike"),
                            ("✅ Confirmed ({n})", count("confirmed"), "_confirmed")):
        if n:
            choices.append((t(label, n=n), value))
    for o in outfits_of(pname, char):
        n = sum(o["token"] in caption_tags(f) for f in files)
        choices.append((t("🧥 Outfit {id}: {tags} ({n})", id=o["id"], tags=", ".join(o["tags"][:2]), n=n),
                        f"outfit:{o['token']}"))
    counts = Counter("/".join(group_of(root, f)) for f in files)
    rank = lambda key, names: list(names).index(key) if key in names else len(names)
    order = lambda g: (rank(g.split("/")[0], FRAMING), rank((g.split("/") + [""])[1], VIEW), g)
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
    scores = identity_review(pname, char)
    return [(str(thumb(root.parent, f)), "✅" if scores.get(f.stem, {}).get("confirmed") else
             "🚫" if f.stem in alike else "❓" if scores.get(f.stem, {}).get("uncertain") else
             "⚠" if is_review(root, f) else None)
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
    current = identity_review(pname, char).get(f.stem)
    if current:
        info += "\n\n" + t("Match score: {score} (lower = closer to the character).", score=f"{current['score']:.3f}")
        if current["margin"] is not None:
            info += " " + t("Gap to the closest other character: {margin} (bigger = clearer).",
                            margin=f"{current['margin']:.3f}")
        if current["confirmed"]:
            info += "\n\n" + t("✅ You confirmed this character.")
        elif current["uncertain"]:
            info += "\n\n" + t("❓ Check who this is: a weak match, or close to another character.")
    if meta and meta.get("type") == "own":
        info += "\n\n" + t("📥 Your image: {name} · sharpness {sharp}", name=ltr(meta.get("own", f.name)),
                            sharp=f"{meta['sharp']:.0f}")
    elif meta and meta.get("t") is not None:
        m, s = divmod(int(meta["t"]), 60)
        info += "\n\n" + ("" if meta["type"] == "scene" else t(CROP.get(meta["type"], meta["type"])) + " · ") + t(
            "Episode {ep} at {at} · sharpness {sharp}", ep=f"v{meta['vid']:02d}", at=f"{m}:{s:02d}",
            sharp=f"{meta['sharp']:.0f}")
        if meta.get("upscaled", 1) > 1:
            info += t(" · enlarged ×{f}", f=f"{meta['upscaled']:.1f}")
    return str(f), caption, info


def stats_text(pname, char):
    files = list_files(pname, char, "all")
    if not char:
        return t("Pick a character.")
    root = sorted_root(pname, char)
    n_review = sum(is_review(root, Path(f)) for f in files)
    from . import negatives, positives
    trash = root.parent / "_deleted"
    n_del = len(list(trash.rglob("*.png"))) if trash.exists() else 0
    n_rej = len(negatives.load(root.parent)[0])
    n_conf = len(positives.load(root.parent)[0])
    return (t("**{n}** images · **{r}** to check · {d} deleted", n=len(files), r=n_review, d=n_del)
            + (t(" · {n} rejected as another character", n=n_rej) if n_rej else "")
            + (t(" · {n} confirmed", n=n_conf) if n_conf else ""))


def review_outputs(pname, char, files, idx, regallery=True):
    idx = max(0, min(idx, len(files) - 1)) if files else 0
    img, cap, info = panel(pname, char, files, idx)
    gal = (gr.update(value=gallery_items(pname, char, files), selected_index=idx if files else None)
           if regallery else gr.update(selected_index=idx if files else None))
    return gal, img, cap, info, files, idx, stats_text(pname, char)


def load_review(pname, char, flt):
    return review_outputs(pname, char, list_files(pname, char, flt or "all"), 0)


def change_char(pname, char):
    return (gr.update(choices=filter_choices(pname, char), value="all"), gr.update(choices=move_choices()),
            *load_review(pname, char, "all"))


def move_choices():
    return [(t("{shot} · {angle}", shot=shot_name(f), angle=angle_name(v)), f"{f}/{v}") for f in FRAMING for v in VIEW]


def select_image(pname, char, files, evt: gr.SelectData):
    return review_outputs(pname, char, files, evt.index, regallery=False)


def step(delta):
    def fn(pname, char, files, idx):
        return review_outputs(pname, char, files, idx + delta, regallery=False)
    return fn


def filter_update(pname, char, flt):
    choices = filter_choices(pname, char)
    return gr.update(choices=choices, value=flt if flt in [v for _, v in choices] else "all")


def picked_files(files, idx, picked=""):
    try:
        stems = set(json.loads(picked)) if picked else set()
    except (ValueError, TypeError):
        stems = set()
    chosen = [f for f in files or [] if Path(f).stem in stems]
    return chosen or ([files[idx]] if files and 0 <= idx < len(files) else [])


def first_position(files, targets, idx):
    places = [files.index(f) for f in targets if f in files]
    return min(places) if places else idx


def restore_batch(char_dir, batch):
    from . import negatives, positives
    for orig, moved, kind in reversed(batch):
        orig, moved = Path(orig), Path(moved)
        if not inside(orig, char_dir / "sorted") or not inside(moved, char_dir / "_deleted"):
            raise gr.Error(t("Nothing to undo"))
        if kind == "delete":
            negatives.move_pair(moved, orig.parent)
        elif positives.unreject(char_dir, moved, orig.parent, kind == "reject-confirmed") is None:
            raise gr.Error(t("Build this character once to save its identity features."))


@guarded
def delete_image(pname, char, flt, files, idx, undo, picked=""):
    from . import negatives
    targets = picked_files(files, idx, picked)
    if not targets:
        raise gr.Error(t("No image selected"))
    char_dir, batch = char_dir_of(pname, char), []
    try:
        for f in targets:
            batch.append((f, str(negatives.trash(char_dir, Path(f))), "delete"))
    except BaseException:
        restore_batch(char_dir, batch)
        raise
    if len(batch) > 1:
        gr.Info(t("Removed {n} images. Ctrl+Z puts them all back.", n=len(batch)))
    undo = (undo or []) + [batch]
    position = first_position(files, targets, idx)
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, position), undo, filter_update(pname, char, flt))


@guarded
def reject_image(pname, char, flt, files, idx, undo, picked=""):
    from . import negatives, positives
    targets = picked_files(files, idx, picked)
    if not targets:
        raise gr.Error(t("No image selected"))
    char_dir = char_dir_of(pname, char)
    built, _ = negatives.build_features(char_dir)
    if any(Path(f).stem not in built for f in targets):
        raise gr.Error(t("This character was built by an older version of the program: build it again once so it "
                         "can learn from rejections. Or remove the image with “Bad image”."))
    confirmed_names, batch = positives.load(char_dir)[0], []
    try:
        for f in targets:
            kind = "reject-confirmed" if Path(f).stem in confirmed_names else "reject"
            batch.append((f, str(positives.reject_image(char_dir, Path(f))), kind))
    except BaseException:
        restore_batch(char_dir, batch)
        raise
    undo = (undo or []) + [batch]
    alike = look_alikes(pname, char)
    n = sum(Path(f).stem in alike for f in list_files(pname, char, "all"))
    if len(batch) > 1:
        gr.Info(t("Rejected {k} images as another character. {n} remaining images look like them: pick “🚫 Like "
                  "what you rejected” under “Show”.", k=len(batch), n=n)
                if n else t("Rejected {k} images as another character; every later build leaves out what looks "
                            "like them.", k=len(batch)))
    else:
        gr.Info(t("Rejected as another character. {n} remaining images look like it: pick “🚫 Like what you "
                  "rejected” under “Show”.", n=n)
                if n else t("Rejected as another character; every later build leaves out what looks like it."))
    position = first_position(files, targets, idx)
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, position), undo, filter_update(pname, char, flt))


@guarded
def undo_delete(pname, char, flt, files, idx, undo):
    if not undo:
        raise gr.Error(t("Nothing to undo"))
    undo = list(undo)
    entry = undo.pop()
    batch = entry if entry and isinstance(entry[0], (list, tuple)) else [entry]
    restore_batch(char_dir_of(pname, char), batch)
    files = list_files(pname, char, flt)
    first = str(batch[0][0])
    idx = files.index(first) if first in files else idx
    return (*review_outputs(pname, char, files, idx), undo, filter_update(pname, char, flt))


@guarded
def forget_rejected(pname, char, flt, files, idx):
    from . import negatives
    if not char:
        raise gr.Error(t("Pick a character"))
    char_dir = char_dir_of(pname, char)
    n = len(negatives.load(char_dir)[0])
    negatives.clear(char_dir)
    gr.Info(t("The program forgot {n} rejected images. The images themselves stay deleted.", n=n))
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), filter_update(pname, char, flt))


@guarded
def confirm_image(pname, char, flt, files, idx, picked=""):
    from . import positives
    targets = picked_files(files, idx, picked)
    if not targets:
        raise gr.Error(t("No image selected"))
    done = [f for f in targets if positives.confirm(char_dir_of(pname, char), f)]
    if not done:
        raise gr.Error(t("Build this character once to save its identity features."))
    gr.Info(t("Confirmed {n} images. Preview the effect before you build again.", n=len(done)) if len(done) > 1
            else t("Confirmed. Preview the effect before you build again."))
    files = list_files(pname, char, flt)
    idx = files.index(done[0]) if done[0] in files else idx
    return (*review_outputs(pname, char, files, idx), filter_update(pname, char, flt))


def confirmed_choices(pname, char):
    from . import positives
    names = positives.load(sorted_root(pname, char).parent)[0] if pname and char else []
    return gr.update(choices=names, value=names[0] if names else None)


def confirmed_image(pname, char, name):
    from . import positives
    if not pname or not char or not name:
        return None
    path = positives.thumbnail(sorted_root(pname, char).parent, name)
    return str(path) if path.exists() else None


@guarded
def unconfirm_image(pname, char, flt, files, idx, name):
    from . import positives
    if not pname or not char or not name:
        raise gr.Error(t("Pick a confirmed image."))
    positives.remove(char_dir_of(pname, char), name)
    files = list_files(pname, char, flt)
    return (*review_outputs(pname, char, files, idx), filter_update(pname, char, flt))


IMPACT_COLUMNS = ["Episode", "Time", "Change", "Score before", "Score after"]
IMPACT_NOTE = ("See how your confirmations and rejections change the frames that match the character in the next build. "
               "Nothing changes until you build again. The counts are frames, before the scene filters.")


def impact_view(data):
    if not data:
        return t("Press “Preview the effect” after confirming or rejecting images."), table([], IMPACT_COLUMNS)
    summary = t("Matched frames: {before} → {after}. New: {added}; excluded: {removed}; different person: {switched}.",
                **{k: data[k] for k in ("before", "after", "added", "removed", "switched")})
    summary += "\n\n" + t("{confirmed} confirmed and {rejected} rejected images. Up to 24 changed frames are shown.",
                            confirmed=data["confirmed"], rejected=data["rejected"])
    rows = [[f"v{r['vid']:02d}", mmss(r["t"]), t(r["change"]),
             round(r["before"], 3) if r["before"] is not None else "—",
             round(r["after"], 3) if r["after"] is not None else "—"] for r in data["items"]]
    return summary, table(rows, IMPACT_COLUMNS)


def impact_images(data):
    images = []
    if data:
        p = Project(data["project"])
        for row in data["items"]:
            path = p.path(row["frame"])
            if not path.exists():
                continue
            with Image.open(path) as source:
                frame = source.convert("RGB")
                for key, label in (("before_box", "Before"), ("after_box", "After")):
                    if row[key] is not None:
                        image = frame.crop(row[key])
                        image.thumbnail((320, 320))
                        images.append((image, f"{t(label)} · v{row['vid']:02d} {mmss(row['t'])} · {t(row['change'])}"))
    return images


def do_feedback_preview(pname, char, progress=gr.Progress(track_tqdm=True)):
    from .feedback import preview_impact
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    _, data = captured_result(preview_impact, p, char)
    return *impact_view(data), impact_images(data), data


def confirmed_view(pname, char):
    return confirmed_choices(pname, char), None


def clear_impact():
    return *impact_view({}), [], {}


@guarded
def move_image(pname, char, flt, files, idx, target, picked=""):
    from . import negatives
    targets = picked_files(files, idx, picked)
    if not targets or not target:
        raise gr.Error(t("Pick an image and the target group"))
    moved = [negatives.move_pair(Path(f), sorted_root(pname, char) / target) for f in targets]
    files = list_files(pname, char, flt)
    return review_outputs(pname, char, files, next((i for i, f in enumerate(files) if Path(f) == moved[0]), idx))


@guarded
def save_caption(pname, char, files, idx, caption):
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
    status = t("**{n}** captions · **{k}** different tags · {u} changes you can undo",
               n=n, k=len(cnt), u=history_size(char_dir_of(pname, char)))
    outfits = outfits_of(pname, char)
    if outfits:
        status += "\n\n" + "\n".join(f"- 🧥 {ltr('`' + o['token'] + '`')}: {', '.join(o['tags'])}" for o in outfits)
    return rows, status, list(cnt)


def tag_view(pname, char, query="", keep=()):
    rows, status, tags = _tag_state(pname, char, query)
    return table(rows, TAG_COLUMNS), status, gr.update(choices=tags, value=[s for s in keep or () if s in tags])


def tag_search(pname, char, query, selected):
    return tag_view(pname, char, query, selected)


def pick_tag(selected, evt: gr.SelectData):
    tag = evt.row_value[0] if getattr(evt, "row_value", None) else evt.value
    sel = list(selected or [])
    if tag and tag not in sel:
        sel.append(tag)
    return sel


def goal_choices():
    return [(t("🧑 Character"), "character"), (t("🖌 Style"), "style"), (t("👕 Outfit"), "outfit")]


def _goal_state(pname, char, goal):
    from .captions import goal_suggestions
    from .outfits import protected
    from .tags import load_box, tag_counts
    char_dir = char_dir_of(pname, char) if pname and char else None
    if not char_dir or not (char_dir / "sorted").exists():
        return [], [], "", [], ""
    p = Project(safe_name(pname))
    cnt, n = tag_counts(char_dir)
    rows = goal_suggestions(cnt, n, goal or "character", protected(p, char))
    choices = [(f"{GOAL_ICONS[r['category']]} {r['tag']} · {r['count']}", r["tag"]) for r in rows]
    present = dict.fromkeys(r["category"] for r in rows)
    legend = ("  ".join(f"{GOAL_ICONS[c]} {t(CATEGORY_NAMES[c])}" for c in present) if rows
              else t("No tags of this kind in the captions."))
    box = load_box(char_dir)
    note = (t("Removed from every caption, so the trigger word learns them as part of the character. The number "
              "is how many images had the tag. Check a tag and put it back to return it to those images.") if box
            else t("Empty. Tags you move here are removed from every caption, so the trigger word learns them as "
                   "part of the character."))
    old = p.load(f"characters/{char_dir.name}/build.json", {}).get("core_tags")
    if old:
        note += "\n\n" + t("Removed when these images were made by an older version: {tags}. Rebuild the character "
                            "to get every tag back in the captions.", tags=ltr(", ".join(old)))
    box_choices = [(f"{tag} · {len(where)}", tag) for tag, where in box.items()]
    return choices, [r["tag"] for r in rows if r["suggested"]], legend, box_choices, note


def goal_view(pname, char, goal):
    choices, suggested, legend, box_choices, note = _goal_state(pname, char, goal)
    return gr.update(choices=choices, value=suggested), legend, gr.update(choices=box_choices, value=[]), note


def tag_views(pname, char, query, goal):
    return (*tag_view(pname, char, query), *goal_view(pname, char, goal))


@guarded
def _tag_edit(pname, char, query, goal, **kw):
    from .outfits import edit_captions
    if not char:
        raise gr.Error(t("Pick the character"))
    n = edit_captions(Project(safe_name(pname)), char, **kw)
    gr.Info(t("Changed {n} captions", n=n))
    return tag_views(pname, char, query, goal)


def tag_remove(pname, char, selected, query, goal="character"):
    if not selected:
        raise gr.Error(t("Pick one or more tags in the table"))
    return _tag_edit(pname, char, query, goal, remove=selected)


def tag_replace(pname, char, selected, new_text, query, goal="character"):
    if not selected:
        raise gr.Error(t("Pick one or more tags in the table"))
    return _tag_edit(pname, char, query, goal, replace={tag: new_text or "" for tag in selected})


def tag_add(pname, char, add_text, query, goal="character"):
    from .tags import split_tags
    if not split_tags(add_text or ""):
        raise gr.Error(t("Type the tag to add"))
    return _tag_edit(pname, char, query, goal, add=split_tags(add_text))


@guarded
def tag_absorb(pname, char, picked, query, goal="character"):
    from .outfits import absorb_captions, protected
    if not char:
        raise gr.Error(t("Pick the character"))
    if not picked:
        raise gr.Error(t("Pick one or more tags first"))
    p = Project(safe_name(pname))
    fixed = protected(p, char)
    moving = [tag for tag in picked if not fixed(tag)]
    if not moving:
        raise gr.Error(t("The trigger word, the series and the outfit tags stay in the captions"))
    n = absorb_captions(p, char, moving)
    gr.Info(t("Moved into the trigger word: {tags}. Changed {n} captions.", tags=", ".join(moving), n=n))
    return tag_views(pname, char, query, goal)


@guarded
def tag_restore(pname, char, picked, query, goal="character"):
    from .outfits import restore_captions
    if not char:
        raise gr.Error(t("Pick the character"))
    if not picked:
        raise gr.Error(t("Pick one or more tags first"))
    n = restore_captions(Project(safe_name(pname)), char, picked)
    gr.Info(t("Put back in the captions: {tags}. Changed {n} captions.", tags=", ".join(picked), n=n))
    return tag_views(pname, char, query, goal)


@guarded
def tag_undo(pname, char, query, goal="character"):
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
    return tag_views(pname, char, query, goal)


@guarded
def rerun_outfits(pname, char, query, goal="character"):
    from .outfits import run_outfits
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    log = captured(run_outfits, p, char)
    return (*tag_views(pname, char, query, goal), log)


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
        return t("Pick a character."), table([], GROUP_COLUMNS)
    p = Project(safe_name(pname))
    root = sorted_root(pname, char)
    files = sorted(root.rglob("*.png")) if root.exists() else []
    if not files:
        return t("There are no images for this character. Build it first (tab 2)."), table([], GROUP_COLUMNS)
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
        model = build.get("settings", {}).get("upscaler") or "cdc"
        lines.append(t("- Upscaled with {model}: {n}", model=t(UPSCALERS.get(model, model)), n=len(upscaled & stems)))
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
    return "\n".join(lines), table(rows, GROUP_COLUMNS)


def do_save(pname, char, parent):
    from .aitk import made_here, save_settings
    from .export import run_export
    p = need_project(pname)
    if not char:
        raise gr.Error(t("Pick the character"))
    out = save_target(char, parent)
    if out.exists() and any(out.iterdir()) and not made_here(out):
        raise gr.Error(t("There is a folder named {name} in that place that the program didn't make, so it won't "
                         "be overwritten. Pick another place.", name=out.name))
    save_settings(save_dir=str(out.parent))
    with working_on(p.char_dir(char)):
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
    if (p.dir / "episodes").is_dir():
        text += "\n\n" + t("The copies of episodes you dropped into the program are deleted with it.")
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


def title_md(gpu):
    from . import __version__
    from .updates import RELEASES_PAGE, newer
    text = ("## " + t("ALDS — LoRA datasets of a character from anime episodes") + "\n"
            + (t("🟢 The graphics card is used (CUDA)") if gpu else t("🔴 Running on the CPU only (slow)"))
            + f" · v{__version__}")
    if newer():
        text += ("\n\n" + t("🆕 Version {version} is out.", version=newer().lstrip("vV"))
                 + f" [{t('Download it')}]({RELEASES_PAGE})")
    return text


def other_language():
    return LANGS["en" if lang() == "ar" else "ar"]


def static_texts(demo):
    texts = {}
    for block in demo.blocks.values():
        props = {prop: getattr(block, prop) for prop in ("label", "info")
                 if isinstance(getattr(block, prop, None), str) and getattr(block, prop) in AR}
        if isinstance(block, (gr.Button, gr.Markdown)) and isinstance(block.value, str) and block.value in AR:
            props["value"] = block.value
        if isinstance(block, gr.Dataframe):
            props["headers"] = list(block.headers)
        if props:
            texts[block._id] = (block, props)
    return texts


def apply_texts(texts, language):
    with use(language):
        for block, props in texts.values():
            for prop, text in props.items():
                setattr(block, prop, translated(text))
                if prop == "headers":
                    block.value = block.postprocess(table([], text))


def build_ui(language):
    import onnxruntime as ort
    gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    with gr.Blocks(title="ALDS", analytics_enabled=False) as demo, use("en"):
        texts = build_page(demo, gpu)
    apply_texts(texts, language)
    return demo


def build_page(demo, gpu):
    from .aitk import load_settings
    L = localized
    title = gr.Markdown(title_md(gpu))
    with gr.Row(elem_id="top-bar"):
        project = gr.Dropdown(choices=projects(), value=(projects() or [None])[0], allow_custom_value=True,
                              label=t("Project (pick one or type a new name)"), scale=4)
        char = gr.Dropdown(label=t("Character"), choices=[], scale=3)
        refresh = gr.Button(t("🔄 Refresh"), scale=1)
        lang_btn = gr.Button(other_language(), scale=1)
        lang_box = gr.Textbox(visible=False)

    with gr.Tabs() as tabs:
        with gr.Tab(t("1. Scan episodes"), id="scan"):
            with gr.Row():
                with gr.Column(scale=3):
                    episodes_drop = gr.File(file_count="multiple", file_types=sorted(VIDEO_EXTS), type="filepath",
                                            height=120, label=t("Drop the episodes here, or click to choose them"),
                                            elem_id="episode-drop")
                    with gr.Row():
                        browse_files = gr.Button(t("📂 Choose episodes"), size="sm", elem_id="episode-browse")
                        browse_dir = gr.Button(t("📁 Choose a folder of episodes"), size="sm")
                    episodes = gr.Dropdown(choices=[], value=[], multiselect=True, allow_custom_value=True,
                                           label=t("Episodes to scan"), elem_classes="ltr",
                                           info=t("× removes one. You can also paste a path and press Enter."))
                    auto = gr.Checkbox(True, label=t("Leave out the OP/ED automatically"),
                                       info=t("Parts repeated between episodes are left out. With one episode, the "
                                              "next episode in its folder is used for the comparison."))
                    with gr.Accordion(t("⚙️ Advanced settings"), open=False):
                        gr.Markdown(t("You rarely need these: the defaults suit most anime."))
                        skip = gr.Textbox(label=t("More times to ignore (optional)"), elem_classes="ltr",
                                          placeholder="0:00-1:55, 21:55-24:30")
                        gr.Markdown(t("**Opening and ending (OP/ED)**"))
                        auto_min = gr.Slider(15, 120, 40, step=5, label=t("Shortest OP/ED (seconds)"),
                                             info=t("A part repeated between episodes is left out only if it's at "
                                                    "least this long. Lower it if a short OP/ED isn't found."))
                        autoskip_btn = gr.Button(t("🔁 Find the OP/ED again in the scanned episodes"))
                        busy_auto, stop_auto = running()
                        gr.Markdown(t("**Which frames are kept** (for new scans)"))
                        min_gap = gr.Slider(0.1, 2.0, 0.35, step=0.05, label=t("Time between kept frames (seconds)"),
                                            info=t("Lower = more frames from each scene. Higher = fewer frames and "
                                                   "a faster scan."))
                        keep_diff = gr.Slider(1, 20, 5, step=0.5, label=t("Change needed to keep another frame"),
                                              info=t("How different a frame must look from the last kept one. "
                                                     "Lower = more, more similar frames. Higher = fewer."))
                    scan_btn = gr.Button(t("▶ Start scanning"), variant="primary", size="lg")
                    busy_scan, stop_scan = running()
                with gr.Column(scale=3):
                    vids_df = gr.Dataframe(headers=VIDEO_COLUMNS, interactive=False, wrap=True,
                                           label=t("Episodes scanned in this project"),
                                           column_widths=["5%", "31%", "13%", "13%", "38%"])
                    scan_log = gr.Textbox(lines=10, label=t("Log"), elem_classes="log", autoscroll=True)

        with gr.Tab(t("2. Pick the character"), id="pick"):
            gr.Markdown(t("Click the character's image to select it, click again to unselect. If it shows up in more "
                          "than one cluster (another outfit, say), pick all of them. **The numbers change after every "
                          "scan.**"))
            with gr.Row():
                with gr.Column(scale=3):
                    clusters_gal = gr.Gallery(label=t("Characters found"), columns=5, height=500,
                                              allow_preview=False, object_fit="contain", buttons=[])
                    with gr.Accordion(t("🧩 Fix the clusters (two characters mixed, or one split up)"), open=False):
                        gr.Markdown(t("**One character in several clusters?** Usually there's nothing to fix: just "
                                      "select all of them.\n\n**Two characters in one cluster?** Select only that "
                                      "cluster, then split it:"))
                        split_cut = gr.Slider(0.06, 0.19, 0.14, step=0.01, label=t("Split strength"),
                                              info=t("Lower = more, smaller parts. The other clusters keep their "
                                                     "numbers."))
                        split_btn = gr.Button(t("✂ Split the selected cluster"))
                        gr.Markdown(t("**Many clusters wrong?** Cluster the whole project again (all the numbers "
                                      "change):"))
                        cut = gr.Slider(0.10, 0.40, 0.20, step=0.01, label=t("Cluster size"),
                                        info=t("Lower = more, smaller clusters, which separates characters that look "
                                               "alike. Higher = fewer, bigger clusters, which joins a character that "
                                               "got split."))
                        min_csize = gr.Slider(3, 40, 8, step=1, label=t("Hide clusters with fewer views than"),
                                              info=t("Small clusters are usually background characters."))
                        recluster_btn = gr.Button(t("🔁 Re-cluster the whole project"))
                        busy_clu, stop_clu = running()
                        recluster_log = gr.Textbox(lines=6, label=t("Log"), elem_classes="log")
                with gr.Column(scale=2):
                    chosen = gr.CheckboxGroup(label=t("Selected clusters"), choices=[])
                    sheet = gr.Image(label=t("Cluster preview"), interactive=False, height=380,
                                     buttons=["fullscreen"])
            with gr.Row():
                with gr.Column(scale=1):
                    name = gr.Textbox(label=t("Trigger word (the character's name)"), elem_classes="ltr",
                                      placeholder="natsu_ft")
                    name_info = gr.Markdown()
                    series = gr.Textbox(label=t("Anime name as a tag (optional)"), elem_classes="ltr",
                                        placeholder="fairy tail")
                    own_files = gr.File(file_count="multiple", file_types=["image"], type="filepath", height=150,
                                        label=t("Your own images of the character (optional)"))
                    gr.Markdown(t("Tagged and enlarged like the scenes, and kept with the character for later "
                                  "builds. × removes one."))
                    own_in_set = gr.Checkbox(True, label=t("Add them to the image set"))
                    own_refs = gr.Checkbox(True, label=t("Use them to find the character in the episodes"))
                    own_loaded = gr.State([])
                with gr.Column(scale=1):
                    upscale_on = gr.Checkbox(label=t("Enlarge small scenes with an anime upscaler: cleaner lines "
                                                     "than plain resizing"))
                    with gr.Column(visible=False) as upscale_box:
                        upscaler = gr.Radio(upscaler_choices(), value=DEFAULT_UPSCALER, label=t("Upscaling model"),
                                            info=t("Press ! next to a model to read about it."),
                                            elem_id="upscaler-models")
                        upscale_version = gr.Radio(model_version_choices(), value="auto", label=t("Model version"),
                                                   info=t("Automatic uses 2x for enlargements up to double and 4x "
                                                          "above. Choosing one version downloads only that version."))
                        model_info = gr.Markdown()
                        model_delete = gr.Button(t("🗑 Delete this model to free space"), size="sm", visible=False)
                        upscale_to = gr.Slider(512, 2048, 1024, step=64,
                                               label=t("Enlarge every scene smaller than this to it (pixels; use "
                                                       "your training resolution)"))
                    with gr.Accordion(t("⚙️ Advanced settings"), open=False):
                        gr.Markdown(t("The defaults suit most anime. If the result isn't right, change one setting "
                                      "and build again: rebuilding is fast."))
                        threshold = gr.Slider(0.06, 0.25, 0.13, step=0.005, label=t("Match threshold"),
                                              info=t("Lower = only clear matches, fewer images. Higher = more "
                                                     "images, but other characters may slip in."))
                        sim = gr.Slider(0.60, 0.98, 0.80, step=0.01, label=t("Duplicate removal"),
                                        info=t("Lower = removes more look-alike images. Higher = keeps more "
                                               "similar ones."))
                        min_height = gr.Slider(10, 100, round(DEFAULT_MIN_HEIGHT * 100), step=5,
                                               label=t("Smallest character in the scene (% of the frame height)"),
                                               info=t("Scenes where the character is smaller are left out. Only "
                                                      "scenes where the character is alone are used."))
                        relax = gr.Slider(1.0, 2.0, 1.0, step=0.05, label=t("Follow the character within a shot"),
                                          info=t("1 = off (recommended). Higher takes more frames from the same "
                                                 "shot, but may let other characters in."))
                        tagger = gr.Dropdown(["EVA02_Large", "SwinV2_v3", "ConvNext_v3", "ViT_v3"],
                                             value="EVA02_Large", label=t("Tagging model"),
                                             info=t("EVA02_Large is the most accurate; the others are faster."))
                        opts = gr.CheckboxGroup(build_options(), value=["auto_reject", "outfits", "screencap"],
                                                label=t("Options"))
                    with gr.Row():
                        preview_btn = gr.Button(t("🔎 Preview these settings"), scale=1)
                        build_btn = gr.Button(t("▶ Build the image set"), variant="primary", scale=2)
                    busy_preview, stop_preview = running()
                    busy_build, stop_build = running()
            with gr.Accordion(t("🔎 Settings preview"), open=True, visible=False) as preview_box:
                preview_state = gr.State({})
                preview_summary = gr.Markdown(preview_view({})[1])
                preview_gal = gr.Gallery(columns=6, height=360, label=t("Accepted and excluded scenes"),
                                         object_fit="contain")
            build_log = gr.Textbox(lines=12, label=t("Report"), elem_classes="log")

        with gr.Tab(t("3. Review"), id="review"):
            gr.Markdown(t("❓ unsure who it is and ⚠ to check come first. **✅** confirms a clear image, and the program "
                          "learns from it · **🚫 N** removes another character and learns to leave it out · "
                          "**🗑 Delete** removes a bad image · **← →** next and previous · **Ctrl+Z** undoes a "
                          "removal · **Ctrl or Shift + click** picks several images, **Ctrl+A** all of them, and the "
                          "buttons act on every picked image"))
            with gr.Row(elem_classes="inline-row"):
                r_filter = gr.Dropdown(label=t("Show"), choices=[(t("All"), "all")], value="all", scale=2)
                with gr.Column(scale=3):
                    r_stats = gr.Markdown()
            with gr.Row():
                with gr.Column(scale=3):
                    r_gal = gr.Gallery(columns=6, height=720, allow_preview=False, object_fit="contain",
                                       show_label=False, buttons=[], elem_id="review-gallery")
                with gr.Column(scale=2):
                    r_img = gr.Image(interactive=False, height=460, show_label=False, elem_id="preview",
                                     buttons=["fullscreen"])
                    r_info = gr.Markdown()
                    with gr.Row():
                        prev_btn = gr.Button(t("← Previous"), elem_id="btn-prev")
                        next_btn = gr.Button(t("Next →"), elem_id="btn-next")
                    confirm_btn = gr.Button(t("✅ Definitely this character"), variant="primary")
                    with gr.Row():
                        reject_btn = gr.Button(t("🚫 Not this character (N)"), variant="stop", elem_id="btn-reject")
                        del_btn = gr.Button(t("🗑 Bad image (Delete)"), elem_id="btn-del")
                        undo_btn = gr.Button(t("↶ Undo"), elem_id="btn-undo")
                    r_caption = gr.Textbox(lines=4, label=t("Caption"), elem_classes="ltr")
                    save_btn = gr.Button(t("💾 Save caption"))
                    with gr.Row(elem_classes="inline-row"):
                        move_to = gr.Dropdown(label=t("Wrong group? Move it to"), choices=[], scale=3)
                        move_btn = gr.Button(t("↪ Move"), scale=1)
            files_st, idx_st, undo_st = gr.State([]), gr.State(0), gr.State([])
            r_picked = gr.Textbox(visible=False)
            with gr.Accordion(t("✅ Confirmed images and the effect of your review"), open=False):
                gr.Markdown(t("Confirm clear images from different angles and in different outfits. Images marked ❓ "
                              "come first under “All”."))
                with gr.Row():
                    with gr.Column():
                        confirmed_pick = gr.Dropdown(label=t("Confirmed images"), choices=[], elem_classes="ltr")
                        confirmed_thumb = gr.Image(interactive=False, height=200, show_label=False)
                        unconfirm_btn = gr.Button(t("↶ Remove this confirmation"))
                        forget_btn = gr.Button(t("🧹 Forget all images rejected as another character"), size="sm")
                    with gr.Column(scale=2):
                        gr.Markdown(t(IMPACT_NOTE))
                        impact_btn = gr.Button(t("🔎 Preview the effect"))
                        busy_impact, stop_impact = running()
                        impact_summary = gr.Markdown()
                        impact_table = gr.Dataframe(headers=IMPACT_COLUMNS, interactive=False)
                impact_gal = gr.Gallery(label=t("Frames that change (when the frames are still on disk)"),
                                        columns=4, height=350, object_fit="contain")
                impact_state = gr.State({})
            with gr.Accordion(t("🕘 Saved build versions"), open=False):
                gr.Markdown(t("A version is saved before every rebuild. Restoring also saves the current result. "
                              "Versions stay inside this project; images that didn't change are stored only once."))
                with gr.Row(elem_classes="inline-row"):
                    version_pick = gr.Dropdown(label=t("Saved version"), choices=[], scale=3)
                    version_refresh = gr.Button(t("🔄 Refresh"), scale=1)
                version_diff = gr.Markdown()
                with gr.Row():
                    version_save = gr.Button(t("💾 Save current version"))
                    version_restore = gr.Button(t("↶ Restore selected version"))
                busy_version, stop_version = running()
                with gr.Row(elem_classes="inline-row"):
                    version_delete_confirm = gr.Checkbox(label=t("Delete the selected version for good"), scale=3)
                    version_delete = gr.Button(t("🗑 Delete version"), variant="stop", scale=1)
                version_log = gr.Textbox(label=t("Log"), lines=3, elem_classes="log")

        with gr.Tab(t("4. Tags"), id="tags"):
            gr.Markdown(t("Every tag the tagger found is in the captions. Pick what the LoRA is for to see the tags "
                          "that matter for it, then move the ones the trigger word should learn into the trigger word. "
                          "Below are all the tags and how often they appear: remove, replace or add tags in **all** "
                          "captions at once. Every change can be undone."))
            t_goal = gr.Radio(goal_choices(), value="character", label=t("What is the LoRA for?"))
            with gr.Row():
                with gr.Column(scale=3):
                    t_goal_tags = gr.CheckboxGroup(label=t("Tags for this goal (checked = in at least 20% of the "
                                                           "images)"), choices=[], elem_classes="tag-choices")
                    t_goal_legend = gr.Markdown()
                    t_absorb_btn = gr.Button(t("🔒 Move the checked into the trigger word"), variant="primary")
                with gr.Column(scale=2):
                    t_box = gr.CheckboxGroup(label=t("🔒 Learned by the trigger word (not in the captions)"),
                                             choices=[], elem_classes="tag-choices")
                    t_box_note = gr.Markdown()
                    t_restore_btn = gr.Button(t("↩ Put the checked back in the captions"))
            with gr.Row():
                with gr.Column(scale=3):
                    t_search = gr.Textbox(label=t("Search"), elem_classes="ltr")
                    t_table = gr.Dataframe(headers=TAG_COLUMNS, interactive=False, max_height=620,
                                           column_widths=["70%", "15%", "15%"])
                with gr.Column(scale=2):
                    t_status = gr.Markdown()
                    t_selected = gr.Dropdown(label=t("Selected tags"), choices=[], multiselect=True,
                                             allow_custom_value=True, elem_classes="ltr")
                    with gr.Row():
                        t_remove_btn = gr.Button(t("🗑 Remove the selected from all captions"), variant="stop")
                        t_absorb_sel_btn = gr.Button(t("🔒 Move the selected into the trigger word"))
                    with gr.Row(elem_classes="inline-row"):
                        t_new = gr.Textbox(label=t("Replace the selected with (empty = remove)"), elem_classes="ltr",
                                           scale=3, placeholder="brown eyes")
                        t_replace_btn = gr.Button(t("↔ Replace"), scale=1)
                    with gr.Row(elem_classes="inline-row"):
                        t_add_text = gr.Textbox(label=t("Add a tag to every caption"), elem_classes="ltr", scale=3)
                        t_add_btn = gr.Button(t("➕ Add"), scale=1)
                    t_undo_btn = gr.Button(t("↶ Undo the last change (Ctrl+Z)"), elem_id="btn-tag-undo")
                    gr.Markdown(t("**Outfits:** after deleting images in review, separate the outfits again to update "
                                  "them."))
                    t_outfits_btn = gr.Button(t("🧥 Separate the outfits again"))
                    t_log = gr.Textbox(lines=4, label=t("Log"), elem_classes="log")

        with gr.Tab(t("5. Save the result"), id="export"):
            gr.Markdown(t("Saves the reviewed images with their captions in a folder named after the character, inside "
                          "the place you choose. That folder is the dataset you train on."))
            saved_dir = load_settings().get("save_dir", "")
            with gr.Row():
                with gr.Column(scale=2):
                    with gr.Row(elem_classes="inline-row"):
                        e_out = gr.Textbox(saved_dir, label=t("Save to (a folder named after the character is made "
                                                              "in it)"),
                                           elem_classes="ltr", placeholder="D:\\datasets", scale=4)
                        e_browse = gr.Button(t("📁 Choose"), scale=1)
                    export_btn = gr.Button(t("💾 Save the images and captions"), variant="primary", size="lg")
                    busy_export, stop_export = running()
                    export_log = gr.Textbox(lines=6, label=t("Log"), elem_classes="log")
                with gr.Column(scale=2):
                    e_summary = gr.Markdown()
                    groups_df = gr.Dataframe(headers=GROUP_COLUMNS, interactive=False,
                                             label=t("Distribution"))
            with gr.Accordion(t("🧰 Project upkeep: disk space, frames and deleting"), open=False):
                with gr.Row():
                    with gr.Column():
                        usage = gr.Markdown()
                        gr.Markdown(t("**Safe clean** deletes only what the program will never use again: frames "
                                      "with no character, frames inside the OP/ED, thumbnails and leftover copies. "
                                      "Nothing you need is lost."))
                        clean_safe_btn = gr.Button(t("🧹 Safe clean"))
                        gr.Markdown(t("**Delete all frames** keeps your finished images and saved versions. "
                                      "Restore the frames from the original episodes before building again."))
                        clean_confirm = gr.Checkbox(label=t("Delete extracted frames; keep finished images and "
                                                            "versions"))
                        clean_all_btn = gr.Button(t("🗑 Delete all frames"), variant="stop")
                    with gr.Column():
                        gr.Markdown(t("**Restore frames:** recover missing frames using the original episodes. "
                                      "Character groups and reviewed images stay as they are."))
                        with gr.Row(elem_classes="inline-row"):
                            restore_folder = gr.Textbox(label=t("Episodes folder if moved (optional)"),
                                                        elem_classes="ltr", scale=4)
                            restore_browse = gr.Button(t("📁 Choose"), scale=1)
                        restore_frames_btn = gr.Button(t("↶ Restore missing frames"))
                        busy_restore, stop_restore = running()
                        upkeep_log = gr.Textbox(lines=5, label=t("Log"), elem_classes="log")
                gr.Markdown(t("**Delete the project** from the program folder, after saving what you need:"))
                del_hint = gr.Markdown()
                del_confirm = gr.Checkbox(label=t("I understand deleting the project is final and can't be undone"))
                del_project_btn = gr.Button(t("🗑 Delete the project"), variant="stop")

    proj_outputs = [vids_df, clusters_gal, chosen, char, usage]
    project_loaded = project.change(L(load_project), project, proj_outputs)
    list_refreshed = refresh.click(L(lambda p: (gr.update(choices=projects()), *load_project(p))), project,
                                   [project, *proj_outputs])

    def long_action(btn, stop, busy, fn, inputs, outputs, log=None):
        ui = [stop, busy]
        ev = btn.click(L(start_ui), None, ui, queue=False) \
            .then(streamed(fn, outputs.index(log) if log else None, len(outputs)), inputs, outputs,
                  concurrency_id="gpu", show_progress_on=[busy])
        ev.then(end_ui, None, ui, queue=False)
        ev.failure(end_ui, None, ui, queue=False)
        return ev

    for stop in (stop_scan, stop_auto, stop_clu, stop_build, stop_export, stop_restore, stop_preview, stop_version,
                 stop_impact):
        stop.click(L(press_stop), None, stop, queue=False)

    episodes.blur(episodes_update, episodes, episodes, queue=False)
    browse_files.click(L(browse_episodes), episodes, episodes, concurrency_id="dialog")
    browse_dir.click(L(browse_episode_folder), episodes, episodes, concurrency_id="dialog")
    episodes_drop.upload(L(drop_episodes), [project, episodes, episodes_drop], [episodes, episodes_drop],
                         concurrency_id="dialog")
    scanned = long_action(scan_btn, stop_scan, busy_scan, do_scan,
                          [project, episodes, skip, auto, auto_min, min_gap, keep_diff],
                          [scan_log, project, *proj_outputs, episodes, tabs], scan_log)
    autoskipped = long_action(autoskip_btn, stop_auto, busy_auto, do_autoskip, [project, auto, auto_min],
                              [scan_log, *proj_outputs], scan_log)
    reclustered = long_action(recluster_btn, stop_clu, busy_clu, do_recluster, [project, cut, min_csize],
                              [recluster_log, clusters_gal, chosen], recluster_log)
    split = long_action(split_btn, stop_clu, busy_clu, do_split, [project, chosen, split_cut],
                        [recluster_log, clusters_gal, chosen], recluster_log)
    clean_safe_btn.click(L(lambda p: do_clean(p, False, False)), project, [upkeep_log, usage], concurrency_id="gpu")
    clean_all_btn.click(L(lambda p, c: do_clean(p, True, c)), [project, clean_confirm], [upkeep_log, usage],
                        concurrency_id="gpu")
    long_action(restore_frames_btn, stop_restore, busy_restore, do_restore_frames, [project, restore_folder],
                [upkeep_log, usage, vids_df], upkeep_log)
    restore_browse.click(L(browse_episodes_dir), restore_folder, restore_folder, concurrency_id="dialog")
    clusters_gal.select(L(pick_cluster), [project, chosen], [chosen, sheet])
    upscale_on.change(lambda on: gr.update(visible=on), upscale_on, upscale_box, queue=False)
    model_in = [upscale_on, upscaler, upscale_version]
    model_out = [model_info, model_delete]
    for control in model_in:
        control.change(L(model_view), model_in, model_out, queue=False)
    upscale_on.input(L(do_model), model_in, model_out, concurrency_id="download")
    upscaler.input(model_versions, [upscaler, upscale_version], upscale_version, queue=False) \
        .then(L(do_model), model_in, model_out, concurrency_id="download")
    upscale_version.input(L(do_model), model_in, model_out, concurrency_id="download")
    model_delete.click(L(delete_model), [upscaler, upscale_version], model_out, concurrency_id="gpu")

    own_in = [project, name, own_files, own_loaded]
    own_out = [own_files, own_loaded, name_info]
    name.change(L(name_changed), own_in, own_out, trigger_mode="always_last")
    project.change(L(name_changed), own_in, own_out)
    setup_out = [name, series, chosen, own_in_set, own_refs, upscale_on, upscaler, upscale_version, upscale_to,
                 threshold, min_height, sim, relax, tagger, opts]
    char.change(L(char_setup), [project, char], setup_out)

    build_inputs = [project, chosen, own_files, own_in_set, own_refs, name, series, upscale_on, upscaler,
                    upscale_version, upscale_to, threshold, min_height, sim, relax, tagger, opts]
    preview_out = [preview_gal, preview_summary, preview_state, preview_box]
    long_action(preview_btn, stop_preview, busy_preview, do_preview, build_inputs,
                [preview_gal, preview_summary, build_log, preview_state, preview_box], build_log)

    def clear_preview():
        return [], preview_view({})[1], {}, gr.update(visible=False)
    for control in build_inputs:
        control.change(L(clear_preview), None, preview_out, concurrency_id="gpu")
    rv_out = [r_gal, r_img, r_caption, r_info, files_st, idx_st, r_stats]
    built = long_action(build_btn, stop_build, busy_build, do_build, build_inputs, [build_log, char, tabs],
                        build_log)
    built.success(L(name_changed), own_in, own_out)
    built = built.success(L(change_char), [project, char], [r_filter, move_to, *rv_out]) \
        .success(L(version_choices), [project, char], version_pick) \
        .success(lambda: [], None, undo_st)

    char.change(L(change_char), [project, char], [r_filter, move_to, *rv_out])
    char.change(L(version_choices), [project, char], version_pick)
    project.change(lambda: [], None, undo_st)
    char.change(lambda: [], None, undo_st)
    version_refresh.click(L(version_choices), [project, char], version_pick) \
        .then(L(version_comparison), [project, char, version_pick], version_diff)
    version_pick.change(L(version_comparison), [project, char, version_pick], version_diff)
    version_delete.click(L(do_delete_version), [project, char, version_pick, version_delete_confirm],
                         [version_log, version_pick, version_delete_confirm], concurrency_id="review")
    long_action(version_save, stop_version, busy_version, do_version, [project, char],
                [version_log, version_pick, undo_st], version_log)
    restored = long_action(version_restore, stop_version, busy_version, do_restore_version,
                           [project, char, version_pick], [version_log, version_pick, undo_st], version_log) \
        .success(L(change_char), [project, char], [r_filter, move_to, *rv_out])
    r_filter.change(L(load_review), [project, char, r_filter], rv_out)
    r_gal.select(L(select_image), [project, char, files_st], rv_out, show_progress="hidden")
    prev_btn.click(L(step(-1)), [project, char, files_st, idx_st], rv_out, show_progress="hidden")
    next_btn.click(L(step(+1)), [project, char, files_st, idx_st], rv_out, show_progress="hidden")
    trash_in = [project, char, r_filter, files_st, idx_st, undo_st]
    del_btn.click(L(delete_image), [*trash_in, r_picked], [*rv_out, undo_st, r_filter], concurrency_id="review",
                  js=TAKE_PICKED)
    rejected = reject_btn.click(L(reject_image), [*trash_in, r_picked], [*rv_out, undo_st, r_filter],
                                concurrency_id="review", js=TAKE_PICKED)
    undone = undo_btn.click(L(undo_delete), trash_in, [*rv_out, undo_st, r_filter], concurrency_id="review")
    forgotten = forget_btn.click(L(forget_rejected), [project, char, r_filter, files_st, idx_st], [*rv_out, r_filter],
                                 concurrency_id="review")
    confirmed = confirm_btn.click(L(confirm_image), [project, char, r_filter, files_st, idx_st, r_picked],
                                  [*rv_out, r_filter], concurrency_id="review", js=TAKE_PICKED)
    unconfirmed = unconfirm_btn.click(L(unconfirm_image), [project, char, r_filter, files_st, idx_st, confirmed_pick],
                                      [*rv_out, r_filter], concurrency_id="review")
    confirmed_out = [confirmed_pick, confirmed_thumb]
    impact_out = [impact_summary, impact_table, impact_gal, impact_state]
    for event in (built, restored, rejected, undone, forgotten, confirmed, unconfirmed, scanned, autoskipped,
                  reclustered, split):
        event.success(L(confirmed_view), [project, char], confirmed_out)
        event.success(L(clear_impact), None, impact_out, concurrency_id="gpu")
        event.success(L(clear_preview), None, preview_out, concurrency_id="gpu")
    for control in (project, char):
        control.change(L(confirmed_view), [project, char], confirmed_out)
        control.change(L(clear_impact), None, impact_out, concurrency_id="gpu")
    confirmed_pick.change(L(confirmed_image), [project, char, confirmed_pick], confirmed_thumb)
    long_action(impact_btn, stop_impact, busy_impact, do_feedback_preview, [project, char],
                [impact_summary, impact_table, impact_gal, impact_state])
    move_btn.click(L(move_image), [project, char, r_filter, files_st, idx_st, move_to, r_picked], rv_out,
                   concurrency_id="review", js=TAKE_PICKED)
    save_btn.click(L(save_caption), [project, char, files_st, idx_st, r_caption], None, concurrency_id="review")

    t_out = [t_table, t_status, t_selected]
    g_out = [t_goal_tags, t_goal_legend, t_box, t_box_note]
    char.change(L(tag_views), [project, char, t_search, t_goal], [*t_out, *g_out])
    t_goal.change(L(goal_view), [project, char, t_goal], g_out)
    t_search.change(L(tag_search), [project, char, t_search, t_selected], t_out)
    t_table.select(pick_tag, t_selected, t_selected)
    t_remove_btn.click(L(tag_remove), [project, char, t_selected, t_search, t_goal], [*t_out, *g_out],
                       concurrency_id="review")
    t_replace_btn.click(L(tag_replace), [project, char, t_selected, t_new, t_search, t_goal], [*t_out, *g_out],
                        concurrency_id="review")
    t_add_btn.click(L(tag_add), [project, char, t_add_text, t_search, t_goal], [*t_out, *g_out],
                    concurrency_id="review")
    t_absorb_btn.click(L(tag_absorb), [project, char, t_goal_tags, t_search, t_goal], [*t_out, *g_out],
                       concurrency_id="review")
    t_absorb_sel_btn.click(L(tag_absorb), [project, char, t_selected, t_search, t_goal], [*t_out, *g_out],
                           concurrency_id="review")
    t_restore_btn.click(L(tag_restore), [project, char, t_box, t_search, t_goal], [*t_out, *g_out],
                        concurrency_id="review")
    t_undo_btn.click(L(tag_undo), [project, char, t_search, t_goal], [*t_out, *g_out], concurrency_id="review")
    t_outfits_btn.click(L(rerun_outfits), [project, char, t_search, t_goal], [*t_out, *g_out, t_log],
                        concurrency_id="review")

    sum_in, sum_out = [project, char, e_out], [e_summary, groups_df]
    char.change(L(save_summary), sum_in, sum_out)
    e_out.change(L(save_summary), sum_in, sum_out)
    e_browse.click(L(browse_save_dir), e_out, e_out, concurrency_id="dialog")
    tabs.select(L(save_summary), sum_in, sum_out)
    tabs.select(L(delete_hint), project, del_hint)
    project.change(L(delete_hint), project, del_hint)
    tabs.select(L(tag_views), [project, char, t_search, t_goal], [*t_out, *g_out])
    for event in (project_loaded, list_refreshed):
        event.then(L(change_char), [project, char], [r_filter, move_to, *rv_out]) \
            .then(L(version_choices), [project, char], version_pick) \
            .then(L(tag_views), [project, char, t_search, t_goal], [*t_out, *g_out]) \
            .then(L(save_summary), sum_in, sum_out)
    long_action(export_btn, stop_export, busy_export, do_save, [project, char, e_out], [export_log], export_log) \
        .success(L(delete_hint), project, del_hint)
    del_project_btn.click(L(delete_project), [project, del_confirm], [project, del_confirm], concurrency_id="gpu")

    texts = static_texts(demo)
    for block, props in ((title, {"value": lambda: title_md(gpu)}), (lang_btn, {"value": other_language}),
                         (opts, {"choices": build_options}), (upscaler, {"choices": upscaler_choices}),
                         (t_goal, {"choices": goal_choices}),
                         (upscale_version, {"choices": model_version_choices})):
        texts.setdefault(block._id, (block, {}))[1].update(props)
    refreshed = [vids_df, clusters_gal, usage, r_filter, move_to, r_info, r_stats, t_table, t_status, t_goal_legend,
                 t_box_note, e_summary, groups_df, del_hint, version_pick, version_diff, preview_gal,
                 preview_summary, impact_summary, impact_table, impact_gal, model_info, name_info]
    switch_outputs = [block for block, _ in texts.values()] + [b for b in refreshed if b._id not in texts]
    tab_names = [(props["label"], AR[props["label"]]) for block, props in texts.values()
                 if isinstance(block, gr.Tab)]
    set_direction = "(v) => window.aldsSwitch(v)"

    def page_language(language):
        return json.dumps({"lang": language, "tabs": tab_names}, ensure_ascii=False)

    def init_page(p):
        _session_langs[_session()] = lang()
        names = projects()
        p = p if p in names else (names[0] if names else p)
        return (page_language(lang()), title_md(gpu), gr.update(choices=names, value=p), *load_project(p))

    demo.load(L(init_page), project, [lang_box, title, project, *proj_outputs]).then(None, lang_box, None,
                                                                                    js=set_direction)

    def switch_language(pname, char, files, idx, query, goal, parent, version, preview, impact, upscale_on, model,
                        upscale_version, trigger):
        from .aitk import save_settings
        new = "en" if lang() == "ar" else "ar"
        _session_langs[_session()] = new
        save_settings(ui_lang=new)
        apply_texts(texts, new)
        demo.config = demo.get_config_file()
        with use(new):
            updates = {block._id: {prop: translated(text) for prop, text in props.items()}
                       for block, props in texts.values()}
            rows, status, _ = _tag_state(pname, char, query)
            _, _, legend, _, box_note = _goal_state(pname, char, goal)
            summary, groups = save_summary(pname, char, parent)
            preview_images, preview_text = preview_view(preview)
            impact_text, impact_rows = impact_view(impact)
            for block, kw in ((vids_df, {"value": videos_table(pname)}),
                              (clusters_gal, {"value": clusters_view(pname)[0]}),
                              (usage, {"value": usage_md(pname)}),
                              (r_filter, {"choices": filter_choices(pname, char)}),
                              (move_to, {"choices": move_choices()}),
                              (r_info, {"value": panel(pname, char, files, idx)[2]}),
                              (r_stats, {"value": stats_text(pname, char)}),
                              (t_table, {"value": table(rows, TAG_COLUMNS)}),
                              (t_status, {"value": status}),
                              (t_goal_legend, {"value": legend}),
                              (t_box_note, {"value": box_note}),
                              (e_summary, {"value": summary}),
                              (groups_df, {"value": groups}),
                              (del_hint, {"value": delete_hint(pname)}),
                              (version_pick, {"choices": version_choices(pname, char)["choices"], "value": version}),
                              (version_diff, {"value": version_comparison(pname, char, version)}),
                              (preview_gal, {"value": preview_images}),
                              (preview_summary, {"value": preview_text}),
                              (impact_summary, {"value": impact_text}),
                              (impact_table, {"value": impact_rows}),
                              (impact_gal, {"value": impact_images(impact)}),
                              (model_info, {"value": model_status(model, upscale_version) if upscale_on else ""}),
                              (name_info, {"value": name_note(pname, trigger)})):
                updates.setdefault(block._id, {}).update(kw)
        return [page_language(new)] + [gr.update(**updates[block._id]) for block in switch_outputs]

    lang_btn.click(L(switch_language), [project, char, files_st, idx_st, t_search, t_goal, e_out, version_pick,
                                      preview_state, impact_state, upscale_on, upscaler, upscale_version, name],
                   [lang_box, *switch_outputs]).then(None, lang_box, None, js=set_direction)
    return texts


def launch(port=7860, open_browser=True):
    import webbrowser
    from .common import setup_runtime
    from .updates import start as check_for_updates
    setup_runtime()
    check_for_updates()
    PROJECTS_DIR.mkdir(exist_ok=True)
    language = saved_lang()
    demo = build_ui(language)
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=port, inbrowser=False, prevent_thread_lock=True, footer_links=[],
        allowed_paths=[str(PROJECTS_DIR)], theme=gr.themes.Soft(), css=CSS,
        head=HEAD.replace("__LANG__", language).replace("__MODEL_INFO__", model_info_json()))
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    demo.block_thread()
