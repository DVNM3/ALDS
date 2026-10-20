import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path

from . import __version__, common

PACKAGES = ("dghs-imgutils", "onnxruntime-gpu", "av", "gradio", "scikit-learn")
MARK = {"ok": "[ok]     ", "warn": "[warning]", "fail": "[failed] "}
NAME = "selftest"
WINDOW = 150.0
MIN_FREE_GB = 10


def gpu_name():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = out.stdout.strip().splitlines()
    return lines[0].strip() if out.returncode == 0 and lines else None


def environment():
    rows = [("ALDS", __version__, "ok"),
            ("Python", sys.version.split()[0], "ok" if sys.version_info[:2] == (3, 12) else "warn")]
    for name in PACKAGES:
        try:
            rows.append((name, metadata.version(name), "ok"))
        except metadata.PackageNotFoundError:
            rows.append((name, "missing: run setup.bat", "fail"))
    gpu = gpu_name()
    rows.append(("Graphics card", gpu or "no NVIDIA card found: everything runs on the processor, slowly",
                 "ok" if gpu else "warn"))
    try:
        import onnxruntime as ort
        try:
            ort.preload_dlls()
        except Exception:
            pass
        cuda = "CUDAExecutionProvider" in ort.get_available_providers()
        rows.append(("CUDA for the models", "available" if cuda else "not available: the models use the processor",
                     "ok" if cuda else "warn"))
    except ImportError:
        rows.append(("CUDA for the models", "onnxruntime is missing", "fail"))
    try:
        import av
        rows.append(("Video decoding", "HEVC and H.264" if {"hevc", "h264"} <= set(av.codecs_available)
                     else "some codecs are missing", "ok" if {"hevc", "h264"} <= set(av.codecs_available) else "warn"))
    except ImportError:
        rows.append(("Video decoding", "PyAV is missing", "fail"))
    try:
        import tkinter
        rows.append(("Windows file window", "available", "ok"))
    except ImportError:
        rows.append(("Windows file window", "tkinter is missing: drop the files on the page instead", "warn"))
    folder = common.PROJECTS_DIR if common.PROJECTS_DIR.exists() else common.ROOT
    free = shutil.disk_usage(folder).free / 1e9
    rows.append(("Free disk space", f"{free:.0f} GB", "ok" if free >= MIN_FREE_GB else "warn"))
    return rows


def print_rows(rows):
    width = max(len(name) for name, _, _ in rows)
    for name, value, state in rows:
        print(f"  {MARK[state]} {name.ljust(width)}  {value}")


def run_check():
    print(f"ALDS {__version__}: checking the setup")
    rows = environment()
    print_rows(rows)
    failed = any(state == "fail" for _, _, state in rows)
    print("\n" + ("Something is missing: run setup.bat again." if failed else "The setup is ready."))
    return 1 if failed else 0


def known_episodes():
    found = []
    if common.PROJECTS_DIR.exists():
        for project in sorted(common.PROJECTS_DIR.iterdir()):
            for video in common.load_json(project / "project.json", {}).get("videos", []):
                if Path(video["path"]).is_file():
                    found.append((video.get("duration") or 0, Path(video["path"])))
    return [path for _, path in sorted(found)]


def pick_video(video):
    if video:
        path = Path(video.strip().strip('"'))
        if not path.is_file():
            raise SystemExit(f"not found: {path}")
        return path
    episodes = known_episodes()
    if not episodes:
        raise SystemExit('give an episode to test with, e.g.  alds.bat selftest "D:\\anime\\episode.mkv"')
    return episodes[0]


def window_for(video):
    import av
    with av.open(str(video)) as container:
        duration = container.duration / av.time_base if container.duration else 0
    if not duration or duration <= WINDOW * 1.5:
        return (0.0, None), duration
    start = round(duration * 0.35, 1)
    return (start, start + WINDOW), duration


class Steps:
    def __init__(self):
        self.rows = []

    @contextlib.contextmanager
    def step(self, name):
        log = io.StringIO()
        began = time.perf_counter()
        print(f"  ... {name}", end="", flush=True)
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                yield
        except BaseException as e:
            seconds = time.perf_counter() - began
            print(f"\r  {MARK['fail']} {name} ({seconds:.0f} s)")
            tail = "\n".join(log.getvalue().strip().splitlines()[-12:])
            if tail:
                print("      " + tail.replace("\n", "\n      "))
            print(f"      {type(e).__name__}: {e}")
            self.rows.append((name, seconds, "fail"))
            raise
        seconds = time.perf_counter() - began
        print(f"\r  {MARK['ok']} {name} ({seconds:.0f} s)")
        self.rows.append((name, seconds, "ok"))

    def skip(self, name, reason):
        print(f"  {MARK['warn']} {name}: {reason}")
        self.rows.append((name, 0.0, "warn"))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def captions(char_dir):
    return {p.stem: p.with_suffix(".txt").read_text(encoding="utf-8")
            for p in (char_dir / "sorted").rglob("*.png")}


