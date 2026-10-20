from pathlib import Path

import av
import numpy as np
from tqdm import tqdm

from .cancel import check as check_cancel
from .i18n import t
from .repeats import Fingerprinter


def save_frame(frame, path):
    frame.to_image().save(path, quality=95, subsampling=0)


def stream_info(container, stream):
    fps = float(stream.average_rate or stream.guessed_rate or 24)
    duration = container.duration / av.time_base if container.duration else None
    return fps, duration, stream.codec_context.width, stream.codec_context.height


def frame_time(frame, n, fps):
    return float(frame.time) if frame.time is not None else n / fps


def extract_frames(video_path: Path, out_dir: Path, rel_prefix: str, skip=(),
                   min_gap=0.35, keep_diff=5.0, cut_diff=30.0, settle=2, flat_std=6.0, keep=save_frame,
                   start=0.0, until=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        fps, duration, width, height = stream_info(container, stream)
        total = stream.frames or (int(duration * fps) if duration else None)
        info = {"fps": round(fps, 3), "duration": round(duration or 0, 1), "width": width, "height": height}

        fp = Fingerprinter()
        prev = last_kept = None
        last_kept_t, last_kept_shot = -1e9, -1
        shot, since_cut = 0, 0
        if start:
            container.seek(int(start / stream.time_base), stream=stream)
        for n, frame in enumerate(tqdm(container.decode(stream), total=total, unit=t("frames"),
                                       desc=t("Reading the episode"), leave=False)):
            check_cancel()
            at = frame_time(frame, n, fps)
            if until is not None and at >= until:
                break
            if at < start:
                continue
            thumb = frame.reformat(width=64, height=36, format="gray").to_ndarray().astype(np.float32)
            fp.add(at, thumb)
            if any(a <= at < b for a, b in skip):
                prev = None
                continue
            if prev is None or np.abs(thumb - prev).mean() > cut_diff:
                shot += 1
                since_cut = 0
            else:
                since_cut += 1
            prev = thumb

            if thumb.std() < flat_std or since_cut < settle or at - last_kept_t < min_gap:
                continue
            if last_kept_shot == shot and np.abs(thumb - last_kept).mean() < keep_diff:
                continue

            name = f"{n:06d}.jpg"
            keep(frame, out_dir / name)
            frames.append({"n": n, "t": round(at, 3), "shot": shot, "file": f"{rel_prefix}/{name}"})
            last_kept, last_kept_t, last_kept_shot = thumb, at, shot
    info["shots"] = shot
    return frames, info, fp.result()
