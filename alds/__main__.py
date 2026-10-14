import argparse
import sys
from pathlib import Path

from .common import Project, parse_ranges, setup_runtime


def main(argv=None):
    ap = argparse.ArgumentParser(prog="alds",
                                 description="Turn anime episodes into a LoRA training dataset for one character.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="extract frames, detect and cluster characters")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("videos", nargs="+", help="video files or folders of videos")
    p.add_argument("--skip", nargs="*", default=[], help="time ranges to ignore, e.g. 0:00-1:30 22:00-23:40 (OP/ED)")
    p.add_argument("--min-gap", type=float, default=0.35, help="min seconds between kept frames of one shot")
    p.add_argument("--keep-diff", type=float, default=5.0, help="how much a frame must change to be kept again")
    p.add_argument("--no-auto-skip", action="store_true",
                   help="don't auto-detect OP/ED (segments repeated across episodes)")
    p.add_argument("--auto-min", type=float, default=40.0, help="min length (s) of a repeated segment to skip")

    p = sub.add_parser("autoskip", help="re-run (or clear) automatic OP/ED detection, then re-cluster")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--min-len", type=float, default=40.0, help="min length (s) of a repeated segment to skip")
    p.add_argument("--off", action="store_true", help="clear auto-detected segments and use all frames again")

    p = sub.add_parser("clusters", help="re-cluster scanned characters")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--cut", type=float, default=0.2, help="merge distance; lower = more, smaller clusters")
    p.add_argument("--min-size", type=int, default=8, help="hide clusters with fewer views than this")
    p.add_argument("--max-samples", type=int, default=4000)

    p = sub.add_parser("split", help="split one mixed cluster (other cluster numbers stay the same)")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--cluster", type=int, required=True)
    p.add_argument("--cut", type=float, default=0.14, help="tighter than the clustering cut (0.2)")

    p = sub.add_parser("build", help="build the dataset for one character")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-n", "--name", required=True, help="trigger word, also the output folder name")
    p.add_argument("--cluster", type=int, nargs="*", default=[], help="cluster number(s) from scan")
    p.add_argument("--ref", help="folder of reference images of the character (instead of / in addition to clusters)")
    p.add_argument("--threshold", type=float, help="CCIP match threshold (default 0.13; higher = looser)")
    p.add_argument("--relax", type=float, default=1.0,
                   help="enable shot tracking: also take overlapping boxes in the same shot scoring under "
                        "threshold*relax (e.g. 1.3). Off by default: it can pull in wrong characters")
    p.add_argument("--min-size", type=int,
                   help="min crop size, sqrt(width*height) in px (default 448, or 320 with --upscale)")
    p.add_argument("--upscale", action="store_true",
                   help="enlarge small crops with an anime upscaler (CDC) instead of training on them small")
    p.add_argument("--upscale-to", type=int, default=1024, help="target size for --upscale, sqrt(w*h) in px")
    p.add_argument("--sim", type=float, default=0.80,
                   help="near-duplicate cutoff (WD14 embedding cosine; lower = stricter dedup)")
    p.add_argument("--keep-text", action="store_true", help="keep crops with on-screen text (credits, titles)")
    p.add_argument("--keep-crowded", action="store_true", help="keep crops where another character takes up a big part")
    p.add_argument("--series", help="series tag to put after the trigger, e.g. 'fairy tail'")
    p.add_argument("--keep-core", action="store_true", help="keep hair/eye/body tags in captions")
    p.add_argument("--no-screencap-tag", action="store_true", help="don't prefix captions with 'anime screencap'")
    p.add_argument("--tagger", default="EVA02_Large", help="WD14 model: EVA02_Large, SwinV2_v3, ConvNext_v3, ViT_v3")
    p.add_argument("--keep-offmodel", action="store_true", help="keep crops tagged chibi / super deformed / blurry")
    p.add_argument("--keep-mono", action="store_true", help="keep black-and-white and sepia crops (flashbacks)")
    p.add_argument("--no-auto-reject", action="store_true",
                   help="don't use the other clusters to leave out other characters")
    p.add_argument("--no-outfits", action="store_true", help="don't add per-outfit tokens to captions")
    p.add_argument("--save-dropped", action="store_true", help="also save filtered-out crops to _dropped/<reason>/")
    p.add_argument("--overwrite", action="store_true", help="replace an existing sorted/ folder")
    p.add_argument("--fresh", action="store_true",
                   help="ignore the saved crop analysis (tags, OCR, faces, upscales) and redo it all")

    p = sub.add_parser("reject", help="mark built images as another character (removed and learned); "
                                      "without images it lists the remaining ones that look like them")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-n", "--name", required=True)
    p.add_argument("images", nargs="*", help="image names in sorted/, e.g. v01_00616.0s_full.png")
    p.add_argument("--clear", action="store_true", help="forget all rejected images (the files stay deleted)")

    p = sub.add_parser("outfits", help="re-run outfit separation (e.g. after deleting images in review)")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-n", "--name", required=True)

    p = sub.add_parser("tags", help="bulk edit captions; without an action it lists tag counts")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-n", "--name", required=True)
    p.add_argument("--remove", nargs="*", default=[], help="tags to remove from every caption")
    p.add_argument("--replace", nargs="*", default=[], metavar="OLD=NEW", help="e.g. \"yellow eyes=brown eyes\"")
    p.add_argument("--add", nargs="*", default=[], help="tags to append to every caption")
    p.add_argument("--undo", action="store_true", help="undo the last bulk edit")

    p = sub.add_parser("export", help="flatten reviewed images into an AI Toolkit dataset folder")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-n", "--name", required=True)
    p.add_argument("--out", help="output folder (default: projects/<p>/characters/<name>/train)")
    p.add_argument("--total", type=int, help="balance: spread this many images evenly over framing/view groups")
    p.add_argument("--max-per-group", type=int, help="cap images per framing/view group")
    p.add_argument("--aitk", nargs="?", const="", metavar="AI_TOOLKIT_DIR",
                   help="export into AI Toolkit's datasets folder and write a job config; the folder is "
                        "remembered, so later just --aitk")
    p.add_argument("--dataset-name", help="dataset folder name in AI Toolkit (default: the character name)")
    p.add_argument("--epochs", type=int, default=40, choices=(40, 50, 60), help="training length (Anima recipe: 40)")
    p.add_argument("--res", type=int, nargs="+", default=[512, 1024], help="training resolutions (recipe: 512 1024)")
    p.add_argument("--job-name", help="AI Toolkit job name (default: <Dataset_Name>_v<next free number>)")

    p = sub.add_parser("clean", help="free disk space; without --all only frames nothing will read again")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--all", action="store_true",
                   help="delete ALL extracted frames: finished images stay, but no more builds for this project")

    p = sub.add_parser("gui", help="open the graphical interface in the browser")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")

    a = ap.parse_args(argv)
    if a.cmd == "gui":
        from .gui import launch
        return launch(a.port, not a.no_browser)
    project = Project(a.project)
    if a.cmd not in ("export", "tags", "outfits", "clean"):
        setup_runtime()
    try:
        run_command(project, a)
    except KeyboardInterrupt:
        print("[stopped] nothing from this command was kept")
        return 130


