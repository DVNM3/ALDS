import io
import threading
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from alds import aitk, cancel, gui, scan, selftest
from alds.i18n import use
from test_preservation import ProjectTest


class JobTests(ProjectTest):
    def setUp(self):
        super().setUp()
        settings = patch.object(aitk, "SETTINGS", self.p.dir / "settings.json")
        settings.start()
        self.addCleanup(settings.stop)
        aitk.save_settings(ui_lang="en")
        self.addCleanup(lambda: gui.stop_running_job(10))
        self.release = threading.Event()

    def slow(self):
        print("Step 1")
        self.release.wait(10)
        print("Step 2")
        return "result"

    def test_closing_the_page_leaves_the_action_running(self):
        stream = gui.streamed(self.slow, 0, 1)()
        self.assertEqual(next(stream), "Step 1\n")
        stream.close()
        job = gui.running_job()
        self.assertIsNotNone(job)
        self.release.set()
        job.thread.join(10)
        self.assertEqual(job.done["value"], "result")
        self.assertIn("Step 2", job.log.getvalue())

    def test_a_second_action_waits_for_the_running_one(self):
        stream = gui.streamed(self.slow, 0, 1)()
        next(stream)
        stream.close()
        with use("en"), self.assertRaises(gui.gr.Error) as err:
            next(gui.streamed(lambda: "other", 0, 1)())
        self.assertIn("still running", str(err.exception))
        with use("en"), self.assertRaises(gui.gr.Error):
            gui.do_clean(self.p.name, False, False)
        self.release.set()

    def test_a_reopened_page_follows_the_running_action(self):
        stream = gui.streamed(self.slow, 0, 1)()
        next(stream)
        stream.close()
        with use("en"):
            watch = gui.watch_job()
            panel, info, log, stop, seen = next(watch)
            self.assertTrue(panel["visible"] and seen)
            self.assertIn("has been running", info)
            self.assertIn("Step 1", log)
            self.release.set()
            *_, last = watch
        self.assertIn("finished", last[1])
        self.assertFalse(last[3]["visible"])

    def test_with_nothing_running_the_panel_stays_hidden(self):
        panel, *_, seen = next(gui.watch_job())
        self.assertFalse(panel["visible"])
        self.assertFalse(seen)

    def test_the_stop_button_still_stops_a_detached_action(self):
        def stoppable():
            print("Step 1")
            while True:
                cancel.check()
                self.release.wait(0.05)
        stream = gui.streamed(lambda: gui.captured(stoppable), 0, 1)()
        next(stream)
        stream.close()
        job = gui.running_job()
        gui.press_stop()
        job.thread.join(10)
        self.assertFalse(job.thread.is_alive())
        self.assertIn("error", job.done)


class DamagedVideoTests(ProjectTest):
    def test_unreadable_episodes_are_skipped_and_named(self):
        broken = Path(self.tmp.name) / "broken.mkv"
        broken.write_bytes(b"not a video at all" * 1000)
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as err:
            scan.run_scan(self.p, [str(broken)], [], 0.35, 5.0, auto_skip=False)
        self.assertIn("none of the episodes could be read", str(err.exception))
        self.assertIn("broken.mkv", out.getvalue())
        self.assertFalse((self.p.frames_dir / "v01").exists())

    def test_the_interface_explains_it(self):
        broken = Path(self.tmp.name) / "broken.mkv"
        broken.write_bytes(b"not a video at all" * 1000)
        with patch.object(gui, "PROJECTS_DIR", self.p.dir.parent), use("en"), self.assertRaises(gui.gr.Error) as err:
            gui.do_scan(self.p.name, [str(broken)], "", False, 40, 0.35, 5)
        self.assertIn("damaged", str(err.exception))


class CaptionTests(ProjectTest):
    def test_an_edited_caption_is_saved_when_moving_on(self):
        char = self.write_build(stems=("a",))
        png = next((char / "sorted").rglob("a.png"))
        Image.new("RGB", (8, 8)).save(png)
        files = [str(png)]
        with use("en"):
            gui.autosave_caption(self.p.name, "hero", files, 0, "generated a, smile ")
            self.assertEqual(png.with_suffix(".txt").read_text(encoding="utf-8"), "generated a, smile")
            stamp = png.with_suffix(".txt").stat().st_mtime_ns
            gui.autosave_caption(self.p.name, "hero", files, 0, "generated a, smile")
            self.assertEqual(png.with_suffix(".txt").stat().st_mtime_ns, stamp)
            png.unlink()
            gui.autosave_caption(self.p.name, "hero", files, 0, "something else")
        self.assertEqual(png.with_suffix(".txt").read_text(encoding="utf-8"), "generated a, smile")


class SelfTestFailureTests(ProjectTest):
    def test_a_failure_outside_a_step_says_why(self):
        video = Path(self.tmp.name) / "episode.mkv"
        video.write_bytes(b"video")
        with patch.object(selftest, "environment", return_value=[("ALDS", "x", "ok")]), \
                patch.object(selftest, "pipeline", side_effect=RuntimeError("no clusters to pick")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(selftest.run_selftest(str(video)), 1)
        self.assertIn("RuntimeError: no clusters to pick", out.getvalue())
