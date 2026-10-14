from pathlib import Path
from unittest.mock import patch

import av
import numpy as np

from alds import cancel, restore
from test_preservation import ProjectTest


class RestoreTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.source = Path(self.tmp.name) / "episode.mkv"
        with av.open(str(self.source), "w") as output:
            stream = output.add_stream("ffv1", rate=24)
            stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
            for n in range(16):
                image = np.random.default_rng(n).integers(0, 255, (48, 64, 3), dtype=np.uint8)
                for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        frames = []
        with av.open(str(self.source)) as container:
            stream = container.streams.video[0]
            video = {"id": 1, "path": str(self.source), "name": "episode", "width": 64, "height": 48,
                     "fps": float(stream.average_rate), "duration": round(container.duration / av.time_base, 1),
                     "source_sha256": restore.file_hash(self.source)}
            self.expected = {}
            for n, frame in enumerate(container.decode(stream)):
                if n in (2, 7, 13):
                    rel = f"frames/v01/{n:06d}.jpg"
                    frames.append({"vid": 1, "n": n, "t": round(float(frame.time), 3), "file": rel, "shot": 1})
                    path = Path(self.tmp.name) / f"expected-{n}.jpg"
                    restore.save_frame(frame, path)
                    self.expected[rel] = path.read_bytes()
        self.p.save("project.json", {"videos": [video], "frames_deleted": True})
        self.p.save("scan/frames.json", frames)
        self.p.save("scan/detections.json", [{"frame": i, "feat": i} for i in range(len(frames))])
        self.write_build()

    def test_restore_exact_frames_without_touching_scan_or_review(self):
        before_scan = self.files(self.p.scan_dir)
        before_char = self.files(self.p.char_dir("hero"))
        self.assertEqual(restore.restore_frames(self.p), 3)
        for rel, expected in self.expected.items():
            self.assertEqual(self.p.path(rel).read_bytes(), expected)
        self.assertEqual(self.files(self.p.scan_dir), before_scan)
        self.assertEqual(self.files(self.p.char_dir("hero")), before_char)
        self.assertFalse(self.p.load("project.json")["frames_deleted"])
        self.assertEqual(restore.restore_frames(self.p), 0)

    def test_existing_frame_is_never_overwritten(self):
        rel = next(iter(self.expected))
        path = self.p.path(rel)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"keep existing")
        self.assertEqual(restore.restore_frames(self.p), 2)
        self.assertEqual(path.read_bytes(), b"keep existing")

    def test_moved_source_folder_is_remembered_after_success(self):
        folder = Path(self.tmp.name) / "moved"
        folder.mkdir()
        self.source.rename(folder / self.source.name)
        restore.restore_frames(self.p, folder)
        self.assertEqual(self.p.load("project.json")["videos"][0]["path"], str((folder / self.source.name).resolve()))

    def test_missing_source_does_not_mutate_project(self):
        before = self.files(self.p.dir)
        self.source.unlink()
        with self.assertRaises(SystemExit):
            restore.restore_frames(self.p)
        self.assertEqual(self.files(self.p.dir), before)

    def test_changed_source_hash_rejected_before_writing(self):
        info = self.p.load("project.json")
        info["videos"][0]["source_sha256"] = "wrong"
        self.p.save("project.json", info)
        before = self.files(self.p.dir)
        with self.assertRaises(SystemExit):
            restore.restore_frames(self.p)
        self.assertEqual(self.files(self.p.dir), before)

    def test_cancel_mid_commit_removes_new_frames_and_restores_metadata(self):
        before = self.files(self.p.dir)
        def stop_save(*args):
            cancel.request()
            cancel.check()
        with patch.object(self.p, "save", side_effect=stop_save), self.assertRaises(cancel.Cancelled):
            restore.restore_frames(self.p)
        self.assertEqual(self.files(self.p.dir), before)
        self.assertFalse(self.p.frames_dir.exists())
        self.assertFalse(list(self.p.dir.glob(".restore-*")))

    def test_decoding_failure_leaves_no_partial_frames(self):
        before = self.files(self.p.dir)
        actual = restore.save_frame
        calls = 0
        def fail_second(frame, path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("decoder error")
            return actual(frame, path)
        with patch.object(restore, "save_frame", side_effect=fail_second), self.assertRaises(RuntimeError):
            restore.restore_frames(self.p)
        self.assertEqual(self.files(self.p.dir), before)
        self.assertFalse(self.p.frames_dir.exists())

    def test_legacy_project_without_hash_validates_frame_timestamps(self):
        info = self.p.load("project.json")
        del info["videos"][0]["source_sha256"]
        self.p.save("project.json", info)
        frames = self.p.load("scan/frames.json")
        frames[1]["t"] += 0.5
        self.p.save("scan/frames.json", frames)
        before = self.files(self.p.dir)
        with self.assertRaises(SystemExit):
            restore.restore_frames(self.p)
        self.assertEqual(self.files(self.p.dir), before)

    def test_absolute_frame_path_is_rejected(self):
        frames = self.p.load("scan/frames.json")
        frames[0]["file"] = str((self.p.frames_dir / "bad.jpg").resolve())
        self.p.save("scan/frames.json", frames)
        with self.assertRaises(SystemExit):
            restore.restore_frames(self.p)
        self.assertFalse(self.p.frames_dir.exists())

    def test_frames_inside_the_op_ed_are_not_restored(self):
        frames = self.p.load("scan/frames.json")
        frames[1]["auto"] = True
        self.p.save("scan/frames.json", frames)
        self.assertEqual(restore.restore_frames(self.p), 2)
        self.assertFalse(self.p.path(frames[1]["file"]).exists())
        self.assertFalse(self.p.load("project.json")["frames_deleted"])

    def test_restored_frames_are_not_left_marked_deleted(self):
        frames = self.p.load("scan/frames.json")
        frames[0]["deleted"] = True
        frames[1]["auto"] = True
        self.p.save("scan/frames.json", frames)
        restore.restore_frames(self.p)
        result = self.p.load("scan/frames.json")
        self.assertNotIn("deleted", result[0])
        self.assertTrue(result[1]["auto"])