def run_command(project, a):
    from . import txn

    if a.cmd == "scan":
        from .scan import run_scan
        with txn.scan_txn(project):
            run_scan(project, a.videos, parse_ranges(a.skip), a.min_gap, a.keep_diff, not a.no_auto_skip,
                     a.auto_min)
    elif a.cmd == "autoskip":
        from .repeats import clear_repeats, detect_repeats
        from .scan import run_clusters
        with txn.clusters_txn(project):
            if a.off:
                clear_repeats(project)
            else:
                detect_repeats(project, a.min_len)
            run_clusters(project)
    elif a.cmd == "clusters":
        from .scan import run_clusters
        with txn.clusters_txn(project):
            run_clusters(project, a.cut, a.min_size, a.max_samples)
    elif a.cmd == "split":
        from .scan import split_cluster
        with txn.clusters_txn(project):
            split_cluster(project, a.cluster, a.cut)
    elif a.cmd == "build":
        from .build import check_overwrite, run_build
        min_size = a.min_size or (320 if a.upscale else 448)
        check_overwrite(project, a.name, a.overwrite)
        with txn.build_txn(project, a.name):
            run_build(project, a.name, a.cluster, a.ref, a.threshold, a.relax, min_size, a.sim, a.series,
                      a.keep_core, not a.no_screencap_tag, a.tagger, a.keep_text, a.keep_crowded, a.keep_offmodel,
                      a.save_dropped, a.overwrite, a.upscale_to if a.upscale else 0, not a.no_outfits, a.fresh,
                      not a.no_auto_reject, a.keep_mono)
    elif a.cmd == "reject":
        run_reject(project, a)
    elif a.cmd == "outfits":
        from .outfits import run_outfits
        run_outfits(project, a.name)
    elif a.cmd == "tags":
        run_tags(project, a)
    elif a.cmd == "export":
        from .export import run_export
        aitk = None
        if a.aitk is not None:
            from .aitk import load_settings, save_settings
            root = a.aitk or load_settings().get("aitk_root")
            if not root:
                raise SystemExit("give the AI Toolkit folder once, e.g. --aitk \"E:\\AI-Toolkit-Easy-Install\\AI-Toolkit\"")
            save_settings(aitk_root=root)
            aitk = {"root": root, "dataset_name": a.dataset_name, "epochs": a.epochs, "resolutions": a.res,
                    "job_name": a.job_name}
        from .export import export_target
        with txn.export_txn(project, a.name, export_target(project, a.name, a.out, aitk),
                            Path(aitk["root"]) / "config" if aitk else None):
            run_export(project, a.name, a.out, a.max_per_group, a.total, aitk)
    elif a.cmd == "clean":
        from .cleanup import clean
        clean(project, "all" if a.all else "safe")


