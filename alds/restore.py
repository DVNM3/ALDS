from pathlib import Path
from tempfile import TemporaryDirectory

import av
from tqdm import tqdm

from .cache import file_hash
from .cancel import check as check_cancel
from .common import inside
from .extract import frame_time, save_frame, stream_info
from .txn import Transaction


def _frame_path(project, frame):
    rel = Path(frame["file"])
    path = project.path(rel)
    if rel.is_absolute() or ".." in rel.parts or not inside(path, project.frames_dir):
        raise SystemExit("invalid frame path in scan data")
    return path.resolve()


def restore_frames(project, videos_dir=None):
    info = project.load("project.json")
    frames = project.load("scan/frames.json", [])
    dets = project.load("scan/detections.json", [])
    if not info or not frames or not dets:
        raise SystemExit("nothing scanned yet - run scan first")
    needed = sorted({d["frame"] for d in dets if d["feat"] >= 0 and not frames[d["frame"]].get("auto")})
    groups = {}
    for index in needed:
        frame = frames[index]
        if not _frame_path(project, frame).exists():
            groups.setdefault(frame["vid"], []).append(frame)
    videos = {v["id"]: v for v in info["videos"]}
    sources, hashes = {}, {}
    for vid in groups:
        v = videos[vid]
        source = Path(v["path"])
        if videos_dir:
            source = Path(videos_dir) / source.name
        if not source.is_file():
            raise SystemExit(f"original episode not found: {source}; use --videos-dir to locate moved episodes")
        with av.open(str(source)) as container:
            fps, duration, width, height = stream_info(container, container.streams.video[0])
        if ((width, height) != (v["width"], v["height"]) or abs(fps - v["fps"]) > 0.02
                or (duration and abs(duration - v["duration"]) > 0.2)):
            raise SystemExit(f"episode does not match the original scan: {source}")
        hashes[vid] = file_hash(source)
        if v.get("source_sha256") and hashes[vid] != v["source_sha256"]:
            raise SystemExit(f"episode does not match the original scan: {source}")
        sources[vid] = source.resolve()

    installed, created_dirs = [], set()
    try:
        with TemporaryDirectory(prefix=".restore-", dir=project.dir) as tmp:
            stage = Path(tmp)
            for vid, wanted in groups.items():
                by_number = {f["n"]: f for f in wanted}
                remaining = set(by_number)
                with av.open(str(sources[vid])) as container:
                    stream = container.streams.video[0]
                    stream.thread_type = "AUTO"
                    fps = stream_info(container, stream)[0]
                    for n, frame in enumerate(tqdm(container.decode(stream), desc="  restore", unit="f")):
                        check_cancel()
                        if n not in by_number:
                            continue
                        saved = by_number[n]
                        if abs(frame_time(frame, n, fps) - saved["t"]) > 0.002:
                            raise SystemExit(f"frame timing differs from the original scan: {sources[vid]}")
                        target = stage / saved["file"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        save_frame(frame, target)
                        remaining.remove(n)
                        if not remaining:
                            break
                if remaining:
                    raise SystemExit(f"episode ended before all frames were restored: {sources[vid]}")
            with Transaction(project.dir, keep=[project.path("project.json"), project.path("scan/frames.json")],
                             remove_if_new=[project.frames_dir]):
                for wanted in groups.values():
                    for frame in wanted:
                        check_cancel()
                        dest = _frame_path(project, frame)
                        if dest.exists():
                            raise SystemExit(f"frame appeared during restore: {dest}")
                        parent = dest.parent
                        while not parent.exists() and parent.is_relative_to(project.frames_dir):
                            created_dirs.add(parent)
                            parent = parent.parent
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        (stage / frame["file"]).rename(dest)
                        installed.append(dest)
                check_cancel()
                for vid, source in sources.items():
                    videos[vid]["path"] = str(source)
                    videos[vid]["source_sha256"] = hashes[vid]
                if [i for i in needed if frames[i].pop("deleted", None) is not None]:
                    project.save("scan/frames.json", frames)
                info["frames_deleted"] = False
                project.save("project.json", info)
    except BaseException:
        for path in installed:
            path.unlink(missing_ok=True)
        for path in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
            if path.exists():
                path.rmdir()
        raise
    print(f"[restore] restored {len(installed)} missing frames; builds and clustering are available again")
    return len(installed)
