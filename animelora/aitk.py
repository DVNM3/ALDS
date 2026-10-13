"""AI Toolkit job config for Anima.

The schedule follows the user's anima-lora-calculator.html (Anima developer's recipe):
    gradient accumulation 4, batch 1, warmup 100 steps, a checkpoint every 10 epochs
    save_every = round(images x resolutions x 10 / 4)      (JS Math.round: halves round up)
    steps      = save_every x epochs / 10                  (so the last checkpoint lands on the last step)
    sample_every = save_every, max_step_saves_to_keep = epochs / 10
Everything else comes from the template (aitk_template.yaml, a copy of the user's settings file).
"""
import math
import re
from collections import Counter
from pathlib import Path

import yaml

from .common import ROOT

GA = 4
WARMUP = 100
TEMPLATE = Path(__file__).with_name("aitk_template.yaml")
DEFAULT_RES = (512, 1024)
EPOCH_CHOICES = (40, 50, 60)
MARKER = ".animelora"  # put in dataset folders we create, so we never overwrite someone else's dataset
SETTINGS = ROOT / "settings.json"
QUALITY = "masterpiece, best quality, score_7"


def js_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def schedule(n_images: int, resolutions, epochs: int = 40) -> dict:
    R = len(resolutions)
    exact = n_images * R * 10 / GA
    save = max(1, js_round(exact))
    points = epochs // 10
    return {"images": n_images, "resolutions": list(resolutions), "epochs": epochs, "save_every": save,
            "steps": save * points, "keep": points, "exact_save": exact, "per_epoch": n_images * R / GA,
            "views": R * epochs}


def schedule_notes(s, lang="ar") -> list:
    """The calculator's warnings (Arabic for the GUI, English for the console)."""
    ar = lang == "ar"
    notes = []
    if s["steps"] <= WARMUP:
        notes.append(f"⚠ الـ warmup لن يكتمل: عدد الخطوات ({s['steps']}) لا يتجاوز {WARMUP}، فلن يصل معدل التعلم "
                     "إلى 0.00002 خلال التدريب." if ar else
                     f"! warmup never finishes: {s['steps']} steps <= {WARMUP}, lr never reaches 0.00002.")
    else:
        pct = round(WARMUP / s["steps"] * 100)
        if pct >= 20:
            notes.append(f"⚠ الـ warmup يأخذ {pct}% من التدريب. إن جاء آخر checkpoint ناقص الهوية فدرّب 60 epoch."
                         if ar else f"! warmup takes {pct}% of training; if the last checkpoint lacks identity, "
                                    "train 60 epochs.")
    if abs(s["exact_save"] - s["save_every"]) > 1e-9:
        notes.append(f"Save Every الدقيق {s['exact_save']:g} وقُرّب إلى {s['save_every']} ليقع آخر checkpoint على "
                     "آخر خطوة." if ar else
                     f"save_every {s['exact_save']:g} rounded to {s['save_every']} so the last checkpoint is the last step.")
    if 1536 in s["resolutions"]:
        notes.append("⚠ 1536 مفعّلة: لا تفعّلها إلا إن كانت صورك 1536 بكسل أو أكبر. AI Toolkit لا يكبّر الصور، "
                     "فالأصغر منها لا تُدرَّب على 1536." if ar else
                     "! 1536 enabled: only useful if images are >= 1536 px (AI Toolkit doesn't upscale).")
    if 768 in s["resolutions"]:
        notes.append("⚠ 768 ليست ضمن الوصفة الرسمية (512 و1024)." if ar else
                     "! 768 is not in the official recipe (512 + 1024).")
    if 1024 not in s["resolutions"]:
        notes.append("⚠ 1024 غير مفعّلة، والوصفة الرسمية تعتمد المزج بين 512 و1024." if ar else
                     "! 1024 is off; the official recipe mixes 512 and 1024.")
    return notes


def sample_prompts(count_tag: str, series=None, outfit_tokens=()) -> list:
    """Same shape as the user's template prompts, without the template character's specifics: two with the
    trigger, one per outfit token (up to 2), and one without the trigger to compare against the base model."""
    who = f"{count_tag}, [trigger]" + (f", {series}" if series else "")
    prompts = [f"{QUALITY}, {who}, solo, upper body, looking at viewer, smile, white background",
               f"{QUALITY}, {who}, solo, full body, from side, walking, outdoors, street, day"]
    for token in list(outfit_tokens)[:2]:
        prompts.append(f"{QUALITY}, {count_tag}, [trigger], {token}" + (f", {series}" if series else "")
                       + ", solo, cowboy shot, standing, looking at viewer, outdoors")
    if len(prompts) == 2:
        prompts.append(f"{QUALITY}, {who}, solo, portrait, looking to the side, closed mouth, simple background")
    prompts.append(f"{QUALITY}, {count_tag}, solo, upper body, looking at viewer, smile, white background")
    return [{"prompt": p} for p in prompts]


def make_config(job_name, trigger, dataset_path, training_folder, sched, count_tag="1girl", series=None,
                outfit_tokens=(), template=None) -> dict:
    cfg = yaml.safe_load(Path(template or TEMPLATE).read_text(encoding="utf-8"))
    cfg["config"]["name"] = job_name
    p = cfg["config"]["process"][0]
    p["training_folder"] = str(training_folder)
    p["trigger_word"] = trigger
    ds = p["datasets"][0]
    ds["folder_path"] = str(dataset_path)
    ds["resolution"] = list(sched["resolutions"])
    t = p["train"]
    t["batch_size"] = 1
    t["gradient_accumulation"] = GA
    t["steps"] = sched["steps"]
    t.setdefault("lr_scheduler_params", {})["num_warmup_steps"] = WARMUP
    p["save"]["save_every"] = sched["save_every"]
    p["save"]["max_step_saves_to_keep"] = sched["keep"]
    p["sample"]["sample_every"] = sched["save_every"]
    p["sample"]["samples"] = sample_prompts(count_tag, series, outfit_tokens)
    return cfg


def dump(cfg) -> str:
    return yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, explicit_start=True, width=200)


def count_tag_of(captions) -> str:
    """Most common 1girl / 1boy / 1other tag in the captions (the sample prompts need one)."""
    c = Counter(t for cap in captions for t in cap if re.fullmatch(r"1(girl|boy|other)", t))
    return c.most_common(1)[0][0] if c else "1girl"


def next_job_name(base: str, aitk_root: Path) -> str:
    """<Base>_v<n> with n one past the highest existing output/config version."""
    taken = set()
    for d in (aitk_root / "output", aitk_root / "config"):
        if d.exists():
            taken |= {p.stem.lower() for p in d.iterdir()}
    n = 1
    while f"{base}_v{n}".lower() in taken:
        n += 1
    return f"{base}_v{n}"


def check_dataset_dir(path: Path):
    """Refuse to export into an existing, non-empty dataset folder that animelora didn't create."""
    if path.exists() and any(path.iterdir()) and not (path / MARKER).exists():
        raise SystemExit(f"dataset folder {path} already exists and was not made by animelora - "
                         "pick another dataset name so it isn't overwritten")


def load_settings() -> dict:
    import json
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    import json
    s = load_settings()
    s.update(kw)
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
