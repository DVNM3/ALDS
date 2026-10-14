from unittest.mock import patch

import numpy as np
from PIL import Image

from alds import build, feedback, identity, negatives, positives, txn, versions
from alds.cache import CropCache
from test_preservation import ProjectTest


def distances(a, b):
    return np.abs(np.asarray(a)[:, 0, None] - np.asarray(b)[None, :, 0])


class FeedbackTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.char = self.write_build()
        for f in (self.char / "sorted").rglob("*.png"):
            Image.new("RGB", (48, 64), (100, 80, 130)).save(f)
        self.pngs = {f.stem: f for f in (self.char / "sorted").rglob("*.png")}
        np.savez(self.char / "ccip.npz", stems=["a", "b"], feats=[[0.12, 1], [0.30, 1]], refs=[[0.0, 1]])
        self.meta = self.p.load("characters/hero/build.json")
        self.meta["settings"] = {"threshold": 0.13, "relax": 1.0, "auto_reject": False}
        self.meta["clusters"] = []
        self.p.save("characters/hero/build.json", self.meta)
        for mod in (identity, build):
            mock = patch.object(mod, "ccip_cross", side_effect=distances)
            mock.start()
            self.addCleanup(mock.stop)

    def scan(self):
        values = [0.12, 0.30, 0.31, 0.04, 0.10, 0.10, 0.28]
        frames = [{"vid": 1, "n": i, "t": float(i), "shot": i, "file": f"frames/{i}.jpg", "deleted": True}
                  for i in range(6)]
        dets = [{"id": i, "frame": min(i, 5), "feat": i, "box": [0, 0, 48, 64], "head": None}
                for i in range(len(values))]
        self.p.save("scan/frames.json", frames)
        self.p.save("scan/detections.json", dets)
        np.save(self.p.path("scan/ccip.npy"), np.array([[v, 1] for v in values], np.float32))
        return frames, dets

    def test_confirmation_is_separate_idempotent_and_reversible(self):
        original = (self.char / "ccip.npz").read_bytes()
        positives.reject(self.char, "b")
        self.assertTrue(positives.confirm(self.char, self.pngs["b"]))
        self.assertTrue(positives.confirm(self.char, self.pngs["b"]))
        self.assertEqual(positives.load(self.char)[0], ["b"])
        self.assertEqual(negatives.load(self.char)[0], [])
        self.assertTrue(positives.thumbnail(self.char, "b").is_file())
        self.assertEqual((self.char / "ccip.npz").read_bytes(), original)
        positives.remove(self.char, "b")
        self.assertEqual(positives.load(self.char)[0], [])
        self.assertFalse(positives.thumbnail(self.char, "b").exists())

    def test_rejection_removes_confirmation_and_failed_write_restores_it(self):
        positives.confirm(self.char, self.pngs["b"])
        before = self.files(self.char)
        real_save = negatives._save

        def fail_confirmations(char_dir, names, feats, file=negatives.FILE):
            if file == positives.FILE:
                raise OSError("disk full")
            return real_save(char_dir, names, feats, file)
        with patch.object(negatives, "_save", side_effect=fail_confirmations):
            with self.assertRaises(OSError):
                positives.reject(self.char, "b")
        self.assertEqual(self.files(self.char), before)
        positives.reject(self.char, "b")
        self.assertEqual(positives.load(self.char)[0], [])
        self.assertEqual(negatives.load(self.char)[0], ["b"])

    def test_failed_thumbnail_does_not_commit_confirmation(self):
        positives.reject(self.char, "b")
        before = self.files(self.char)
        with patch.object(Image, "open", side_effect=OSError("bad image")):
            with self.assertRaises(OSError):
                positives.confirm(self.char, self.pngs["b"])
        self.assertEqual(self.files(self.char), before)

    def test_base_and_confirmed_poses_both_match_and_cache_changes(self):
        frames, dets = self.scan()
        frames = [dict(f, deleted=False) for f in frames]
        F = np.load(self.p.path("scan/ccip.npy"))
        cache = CropCache(self.p)
        refs, positive = np.array([[0, 1]]), np.array([[0.30, 1]])
        before = build.select(frames, dets, F, refs, 0.13, 1.0, cache)[0]
        after = build.select(frames, dets, F, refs, 0.13, 1.0, cache, confirmed=positive)[0]
        undone = build.select(frames, dets, F, refs, 0.13, 1.0, cache)[0]
        self.assertNotIn(1, before)
        self.assertIn(1, after)
        self.assertIn(3, after)
        self.assertEqual(set(before), set(undone))
        self.assertEqual(after[5][0]["id"], 6)

    def test_confirmed_poses_are_not_mined_as_other_characters(self):
        frames, dets = self.scan()
        self.p.save("scan/clusters.json", {"clusters": [{"id": 2, "members": [1, 2]}]})
        F = np.load(self.p.path("scan/ccip.npy"))
        refs = np.array([[0, 1]])
        self.assertIsNotNone(build.other_characters(self.p, [], refs, dets, F, 0.13, feedback.MemoryCache())[0])
        self.assertIsNone(build.other_characters(self.p, [], refs, dets, F, 0.13, feedback.MemoryCache(),
                                                 np.array([[0.30, 1]]))[0])

    def test_ambiguous_queue_uses_threshold_and_competitor_margin(self):
        scores = feedback.review_scores(self.p, "hero")
        self.assertTrue(scores["a"]["uncertain"])
        positives.confirm(self.char, self.pngs["a"])
        scores = feedback.review_scores(self.p, "hero")
        self.assertTrue(scores["a"]["confirmed"])
        self.assertFalse(scores["a"]["uncertain"])
        positives.remove(self.char, "a")
        np.savez(self.char / "ccip.npz", stems=["a", "b"], feats=[[0.05, 1], [0.3, 1]],
                 refs=[[0, 1]], others=[[0.11, 1]])
        negatives.add(self.char, "other", np.array([0.11, 1]))
        scores = feedback.review_scores(self.p, "hero")
        self.assertAlmostEqual(scores["a"]["margin"], 0.01, places=5)
        self.assertTrue(scores["a"]["uncertain"])

    def test_impact_is_read_only_and_works_without_frames(self):
        self.scan()
        positives.confirm(self.char, self.pngs["b"])
        positives.reject(self.char, "a")
        before = self.files(self.p.dir)
        result = feedback.preview_impact(self.p, "hero")
        self.assertEqual((result["added"], result["removed"], result["switched"]), (2, 2, 1))
        self.assertEqual((result["before"], result["after"]), (4, 4))
        self.assertEqual(self.files(self.p.dir), before)
        self.assertFalse((self.p.dir / "cache").exists())
        positives.remove(self.char, "b")
        negatives.clear(self.char)
        result = feedback.preview_impact(self.p, "hero")
        self.assertEqual(result["items"], [])

    def test_rebuild_and_version_restore_preserve_confirmations(self):
        positives.confirm(self.char, self.pngs["b"])
        saved = versions.save_version(self.p, "hero")
        with txn.build_txn(self.p, "hero"):
            self.assertEqual(positives.load(self.char)[0], ["b"])
            self.write_build(("a",))
        self.assertEqual(positives.load(self.char)[0], ["b"])
        self.assertTrue(positives.thumbnail(self.char, "b").exists())
        positives.remove(self.char, "b")
        versions.restore_version(self.p, "hero", saved)
        self.assertEqual(positives.load(self.char)[0], ["b"])
        self.assertTrue(positives.thumbnail(self.char, "b").exists())
        before_restore = next(v for v in versions.list_versions(self.p, "hero") if v["reason"] == "before restore")
        versions.restore_version(self.p, "hero", before_restore["id"])
        self.assertEqual(positives.load(self.char)[0], [])
        self.assertFalse(positives.thumbnail(self.char, "b").exists())

    def test_cli_confirms_removes_and_lists_without_rebuilding(self):
        from alds.__main__ import main
        before = (self.char / "build.json").read_bytes()
        main(["confirm", "-p", self.p.name, "-n", "hero", "b.png"])
        self.assertEqual(positives.load(self.char)[0], ["b"])
        main(["confirm", "-p", self.p.name, "-n", "hero", "--remove", "b"])
        self.assertEqual(positives.load(self.char)[0], [])
        self.assertEqual((self.char / "build.json").read_bytes(), before)

    def test_missing_features_cannot_create_reference(self):
        (self.char / "ccip.npz").unlink()
        self.assertFalse(positives.confirm(self.char, self.pngs["b"]))
        self.assertEqual(feedback.review_scores(self.p, "hero"), {})
