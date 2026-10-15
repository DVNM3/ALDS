import contextlib
import sys
import types
from unittest.mock import patch

import numpy as np
from PIL import Image

from alds import build, cancel, txn
from test_preservation import ProjectTest

TAGS = {"solo": 1.0, "1girl": 1.0, "upper body": 1.0}


class PreviewTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.char = self.write_build()
        self.p.save("project.json", {"videos": [{"id": 1, "width": 64, "height": 48}], "frames_deleted": False})
        frames, dets = [], []
        for n in range(2):
            path = self.p.frames_dir / f"{n}.jpg"
            path.parent.mkdir(exist_ok=True)
            Image.new("RGB", (64, 48), (100, 100, 100)).save(path)
            frames.append({"n": n, "t": float(n), "vid": 1, "shot": n, "file": f"frames/{n}.jpg"})
            dets.append({"id": n, "frame": n, "feat": n, "box": [8, 0, 40, 48], "rh": 1.0, "head": None})
        self.frames, self.dets = frames, dets
        self.save_scan()
        np.save(self.p.path("scan/ccip.npy"), np.array([[0.05, 1], [0.2, 1]], dtype=np.float32))
        self.out = self.p.dir / "previews" / "hero"
        self.tags = dict(TAGS)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        detect = types.ModuleType("imgutils.detect")
        detect.detect_faces = lambda *a, **k: []
        detect.detect_eyes = lambda *a, **k: []
        ocr = types.ModuleType("imgutils.ocr")
        ocr.ocr = lambda *a: []
        tagging = types.ModuleType("imgutils.tagging")
        tagging.get_wd14_tags = lambda *a, **k: ({"safe": 1.0}, dict(self.tags), {}, np.array([1.0, 0.0]))
        tagging.convert_wd14_emb_to_prediction = lambda emb, **k: [dict(self.tags) for _ in emb]
        tagging.drop_overlap_tags = dict
        validate = types.ModuleType("imgutils.validate")
        validate.anime_portrait = lambda *a: ("upper_body", 1.0)
        self.stack.enter_context(patch.dict(sys.modules, {"imgutils.detect": detect, "imgutils.ocr": ocr,
                                                       "imgutils.tagging": tagging, "imgutils.validate": validate}))
        self.stack.enter_context(patch.object(build, "reference_features", return_value=np.array([[0, 1]])))
        self.stack.enter_context(patch.object(build, "other_characters", return_value=(None, [])))
        self.stack.enter_context(patch.object(build, "match_score", side_effect=lambda feats, refs: feats[:, 0]))
        self.stack.enter_context(patch.object(build, "image_stats", return_value=(100.0, 30.0)))

    def save_scan(self):
        self.p.save("scan/frames.json", self.frames)
        self.p.save("scan/detections.json", self.dets)

    def preview(self, threshold=0.13, keep_text=False, min_height=0.5):
        with txn.Transaction(self.p.dir, replace=[self.out]):
            return build.run_build(self.p, "hero", [1], None, threshold, 1.0, min_height, 0.8, None, True,
                                   "EVA02_Large", keep_text, False, False, False, preview_limit=2)

    def reasons(self, result):
        return [r["reason"] for r in result["items"]]

    def test_preview_uses_identity_filter_and_never_changes_current_build(self):
        before = self.files(self.char)
        result = self.preview()
        self.assertEqual(result["frames"], 2)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(set(self.reasons(result)), {"accepted", "identity threshold"})
        self.assertEqual(self.files(self.char), before)
        self.assertFalse((self.char / "versions").exists())

    def test_preview_shows_whole_frames(self):
        result = self.preview()
        accepted = next(r for r in result["items"] if r["reason"] == "accepted")
        self.assertEqual(Image.open(accepted["file"]).size, (64, 48))

    def test_preview_shows_all_rejected_without_failing(self):
        result = self.preview(threshold=0.01)
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(self.reasons(result), ["identity threshold"] * 2)

    def test_preview_explains_ocr_rejection_and_changes_with_keep_text(self):
        with patch.object(build, "read_text", return_value=[("credits", 1.0)]):
            rejected = self.preview()
        self.assertIn("text on screen", self.reasons(rejected))
        self.assertEqual(rejected["accepted"], 0)
        kept = self.preview(keep_text=True)
        self.assertEqual(kept["accepted"], 1)

    def test_duplicate_filter_matches_full_build_rule(self):
        result = self.preview(threshold=0.25)
        self.assertEqual(result["accepted"], 1)
        self.assertIn("near-duplicate", self.reasons(result))

    def test_scene_with_another_detected_person_is_left_out(self):
        self.dets.append({"id": 2, "frame": 0, "feat": -1, "box": [44, 30, 60, 46], "rh": 0.3, "head": None})
        self.save_scan()
        result = self.preview()
        self.assertEqual(result["accepted"], 0)
        self.assertIn("another character in the scene", self.reasons(result))

    def test_scene_the_tagger_sees_two_people_in_is_left_out(self):
        self.tags = {"1girl": 1.0, "1boy": 0.9}
        result = self.preview()
        self.assertEqual(result["accepted"], 0)
        self.assertIn("another character in the scene", self.reasons(result))

    def test_small_character_is_left_out_by_height(self):
        self.dets[0]["rh"] = 0.3
        self.save_scan()
        self.assertIn("character too small in the scene", self.reasons(self.preview()))
        self.assertEqual(self.preview(min_height=0.25)["accepted"], 1)

    def test_confirmed_reference_adds_scenes(self):
        from alds import identity
        from test_feedback import distances
        np.savez(self.char / "positives.npz", names=["confirmed_pose"], feats=[[0.2, 1]])
        with patch.object(identity, "ccip_cross", side_effect=distances):
            result = self.preview()
        self.assertNotIn("identity threshold", self.reasons(result))
        self.assertIn("near-duplicate", self.reasons(result))

    def test_full_build_writes_whole_scenes_and_upscales_small_ones(self):
        calls = []

        def fake_upscale(img, factor, model, version):
            calls.append((img.size, model, version))
            return img.resize((round(img.width * factor), round(img.height * factor)))
        self.tags["blue hair"] = 0.9
        with patch.object(build, "upscale_image", side_effect=fake_upscale), \
                patch("alds.outfits.run_outfits", return_value=[]):
            with txn.build_txn(self.p, "hero"):
                build.run_build(self.p, "hero", [1], None, 0.13, 1.0, 0.5, 0.8, None, True, "EVA02_Large",
                                False, False, False, True, upscale_to=128, upscaler="animesharp",
                                upscale_version="4")
        meta = self.p.load("characters/hero/build.json")
        self.assertEqual(len(meta["items"]), 1)
        item = meta["items"][0]
        self.assertIn("blue hair", item["caption"].split(", "))
        self.assertEqual(meta["appearance_tags"], ["blue hair"])
        report = (self.char / "report.txt").read_text(encoding="utf-8")
        self.assertIn("should learn in the Tags tab): blue hair\n", report)
        self.assertIn("comparing with the other images: -\n", report)
        self.assertEqual((item["type"], item["upscaler"]), ("scene", "animesharp"))
        self.assertEqual(calls, [((64, 48), "animesharp", "4")])
        factor = 128 / (64 * 48) ** 0.5
        self.assertEqual(Image.open(self.char / item["file"]).size, (round(64 * factor), round(48 * factor)))
        self.assertEqual(meta["settings"]["min_height"], 0.5)
        self.assertEqual(meta["settings"]["upscale_version"], "4")

    def test_failed_preview_restores_previous_preview_and_current_result(self):
        self.preview()
        before, before_current = self.files(self.out), self.files(self.char)
        with patch.object(build, "match_score", side_effect=RuntimeError("model error")):
            with self.assertRaises(RuntimeError):
                self.preview()
        self.assertEqual(self.files(self.out), before)
        self.assertEqual(self.files(self.char), before_current)

    def test_stopped_build_keeps_none_of_its_analysis(self):
        self.preview()
        cache = self.p.dir / "cache"
        before, before_current = self.files(cache), self.files(self.char)
        enlarge = lambda img, factor, model, version: img.resize((img.width * 2, img.height * 2))
        with patch.object(build, "upscale_image", side_effect=enlarge), \
                patch.object(build, "link_or_copy", side_effect=cancel.Cancelled), \
                patch.object(build, "image_stats", return_value=(90.0, 30.0)):
            with self.assertRaises(cancel.Cancelled):
                with txn.build_txn(self.p, "hero"):
                    build.run_build(self.p, "hero", [1], None, 0.13, 1.0, 0.5, 0.8, None, True, "EVA02_Large",
                                    False, False, False, True, upscale_to=128, fresh=True)
        self.assertEqual(self.files(cache), before)
        self.assertEqual(self.files(self.char), before_current)
