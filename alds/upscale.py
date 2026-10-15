import functools
import os

import numpy as np
from PIL import Image

from .cancel import check as check_cancel

AUTO_TEXT = "Automatic uses 2x for enlargements up to double and 4x above."
TILE = 256
MARGIN = 16
MIN_FACTOR = 1.15
DEFAULT = "waifu2x"
MODELS = {
    "waifu2x": {2: ("deepghs/waifu2x_onnx", "20230131/onnx_models/swin_unet/art/noise1_scale2x.onnx", 8),
                4: ("deepghs/waifu2x_onnx", "20230131/onnx_models/swin_unet/art/noise1_scale4x.onnx", 8)},
    "animevideov3": {4: ("skillsafe-ai/realesr-animevideov3", "model.onnx", 0)},
    "animesharp": {2: ("Kim2091/AnimeSharpV3", "2x-AnimeSharpV3-fp16.onnx", 0),
                   4: ("Kim2091/AnimeSharp", "ONNX/4x-AnimeSharp-fp16-opset17.onnx", 0)},
    "apisr": {2: ("Xenova/2x_APISR_RRDB_GAN_generator-onnx", "onnx/model.onnx", 0),
              4: ("Xenova/4x_APISR_GRL_GAN_generator-onnx", "onnx/model.onnx", 0)},
    "cdc": {4: None},
}
LABELS = {"waifu2x": "waifu2x (closest to the original)", "animevideov3": "Real-ESRGAN animevideov3 (crisper lines)",
          "animesharp": "AnimeSharp (sharp)", "apisr": "APISR (redraws lines, changes the style)",
          "cdc": "CDC (adds grain, can distort details)"}
CDC_FILE = ("deepghs/cdc_anime_onnx", "HGSR-MHR-anime-aug_X4_320.onnx")
INFO = {
    "waifu2x": "waifu2x (swin_unet, art) by nagadomi, the ONNX version published by deepghs. It enlarges without "
               "redrawing: it removes compression noise and sharpens the least, so the scene looks like the "
               "original. Recommended. Two versions, 2x (17 MB) and 4x (19 MB); " + AUTO_TEXT + " License: MIT.",
    "animevideov3": "Real-ESRGAN animevideov3 by Tencent ARC, made for anime video; ONNX conversion from Hugging Face "
                    "(the original is a PyTorch file). Cleaner, slightly crisper lines than waifu2x and the "
                    "fastest. 4x only, 2.5 MB to download. License: BSD-3-Clause.",
    "animesharp": "AnimeSharp by Kim2091, from the author's own page. It sharpens lines strongly, which can look "
                  "too sharp on soft anime. Two versions, 2x (V3, 34 MB) and 4x (34 MB); " + AUTO_TEXT + " License: "
                  "CC BY-NC-SA 4.0, non-commercial use only.",
    "apisr": "APISR (CVPR 2024) by Kiteretsu77, ONNX conversion by Xenova (the original is a PyTorch file). It "
             "redraws the image the way anime is produced: thick dark lines and stronger contrast. It looks clean, "
             "but it changes the drawing style, and the LoRA would learn that style. Two versions, 2x (18 MB) and "
             "4x (6.5 MB); " + AUTO_TEXT + " License: GPL-3.0.",
    "cdc": "CDC_anime by 7eu7d7: the CDC enlarging method (Component Divide-and-Conquer, 2020) trained on anime, in "
           "the ONNX version published by deepghs. ALDS used it for upscaling up to version 0.4.1. It adds grain and "
           "can distort small details such as eyes and lines, and it needs much more graphics memory than the other "
           "models. 4x only, 160 MB to download. License: MIT.",
}
SIZE_MB = {"waifu2x": {2: 16.8, 4: 19.0}, "animevideov3": {4: 2.5}, "animesharp": {2: 33.6, 4: 33.6},
           "apisr": {2: 18.0, 4: 6.5}, "cdc": {4: 160.0}}


def factor_for(width, height, target):
    f = min(4.0, target / (width * height) ** 0.5)
    return f if f >= MIN_FACTOR else 1.0


@functools.lru_cache(maxsize=2)
def _session(model, scale):
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    repo, file, offset = MODELS[model][scale]
    cuda = ("CUDAExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"})
    session = ort.InferenceSession(hf_hub_download(repo, file), providers=[cuda, "CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    return session, inp.name, np.float16 if "float16" in inp.type else np.float32, offset


def _tiled(arr, model, scale):
    session, name, dtype, offset = _session(model, scale)
    h, w = arr.shape[:2]
    pad = MARGIN + offset
    padded = np.pad(arr, ((pad, pad + TILE), (pad, pad + TILE), (0, 0)), mode="reflect")
    out = np.empty((h * scale, w * scale, 3), np.float32)
    for y in range(0, h, TILE):
        for x in range(0, w, TILE):
            check_cancel()
            tile = padded[y:y + TILE + 2 * pad, x:x + TILE + 2 * pad].transpose(2, 0, 1)[None]
            res = session.run(None, {name: tile.astype(dtype)})[0][0].astype(np.float32).transpose(1, 2, 0)
            th, tw = min(TILE, h - y), min(TILE, w - x)
            m = MARGIN * scale
            out[y * scale:(y + th) * scale, x * scale:(x + tw) * scale] = res[m:m + th * scale, m:m + tw * scale]
    return out


def versions(model):
    return sorted(MODELS[model])


def _picked(model, version):
    return [int(version)] if version != "auto" and int(version) in MODELS[model] else versions(model)


def scale_for(model, factor, version="auto"):
    picked = _picked(model, version)
    return next((s for s in picked if s >= factor), picked[-1])


def size_mb(model, version="auto"):
    return round(sum(SIZE_MB[model][s] for s in _picked(model, version)), 1)


def upscale_image(img, factor, model=DEFAULT, version="auto"):
    img = img.convert("RGB")
    scale = scale_for(model, factor, version)
    if model == "cdc":
        from imgutils.upscale import upscale_with_cdc
        big = upscale_with_cdc(img, silent=True)
    else:
        out = _tiled(np.asarray(img, np.float32) / 255, model, scale)
        big = Image.fromarray((np.clip(out, 0, 1) * 255).round().astype(np.uint8))
    return big.resize((round(img.width * factor), round(img.height * factor)), Image.LANCZOS)


def megabytes(size):
    mb = size / 1e6
    return round(mb, 1) if mb < 10 else round(mb)


def files(model, version="auto"):
    return [CDC_FILE] if model == "cdc" else [MODELS[model][s][:2] for s in _picked(model, version)]


def downloaded_size(model, version="auto"):
    from huggingface_hub import try_to_load_from_cache
    paths = [try_to_load_from_cache(repo, file) for repo, file in files(model, version)]
    if not all(isinstance(p, str) and os.path.exists(p) for p in paths):
        return 0
    return sum(os.path.getsize(p) for p in paths)


def download(model, version="auto"):
    from huggingface_hub import hf_hub_download
    for repo, file in files(model, version):
        check_cancel()
        hf_hub_download(repo, file)


def delete(model):
    from huggingface_hub import scan_cache_dir
    from .common import release_models
    release_models()
    repos = {repo for repo, _ in files(model)}
    cache = scan_cache_dir()
    revisions = [rev.commit_hash for r in cache.repos if r.repo_id in repos for rev in r.revisions]
    freed = sum(r.size_on_disk for r in cache.repos if r.repo_id in repos)
    if revisions:
        cache.delete_revisions(*revisions).execute()
    return freed
