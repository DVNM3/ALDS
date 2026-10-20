import io
from contextlib import redirect_stdout
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

from alds import __version__, aitk, common, selftest, updates
from test_preservation import ProjectTest


class UpdateTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.settings = patch.object(aitk, "SETTINGS", self.p.dir / "settings.json")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        updates._found.clear()
        self.addCleanup(updates._found.clear)

    def test_only_a_newer_release_is_reported(self):
        major, minor, fix = updates.version_tuple(__version__)
        for tag, expected in ((f"v{major}.{minor + 1}.0", True), (f"v{__version__}", False),
                              (f"v{major}.{minor}.{max(fix - 1, 0)}", False)):
            with patch.object(updates, "latest_tag", return_value=tag):
                self.assertEqual(updates.check(), tag if expected else None)

    def test_no_internet_is_quiet(self):
        with patch.object(updates, "latest_tag", side_effect=OSError("offline")):
            self.assertIsNone(updates.check())

    def test_the_check_can_be_turned_off(self):
        aitk.save_settings(check_updates=False)
        with patch.object(updates.threading, "Thread") as thread:
            updates.start()
        thread.assert_not_called()


class SelfTestTests(ProjectTest):
    def test_check_fails_when_a_package_is_missing(self):
        real = metadata.version

        def version(name):
            if name == "av":
                raise metadata.PackageNotFoundError(name)
            return real(name)
        with patch.object(selftest.metadata, "version", side_effect=version), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(selftest.run_check(), 1)
        self.assertIn("missing", out.getvalue())

    def test_the_shortest_scanned_episode_is_used_by_default(self):
        videos = []
        for name, minutes in (("long.mkv", 24), ("short.mkv", 4), ("gone.mkv", 1)):
            path = Path(self.tmp.name) / name
            if name != "gone.mkv":
                path.write_bytes(b"video")
            videos.append({"id": len(videos) + 1, "path": str(path), "duration": minutes * 60})
        self.p.save("project.json", {"videos": videos})
        self.assertEqual(selftest.pick_video(None).name, "short.mkv")
        with self.assertRaises(SystemExit):
            selftest.pick_video(str(Path(self.tmp.name) / "missing.mkv"))

    def test_without_any_episode_it_asks_for_one(self):
        with self.assertRaises(SystemExit) as err:
            selftest.pick_video(None)
        self.assertIn("selftest", str(err.exception))

    def test_a_failed_step_is_reported_and_stops_the_run(self):
        steps = selftest.Steps()
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(AssertionError):
            with steps.step("Broken step"):
                print("detail from the step")
                selftest.check(False, "it broke")
        self.assertIn("[failed]", out.getvalue())
        self.assertIn("detail from the step", out.getvalue())
        self.assertEqual(steps.rows[0][2], "fail")