def pipeline(steps, video, tmp):
    from . import negatives, positives, txn
    from .build import run_build
    from .captions import tag_category
    from .export import run_export
    from .outfits import absorb_captions, restore_captions
    from .pick import sync_images
    from .scan import run_scan
    from .tags import split_tags
    from .versions import list_versions, save_version

    project = common.Project(NAME)
    window, duration = window_for(video)
    part = "whole episode" if window[1] is None else f"part from {common.mmss(window[0])} to {common.mmss(window[1])}"
    print(f"\nEpisode: {video.name} ({duration / 60:.1f} min, scanning the {part})")

    with steps.step("Scan the episode and group the characters"):
        run_scan(project, [str(video)], [], 0.35, 5.0, auto_skip=False, window=window)
        clusters = (project.load("scan/clusters.json") or {}).get("clusters", [])
        check(clusters, "no character was found in this part of the episode; try another episode")
    biggest = max(clusters, key=lambda c: len(c["members"]))
    frames, dets = project.load("scan/frames.json"), project.load("scan/detections.json")
    own_source = tmp / "own" / "my_image.jpg"
    own_source.parent.mkdir()
    shutil.copy2(project.path(frames[dets[biggest["members"][0]]["frame"]]["file"]), own_source)

    char_dir = project.char_dir(NAME)
    with steps.step(f"Build the image set (cluster #{biggest['id']}, {len(biggest['members'])} views, "
                    "with one image of your own)"):
        with txn.build_txn(project, NAME):
            sync_images(char_dir / common.OWN_IMAGES, [own_source])
            run_build(project, NAME, [biggest["id"]], None, 0.13, 1.0, 0.5, 0.8, None, True, "EVA02_Large",
                      False, False, False, True, own_dir=char_dir / common.OWN_IMAGES)

    with steps.step("Check the images and captions"):
        pngs = sorted((char_dir / "sorted").rglob("*.png"))
        check(pngs, "the build made no images")
        check(all(p.with_suffix(".txt").exists() for p in pngs), "an image has no caption file")
        check(all(NAME in split_tags(text) for text in captions(char_dir).values()),
              "a caption is missing the trigger word")
        check(any(p.stem.startswith("own_") for p in pngs), "your own image is missing from the set")

    with steps.step("Review: confirm, reject and delete, then undo each"):
        before = captions(char_dir)
        check(len(pngs) >= 3, "too few images to test the review")
        first, second, third = pngs[:3]
        check(positives.confirm(char_dir, first), "confirming an image failed")
        rejected = positives.reject_image(char_dir, second)
        check(rejected is not None and second.stem in negatives.load(char_dir)[0], "rejecting an image failed")
        deleted = negatives.trash(char_dir, third)
        positives.remove(char_dir, first.stem)
        positives.unreject(char_dir, rejected, second.parent)
        negatives.move_pair(deleted, third.parent)
        check(captions(char_dir) == before, "undoing the review didn't bring every image back")
        check(not negatives.load(char_dir)[0] and not positives.load(char_dir)[0],
              "undoing the review left a confirmation or a rejection behind")

    with steps.step("Tags: move a tag into the trigger word and put it back"):
        before = captions(char_dir)
        counts = {}
        for text in before.values():
            for tag in split_tags(text):
                if tag_category(tag) == "hair_colour":
                    counts[tag] = counts.get(tag, 0) + 1
        tag = max(counts, key=counts.get) if counts else next(
            t for t in split_tags(next(iter(before.values()))) if t != NAME)
        check(absorb_captions(project, NAME, [tag]), f"moving “{tag}” changed no caption")
        check(all(tag not in split_tags(text) for text in captions(char_dir).values()), f"“{tag}” is still there")
        restore_captions(project, NAME, [tag])
        check(captions(char_dir) == before, "putting the tag back didn't restore the captions exactly")

    with steps.step("Save a version"):
        save_version(project, NAME)
        check(len(list_versions(project, NAME)) == 1, "the version wasn't saved")

    with steps.step("Save the images and captions to a folder"):
        out = tmp / "dataset" / NAME
        run_export(project, NAME, str(out))
        check(len(list(out.glob("*.png"))) == len(pngs) == len(list(out.glob("*.txt"))),
              "the saved folder doesn't have every image with its caption")


def upscaler(steps, tmp):
    from PIL import Image
    from .upscale import DEFAULT, LABELS, downloaded_size, upscale_image
    if not downloaded_size(DEFAULT):
        steps.skip("Upscaler", f"{LABELS[DEFAULT].split(' (')[0]} isn't downloaded, so it wasn't tested")
        return
    with steps.step("Upscaler: enlarge a small image twice"):
        image = Image.new("RGB", (160, 90), (180, 120, 200))
        big = upscale_image(image, 2.0, DEFAULT)
        check(big.size == (320, 180), f"the enlarged image is {big.size}, not (320, 180)")


def run_selftest(video=None, keep=False):
    print(f"ALDS {__version__}: self-test")
    rows = environment()
    print_rows(rows)
    if any(state == "fail" for _, _, state in rows):
        print("\nSomething is missing: run setup.bat again.")
        return 1
    video = pick_video(video)
    tmp = Path(tempfile.mkdtemp(prefix="alds-selftest-"))
    root, common.PROJECTS_DIR = common.PROJECTS_DIR, tmp / "projects"
    steps = Steps()
    began = time.perf_counter()
    try:
        pipeline(steps, video, tmp)
        upscaler(steps, tmp)
        failed = False
    except BaseException as e:
        failed = True
        if isinstance(e, KeyboardInterrupt):
            print("\nStopped.")
    finally:
        common.PROJECTS_DIR = root
        common.release_models()
        if keep:
            print(f"\nThe test files are kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    total = time.perf_counter() - began
    print(f"\n{'Something failed: see the step marked [failed] above.' if failed else 'Everything works.'} "
          f"({total / 60:.1f} min)")
    return 1 if failed else 0
