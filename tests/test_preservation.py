import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alds import cancel, common, tags, txn, versions


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root_patch = patch.object(common, "PROJECTS_DIR", Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.p = common.Project("sample")
        self.p.dir.mkdir()
        cancel.reset()
        self.addCleanup(cancel.reset)

    def write_build(self, stems=("a", "b"), captions=None):
        char = self.p.char_dir("hero")
        items = []
        for stem in stems:
            png = char / "sorted" / "upper_body" / "front" / (stem + ".png")
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(b"image-" + stem.encode())
            caption = (captions or {}).get(stem, "generated " + stem)
            png.with_suffix(".txt").write_text(caption, encoding="utf-8")
            items.append({"file": str(png.relative_to(char)), "caption": caption})
        (char / "sorted").mkdir(parents=True, exist_ok=True)
        self.p.save("characters/hero/build.json", {"items": items, "settings": {"threshold": 0.13}})
        return char

    def files(self, folder):
        return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()
                and "versions" not in p.relative_to(folder).parts}


class VersionTests(ProjectTest):
    def test_snapshot_is_independent_and_comparison_sees_review(self):
        char = self.write_build()
        version = versions.save_version(self.p, "hero")
        png = next((char / "sorted").rglob("a.png"))
        png.with_suffix(".txt").write_text("edited", encoding="utf-8")
        png.write_bytes(b"changed image")
        saved = versions.version_path(self.p, "hero", version) / "data"
        self.assertEqual(next(saved.rglob("a.png")).read_bytes(), b"image-a")
        self.assertEqual(versions.compare_version(self.p, "hero", version)["captions"], 1)

    def test_restore_keeps_current_version_and_reference_and_rejections(self):
        char = self.write_build()
        (char / "negatives.npz").write_bytes(b"old rejections")
        refs = self.p.dir / "refs" / "hero"
        refs.mkdir(parents=True)
        (refs / "ref.png").write_bytes(b"old reference")
        original = self.files(char)
        version = versions.save_version(self.p, "hero")
        next((char / "sorted").rglob("a.txt")).write_text("new review")
        (char / "negatives.npz").write_bytes(b"new rejections")
        (refs / "ref.png").write_bytes(b"new reference")
        versions.restore_version(self.p, "hero", version)
        self.assertEqual(self.files(char), original)
        self.assertEqual((refs / "ref.png").read_bytes(), b"old reference")
        rows = versions.list_versions(self.p, "hero")
        self.assertEqual(len(rows), 2)
        prior = next(r for r in rows if r["reason"] == "before restore")
        versions.restore_version(self.p, "hero", prior["id"])
        self.assertEqual(next((char / "sorted").rglob("a.txt")).read_text(), "new review")

    def test_failed_rebuild_restores_all_original_files(self):
        char = self.write_build()
        before = self.files(char)
        with self.assertRaises(RuntimeError):
            with txn.build_txn(self.p, "hero"):
                self.write_build(("c",))
                raise RuntimeError("model failed")
        self.assertEqual(self.files(char), before)
        self.assertEqual(versions.list_versions(self.p, "hero"), [])

    def test_rebuild_preserves_manual_caption_move_and_deletion(self):
        char = self.write_build(("a", "b", "c"))
        a = next((char / "sorted").rglob("a.png"))
        a.with_suffix(".txt").write_text("my caption")
        b = next((char / "sorted").rglob("b.png"))
        b.unlink()
        b.with_suffix(".txt").unlink()
        c = next((char / "sorted").rglob("c.png"))
        dest = char / "sorted" / "full_body" / "side" / "c.png"
        dest.parent.mkdir(parents=True)
        c.rename(dest)
        c.with_suffix(".txt").rename(dest.with_suffix(".txt"))
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a", "b", "c", "d"))
        self.assertEqual(a.with_suffix(".txt").read_text(), "my caption")
        self.assertFalse(b.exists())
        self.assertTrue(dest.exists())
        self.assertEqual(len(list((char / "sorted").rglob("*.png"))), 3)
        self.assertEqual(len(versions.list_versions(self.p, "hero")), 1)

    def test_review_survives_intervening_build_that_does_not_include_image(self):
        char = self.write_build()
        a = next((char / "sorted").rglob("a.png"))
        b = next((char / "sorted").rglob("b.png"))
        a.with_suffix(".txt").write_text("my caption")
        b.unlink()
        b.with_suffix(".txt").unlink()
        with txn.build_txn(self.p, "hero"):
            self.write_build(("c",))
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a", "b", "c"))
        self.assertEqual(a.with_suffix(".txt").read_text(), "my caption")
        self.assertFalse(b.exists())

    def test_cancelled_snapshot_leaves_current_images_untouched(self):
        char = self.write_build()
        original = self.files(char)
        cancel.request()
        with self.assertRaises(cancel.Cancelled):
            versions.save_version(self.p, "hero")
        self.assertEqual(self.files(char), original)
        self.assertEqual(versions.list_versions(self.p, "hero"), [])

    def test_restore_failure_rolls_back_and_keeps_selected_snapshot(self):
        char = self.write_build()
        v = versions.save_version(self.p, "hero")
        next((char / "sorted").rglob("a.txt")).write_text("current review")
        before = self.files(char)
        actual = versions.copy_part
        def fail_saved_copy(src, dst, store=None):
            if v in src.parts:
                raise OSError("disk error")
            return actual(src, dst, store)
        with patch.object(versions, "copy_part", side_effect=fail_saved_copy), self.assertRaises(OSError):
            versions.restore_version(self.p, "hero", v)
        self.assertEqual(self.files(char), before)
        self.assertEqual(len(versions.list_versions(self.p, "hero")), 1)

    def test_version_path_cannot_escape(self):
        self.write_build()
        with self.assertRaises(SystemExit):
            versions.restore_version(self.p, "hero", "../other")

    def test_legacy_automatic_outfit_tags_are_not_mistaken_for_manual_edits(self):
        char = self.write_build(("a",))
        meta = self.p.load("characters/hero/build.json")
        del meta["settings"]
        meta["outfits"] = [{"token": "hero_outfit1"}]
        self.p.save("characters/hero/build.json", meta)
        next((char / "sorted").rglob("a.txt")).write_text("generated a, hero_outfit1")
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a",), {"a": "new generated caption"})
        self.assertEqual(next((char / "sorted").rglob("a.txt")).read_text(), "new generated caption")

    def test_rerun_outfit_tokens_are_not_mistaken_for_manual_edits(self):
        char = self.write_build(("a",), {"a": "hero, generated a"})
        meta = self.p.load("characters/hero/build.json")
        meta["outfits"] = [{"id": 1, "token": "hero_outfit1"}, {"id": 2, "token": "hero_coat"}]
        self.p.save("characters/hero/build.json", meta)
        next((char / "sorted").rglob("a.txt")).write_text("hero, hero_coat, generated a")
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a",), {"a": "hero, hero_outfit1, new a"})
        self.assertEqual(next((char / "sorted").rglob("a.txt")).read_text(), "hero, hero_outfit1, new a")

    def test_manual_caption_takes_the_new_outfit_token(self):
        char = self.write_build(("a",), {"a": "hero, generated a"})
        next((char / "sorted").rglob("a.txt")).write_text("hero, hero_outfit2, my tags")
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a",), {"a": "hero, hero_outfit1, new a"})
        self.assertEqual(next((char / "sorted").rglob("a.txt")).read_text(), "hero, hero_outfit1, my tags")

    def test_bulk_tag_edits_apply_to_new_images_after_rebuild(self):
        char = self.write_build(("a", "b"), {"a": "x, parody", "b": "y, parody"})
        tags.edit_tags(char, remove=["parody"], replace={"x": "z"})
        next((char / "sorted").rglob("b.txt")).write_text("mine")
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a", "b", "c"), {"a": "x, parody", "b": "y, parody", "c": "x, w, parody"})
        text = {p.stem: p.read_text() for p in (char / "sorted").rglob("*.txt")}
        self.assertEqual(text, {"a": "z", "b": "mine", "c": "z, w"})

    def test_tag_undo_forgets_the_edit(self):
        char = self.write_build(("a",), {"a": "x, parody"})
        tags.edit_tags(char, remove=["parody"])
        self.assertEqual(len(tags.load_edits(char)), 1)
        tags.undo_last(char)
        self.assertEqual(tags.load_edits(char), [])
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a",), {"a": "x, parody"})
        self.assertEqual(next((char / "sorted").rglob("a.txt")).read_text(), "x, parody")

    def test_versions_store_unchanged_images_once_and_delete_frees_them(self):
        char = self.write_build(("a", "b"))
        first = versions.save_version(self.p, "hero")
        second = versions.save_version(self.p, "hero")
        store = char / "versions" / versions.STORE
        self.assertEqual(len(list(store.iterdir())), 2)
        versions.delete_version(self.p, "hero", first)
        self.assertEqual(len(list(store.iterdir())), 2)
        versions.delete_version(self.p, "hero", second)
        self.assertEqual(list(store.iterdir()), [])
        self.assertEqual(versions.list_versions(self.p, "hero"), [])
        with self.assertRaises(SystemExit):
            versions.delete_version(self.p, "hero", versions.STORE)

    def test_transactions_started_together_use_separate_backups(self):
        frozen = patch.object(txn.time, "time_ns", return_value=1)
        frozen.start()
        self.addCleanup(frozen.stop)
        char = self.write_build()
        with txn.Transaction(char, keep=[char / "build.json"]):
            with txn.Transaction(char, keep=[char / "build.json"]):
                (char / "build.json").write_text("{}")
        self.assertEqual([p.name for p in char.iterdir() if p.name.startswith(".undo_")], [])

    def test_transaction_entry_failure_returns_already_moved_results(self):
        char = self.write_build()
        before = self.files(char)
        move = txn.shutil.move
        count = 0
        def fail_second(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("locked file")
            return move(src, dst)
        with patch.object(txn.shutil, "move", side_effect=fail_second), self.assertRaises(OSError):
            with txn.build_txn(self.p, "hero"):
                self.fail("Should not enter a partially prepared transaction")
        self.assertEqual(self.files(char), before)
        self.assertEqual(versions.list_versions(self.p, "hero"), [])

    def test_snapshot_survives_when_filesystem_prevents_rollback(self):
        char = self.write_build()
        before = self.files(char)
        with patch.object(txn.Transaction, "rollback", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                with txn.build_txn(self.p, "hero"):
                    self.write_build(("new",))
                    raise RuntimeError("build failed")
        rows = versions.list_versions(self.p, "hero")
        self.assertEqual(len(rows), 1)
        saved = versions.version_path(self.p, "hero", rows[0]["id"]) / "data"
        self.assertEqual(self.files(saved), before)


if __name__ == "__main__":
    unittest.main()
