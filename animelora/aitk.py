import json
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
MARKER = ".animelora"
SETTINGS = ROOT / "settings.json"
QUALITY = "masterpiece, best quality, score_7"


def js_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def schedule(n_images: int, resolutions, epochs: int = 40) -> dict:
    exact = n_images * len(resolutions) * 10 / GA
    save = max(1, js_round(exact))
    points = epochs // 10
    return {"resolutions": list(resolutions), "epochs": epochs, "save_every": save, "steps": save * points,
            "keep": points, "exact_save": exact}


def schedule_notes(s) -> list:
    notes = []
    if s["steps"] <= WARMUP:
        notes.append(f"! warmup never finishes: {s['steps']} steps <= {WARMUP}, lr never reaches 0.00002.")
    elif (pct := round(WARMUP / s["steps"] * 100)) >= 20:
        notes.append(f"! warmup takes {pct}% of training; if the last checkpoint lacks identity, train 60 epochs.")
    if abs(s["exact_save"] - s["save_every"]) > 1e-9:
        notes.append(f"save_every {s['exact_save']:g} rounded to {s['save_every']} so the last checkpoint is the "
                     "last step.")
    if 1536 in s["resolutions"]:
        notes.append("! 1536 enabled: only useful if images are >= 1536 px (AI Toolkit doesn't upscale).")
    if 768 in s["resolutions"]:
        notes.append("! 768 is not in the official recipe (512 + 1024).")
    if 1024 not in s["resolutions"]:
        notes.append("! 1024 is off; the official recipe mixes 512 and 1024.")
    return notes


def sample_prompts(count_tag: str, series=None, outfit_tokens=()) -> list:
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
                outfit_tokens=()) -> dict:
    cfg = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
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
    c = Counter(t for cap in captions for t in cap if re.fullmatch(r"1(girl|boy|other)", t))
    return c.most_common(1)[0][0] if c else "1girl"


def next_job_name(base: str, aitk_root: Path) -> str:
    taken = set()
    for d in (aitk_root / "output", aitk_root / "config"):
        if d.exists():
            taken |= {p.stem.lower() for p in d.iterdir()}
    n = 1
    while f"{base}_v{n}".lower() in taken:
        n += 1
    return f"{base}_v{n}"


def check_dataset_dir(path: Path):
    if path.exists() and any(path.iterdir()) and not (path / MARKER).exists():
        raise SystemExit(f"dataset folder {path} already exists and was not made by animelora - "
                         "pick another dataset name so it isn't overwritten")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    s = load_settings()
    s.update(kw)
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
