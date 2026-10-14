import contextlib
import sys
import types
from unittest.mock import patch

import numpy as np
from PIL import Image

from alds import build, txn
from test_preservation import ProjectTest


class PreviewTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.char = self.write_build()
        self.p.save("project.json", {"videos": [], "frames_deleted": False})
        frames, dets = [], []
        for n in range(2):
            path = self.p.frames_dir / f"{n}.jpg"
            path.parent.mkdir(exist_ok=True)
            Image.new("RGB", (64, 48), (100, 100, 100)).save(path)
            frames.append({"n": n, "t": float(n), "vid": 1, "shot": n, "file": f"frames/{n}.jpg"})
            dets.append({"id": n, "frame": n, "feat": n, "box": [0, 0, 64, 48], "head": None})
        self.p.save("scan/frames.json", frames)
        self.p.save("scan/detections.json", dets)
        np.save(self.p.path("scan/ccip.npy"), np.array([[0.05, 1], [0.2, 1]], dtype=np.float32))
        self.out = self.p.dir / "previews" / "hero"
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        detect = types.ModuleType("imgutils.detect")
        detect.detect_halfbody = lambda *a, **k: []
        detect.detect_faces = lambda *a, **k: []
        detect.detect_eyes = lambda *a, **k: []
        ocr = types.ModuleType("imgutils.ocr")
        ocr.ocr = lambda *a: []
        tagging = types.ModuleType("imgutils.tagging")
        tagging.get_wd14_tags = lambda *a, **k: ({"safe": 1.0}, {"solo": 1.0, "upper body": 1.0}, {},
                                               np.array([1.0, 0.0]))
        validate = types.ModuleType("imgutils.validate")
        validate.anime_portrait = lambda *a: ("upper_body", 1.0)
        self.stack.enter_context(patch.dict(sys.modules, {"imgutils.detect": detect, "imgutils.ocr": ocr,
                                                       "imgutils.tagging": tagging, "imgutils.validate": validate}))
        self.stack.enter_context(patch.object(build, "reference_features", return_value=np.array([[0, 1]])))
        self.stack.enter_context(patch.object(build, "other_characters", return_value=(None, [])))
        self.stack.enter_context(patch.object(build, "match_score", side_effect=lambda feats, refs: feats[:, 0]))
        self.stack.enter_context(patch.object(build, "image_stats", return_value=(100.0, 30.0)))

    def preview(self, threshold=0.13, keep_text=False):
        with txn.Transaction(self.p.dir, replace=[self.out]):
            return build.run_build(self.p, "hero", [1], None, threshold, 1.0, 1, 0.8, None, False, True,
                                   "EVA02_Large", keep_text, False, False, False, False,
                                   preview_limit=2)

    def test_preview_uses_identity_filter_and_never_changes_current_build(self):
        before = self.files(self.char)
        result = self.preview()
        self.assertEqual(result["frames"], 2)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual({r["reason"] for r in result["items"]}, {"accepted", "identity threshold"})
        self.assertEqual(self.files(self.char), before)
        self.assertFalse((self.char / "versions").exists())

    def test_preview_shows_all_rejected_without_failing(self):
        result = self.preview(threshold=0.01)
        self.assertEqual(result["accepted"], 0)
        self.assertEqual([r["reason"] for r in result["items"]], ["identity threshold"] * 2)

    def test_preview_explains_ocr_rejection_and_changes_with_keep_text(self):
        with patch.object(build, "read_text", return_value=[("credits", 1.0)]):
            rejected = self.preview()
        self.assertIn("text on screen", [r["reason"] for r in rejected["items"]])
        self.assertEqual(rejected["accepted"], 0)
        kept = self.preview(keep_text=True)
        self.assertEqual(kept["accepted"], 1)

    def test_duplicate_filter_matches_full_build_rule(self):
        result = self.preview(threshold=0.25)
        self.assertEqual(result["accepted"], 1)
        self.assertIn("near-duplicate", [r["reason"] for r in result["items"]])

    def test_confirmed_reference_applies_to_frames_and_half_crops(self):
        from alds import identity
        from test_feedback import distances
        np.savez(self.char / "positives.npz", names=["confirmed_pose"], feats=[[0.2, 1]])
        with patch.object(identity, "ccip_cross", side_effect=distances), \
                patch.object(build, "crop_boxes", return_value={"full": [0, 0, 64, 48], "half": [0, 0, 32, 24]}), \
                patch.object(build, "ccip_features", side_effect=lambda imgs: np.array([[0.2, 1]] * len(imgs))):
            result = self.preview()
        self.assertEqual(result["accepted"], 2)  # one per crop type after duplicate removal
        self.assertNotIn("identity threshold", [r["reason"] for r in result["items"]])
        self.assertNotIn("another character in crop", [r["reason"] for r in result["items"]])

    def test_failed_preview_restores_previous_preview_and_current_result(self):
        self.preview()
        before, before_current = self.files(self.out), self.files(self.char)
        with patch.object(build, "match_score", side_effect=RuntimeError("model error")):
            with self.assertRaises(RuntimeError):
                self.preview()
        self.assertEqual(self.files(self.out), before)
        self.assertEqual(self.files(self.char), before_current)
