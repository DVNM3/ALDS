import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from alds import aitk, gui, pick
from alds.common import OWN_IMAGES
from alds.i18n import use
from test_preservation import ProjectTest


class PickTests(ProjectTest):
    def setUp(self):
        super().setUp()
        for module in (pick, gui):
            patcher = patch.object(module, "PROJECTS_DIR", self.p.dir.parent)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = patch.object(aitk, "SETTINGS", self.p.dir / "settings.json")
        settings.start()
        self.addCleanup(settings.stop)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.root = Path(outside.name)

    def video(self, folder, name, content):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_dropped_episode_found_on_disk_is_used_where_it_is(self):
        original = self.video("library/Season 1", "ep01.mkv", b"episode one" * 1000)
        upload = self.video("upload/x", "ep01.mkv", b"episode one" * 1000)
        adopted = pick.adopt_dropped(self.p.dir, [upload], [self.root / "library"])
        self.assertEqual(adopted, [(original.resolve(), True)])
        self.assertFalse(upload.exists())
        self.assertFalse((self.p.dir / pick.EPISODES).exists())

    def test_dropped_episode_not_found_is_kept_in_the_project_once(self):
        self.video("library", "ep02.mkv", b"another episode with the same name")
        first = self.video("upload/a", "ep02.mkv", b"dropped episode")
        second = self.video("upload/b", "ep02.mkv", b"dropped episode")
        kept = pick.adopt_dropped(self.p.dir, [first], [self.root / "library"])[0][0]
        self.assertEqual(kept, (self.p.dir / pick.EPISODES / "ep02.mkv").resolve())
        self.assertEqual(kept.read_bytes(), b"dropped episode")
        again = pick.adopt_dropped(self.p.dir, [second], [self.root / "library"])[0][0]
        self.assertEqual(again, kept)
        self.assertEqual(len(list((self.p.dir / pick.EPISODES).iterdir())), 1)

    def test_episode_list_shows_folders_with_their_episode_count(self):
        self.video("library/Season 1", "ep01.mkv", b"1")
        self.video("library/Season 1", "ep02.mp4", b"2")
        self.video("library/Season 1", "notes.txt", b"3")
        update = gui.episodes_update([str(self.root / "library" / "Season 1"),
                                      str(self.root / "library" / "Season 1")])
        self.assertEqual(update["choices"], [("📁 Season 1 (2)", str(self.root / "library" / "Season 1"))])

    def test_scan_asks_for_episodes_when_none_are_chosen(self):
        with use("en"), self.assertRaises(gui.gr.Error) as err:
            gui.do_scan(self.p.name, [], "", True, 40, 0.35, 5)
        self.assertIn("Choose or drop", str(err.exception))

    def test_own_images_follow_the_trigger_word(self):
        own = self.p.char_dir("hero") / OWN_IMAGES
        own.mkdir(parents=True)
        Image.new("RGB", (8, 8)).save(own / "saved.png")
        (self.p.char_dir("hero") / "sorted").mkdir()
        upload = self.root / "upload" / "new.png"
        upload.parent.mkdir()
        Image.new("RGB", (8, 8)).save(upload)
        with use("en"):
            files, loaded, note = gui.name_changed(self.p.name, "hero", [str(upload)], [])
            self.assertEqual([Path(f).name for f in files["value"]], ["saved.png", "new.png"])
            self.assertEqual(loaded, ["saved.png"])
            self.assertIn("already built", note)
            files, loaded, note = gui.name_changed(self.p.name, "villain", files["value"], loaded)
            self.assertEqual([Path(f).name for f in files["value"]], ["new.png"])
            self.assertEqual((loaded, note), ([], ""))

    def test_build_needs_clusters_or_own_images(self):
        with use("en"), self.assertRaises(gui.gr.Error) as err:
            gui.do_build(self.p.name, [], [], True, True, "hero", "", False, "waifu2x", "auto", 1024, 0.13, 50,
                         0.8, 1.0, "EVA02_Large", [])
        self.assertIn("your own images", str(err.exception))

    def test_sync_keeps_the_listed_images_only(self):
        own = self.root / "own"
        own.mkdir()
        Image.new("RGB", (8, 8)).save(own / "keep.png")
        Image.new("RGB", (8, 8)).save(own / "drop.png")
        upload = self.root / "upload" / "keep.png"
        upload.parent.mkdir()
        Image.new("RGB", (8, 8), (9, 9, 9)).save(upload)
        added = self.root / "upload" / "added.jpg"
        Image.new("RGB", (8, 8)).save(added)
        names = [f.name for f in pick.sync_images(own, [upload, added])]
        self.assertEqual(names, ["added.jpg", "keep.png", "keep_2.png"])
        self.assertEqual(pick.sync_images(own, []), [])
        self.assertFalse(own.exists())
