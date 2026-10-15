import ast
import unittest
from pathlib import Path

from alds.i18n import AR, t, use
from alds.upscale import INFO

SOURCE = Path(__file__).resolve().parent.parent / "alds"


def source_strings():
    calls, constants = set(), set(INFO.values())
    for path in SOURCE.glob("*.py"):
        if path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                constants.add(node.value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                calls.add(node.args[0].value)
    return calls, constants


class TranslationTests(unittest.TestCase):
    def test_every_message_has_an_arabic_translation(self):
        calls, _ = source_strings()
        self.assertEqual(sorted(text for text in calls if text not in AR), [])

    def test_no_translation_is_left_without_its_message(self):
        _, constants = source_strings()
        self.assertEqual(sorted(text for text in AR if text not in constants), [])

    def test_translations_keep_the_same_placeholders(self):
        import string
        fields = lambda text: sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)
        self.assertEqual([en for en, ar in AR.items() if fields(en) != fields(ar)], [])

    def test_command_line_messages_stay_in_english(self):
        self.assertEqual(t("Step {i} of {n}: {title}", i=1, n=3, title="x"), "Step 1 of 3: x")
        with use("ar"):
            self.assertIn("الخطوة", t("Step {i} of {n}: {title}", i=1, n=3, title="x"))