def run_reject(project, a):
    from . import negatives
    char_dir = project.char_dir(a.name)
    sorted_dir = char_dir / "sorted"
    if not sorted_dir.exists():
        raise SystemExit(f"no built images for '{a.name}'")
    if a.clear:
        print(f"[reject] forgot {len(negatives.load(char_dir)[0])} rejected images")
        negatives.clear(char_dir)
        return
    for name in a.images:
        hits = list(sorted_dir.rglob(Path(name).stem + ".png"))
        if not hits:
            raise SystemExit(f"not found in {sorted_dir}: {name}")
        if not negatives.reject(char_dir, hits[0].stem):
            raise SystemExit("this character was built by an older version - build it again once (--overwrite)")
        negatives.trash(char_dir, hits[0])
        print(f"[reject] {hits[0].name}: removed and learned as another character")
    names, _ = negatives.load(char_dir)
    alike = negatives.look_alikes(char_dir, [f.stem for f in sorted_dir.rglob("*.png")])
    print(f"[reject] {len(names)} rejected images; {len(alike)} remaining images look like them"
          + (" (most alike first):" if alike else ""))
    paths = {f.stem: f for f in sorted_dir.rglob("*.png")}
    for n in sorted(alike, key=alike.get, reverse=True):
        print(f"  {paths[n].relative_to(sorted_dir)}")


def run_tags(project, a):
    from .tags import edit_tags, tag_counts, undo_last
    char_dir = project.char_dir(a.name)
    if not (char_dir / "sorted").exists():
        raise SystemExit(f"no built images for '{a.name}'")
    if a.undo:
        print(f"[tags] restored {undo_last(char_dir)} captions")
        from .outfits import resync_after_undo
        resync_after_undo(project, a.name)
    elif a.remove or a.replace or a.add:
        try:
            replace = dict(r.split("=", 1) for r in a.replace)
        except ValueError:
            raise SystemExit('--replace expects OLD=NEW, e.g. "yellow eyes=brown eyes"')
        print(f"[tags] changed {edit_tags(char_dir, a.remove, replace, a.add)} captions")
        from .outfits import sync_tokens
        sync_tokens(project, a.name, a.remove, replace)
    else:
        cnt, n = tag_counts(char_dir)
        print(f"[tags] {n} captions, {len(cnt)} distinct tags")
        for t, c in cnt.most_common():
            print(f"  {c:>5}  {100 * c / n:5.1f}%  {t}")


if __name__ == "__main__":
    sys.exit(main())
