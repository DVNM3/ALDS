from collections import Counter

from alds import captions, gui, tags, txn, versions
from alds.i18n import use
from test_preservation import ProjectTest


class CategoryTests(ProjectTest):
    def test_appearance_tags_are_grouped_by_kind(self):
        expected = {
            "blue hair": "hair_colour", "light brown hair": "hair_colour", "two-tone hair": "hair_colour",
            "short hair": "hair_length", "very long hair": "hair_length",
            "bob cut": "hairstyle", "pixie cut": "hairstyle", "undercut": "hairstyle", "spiked hair": "hairstyle",
            "side ponytail": "hairstyle", "twin braids": "hairstyle", "one side up": "hairstyle",
            "hair over one eye": "hairstyle",
            "hair ribbon": "hair_accessory", "scrunchie": "hair_accessory", "hair tie": "hair_accessory",
            "yellow hairband": "hair_accessory", "x hair ornament": "hair_accessory", "hairclip": "hair_accessory",
            "tattoo": "marks", "shoulder tattoo": "marks", "facial mark": "marks", "mole under eye": "marks",
            "scar across eye": "marks", "freckles": "marks",
            "earrings": "piercing", "ear piercing": "piercing",
            "blue eyes": "eyes", "slit pupils": "eyes", "heterochromia": "eyes",
            "black nails": "makeup", "lipstick": "makeup",
            "dark skin": "body", "facial hair": "body", "cat ears": "body", "large breasts": "body",
            "striped bikini": "clothing", "detached sleeves": "clothing", "sundress": "clothing", "scarf": "clothing",
            "anime coloring": "style", "1990s (style)": "style", "watercolor (medium)": "style",
        }
        self.assertEqual({tag: captions.tag_category(tag) for tag in expected}, expected)

    def test_actions_and_moods_are_not_appearance(self):
        for tag in ("holding hair ornament", "adjusting hair", "hand on own hair", "tying hair", "hair tie in mouth",
                    "scared", "closed eyes", "floating hair", "wet hair", "constricted pupils", "1girl", "smile",
                    "grabbing another's hair"):
            self.assertIsNone(captions.tag_category(tag), tag)

    def test_goal_lists_checks_frequent_tags_and_skips_fixed_ones(self):
        counts = Counter({"blue hair": 9, "hair ribbon": 2, "tattoo": 5, "skirt": 8, "anime coloring": 6,
                          "hero": 10, "hero_outfit1": 6})
        rows = captions.goal_suggestions(counts, 10, "character", lambda tag: tag.startswith("hero"))
        self.assertEqual([(r["tag"], r["suggested"]) for r in rows],
                         [("blue hair", True), ("hair ribbon", True), ("tattoo", True)])
        rows = captions.goal_suggestions(counts, 10, "outfit")
        self.assertEqual([r["tag"] for r in rows], ["skirt", "hair ribbon"])
        self.assertEqual([r["tag"] for r in captions.goal_suggestions(counts, 10, "style")], ["anime coloring"])
        self.assertFalse(captions.goal_suggestions(counts, 20, "character")[1]["suggested"])


class RecoveryTests(ProjectTest):
    def test_details_seen_clearly_elsewhere_are_kept_when_less_sure(self):
        generals = [{"shoulder tattoo": 0.8, "solo": 1.0}] * 4 + [{"solo": 1.0}] * 3
        scores = [dict(g) for g in generals[:4]] + [
            {"solo": 1.0, "shoulder tattoo": 0.3, "tattoo": 0.5},
            {"solo": 1.0, "shoulder tattoo": 0.15},
            {"solo": 1.0, "blue hair": 0.3, "shoulder tattoo": 0.25}]
        found, added = captions.recover_details(generals, scores)
        self.assertEqual(added, Counter({"shoulder tattoo": 2}))
        self.assertIn("shoulder tattoo", found[4])
        self.assertNotIn("shoulder tattoo", found[5])
        self.assertNotIn("blue hair", found[6])

    def test_details_seen_in_too_few_images_are_not_added(self):
        generals = [{"hair ribbon": 0.8}] * 2 + [{}] * 5
        scores = [dict(g) for g in generals[:2]] + [{"hair ribbon": 0.3}] * 5
        found, added = captions.recover_details(generals, scores)
        self.assertEqual(added, Counter())
        self.assertEqual(found[2:], [{}] * 5)


class TriggerBoxTests(ProjectTest):
    def caption(self, char, stem):
        return next((char / "sorted").rglob(stem + ".txt")).read_text(encoding="utf-8")

    def test_absorbed_tags_return_to_their_places_and_undo_restores_the_box(self):
        char = self.write_build(captions={"a": "safe, 1girl, hero, blue hair, long hair, smile",
                                          "b": "safe, 1girl, hero, smile, long hair"})
        self.assertEqual(tags.absorb(char, ["blue hair", "long hair"]), 2)
        self.assertEqual(self.caption(char, "a"), "safe, 1girl, hero, smile")
        self.assertEqual(self.caption(char, "b"), "safe, 1girl, hero, smile")
        self.assertEqual({t: sorted(w) for t, w in tags.load_box(char).items()},
                         {"blue hair": ["a"], "long hair": ["a", "b"]})
        self.assertEqual(tags.restore(char, ["blue hair", "long hair"]), 2)
        self.assertEqual(self.caption(char, "a"), "safe, 1girl, hero, blue hair, long hair, smile")
        self.assertEqual(self.caption(char, "b"), "safe, 1girl, hero, smile, long hair")
        self.assertEqual(tags.load_box(char), {})
        tags.undo_last(char)
        self.assertEqual(self.caption(char, "a"), "safe, 1girl, hero, smile")
        self.assertEqual(set(tags.load_box(char)), {"blue hair", "long hair"})
        tags.undo_last(char)
        self.assertEqual(self.caption(char, "a"), "safe, 1girl, hero, blue hair, long hair, smile")
        self.assertEqual(tags.load_box(char), {})
        self.assertEqual(tags.load_edits(char), [])

    def test_restoring_one_tag_keeps_the_rest_in_the_trigger(self):
        char = self.write_build(captions={"a": "hero, blue hair, tattoo, smile"})
        tags.absorb(char, ["blue hair", "tattoo"])
        tags.restore(char, ["tattoo"])
        self.assertEqual(self.caption(char, "a"), "hero, tattoo, smile")
        self.assertEqual(list(tags.load_box(char)), ["blue hair"])

    def test_trigger_series_and_outfit_tags_stay(self):
        char = self.write_build(captions={"a": "hero, fairy tail, hero_outfit1, blue hair"})
        meta = self.p.load("characters/hero/build.json")
        outfit = {"id": 1, "token": "hero_outfit1", "count": 1, "tags": []}
        self.p.save("characters/hero/build.json", {**meta, "name": "hero", "series": "fairy tail", "outfits": [outfit]})
        with use("en"):
            gui.tag_absorb(self.p.name, "hero", ["hero", "fairy tail", "hero_outfit1", "blue hair"], "")
            self.assertEqual(self.caption(char, "a"), "hero, fairy tail, hero_outfit1")
            with self.assertRaises(gui.gr.Error):
                gui.tag_absorb(self.p.name, "hero", ["hero_outfit1"], "")
            gui.tag_restore(self.p.name, "hero", ["blue hair"], "")
        self.assertEqual(self.caption(char, "a"), "hero, fairy tail, hero_outfit1, blue hair")

    def test_goal_view_lists_suggestions_and_the_box(self):
        self.write_build(captions={"a": "hero, blue hair, tattoo, skirt", "b": "hero, blue hair, skirt"})
        with use("en"):
            tag_list, legend, box, note = gui.goal_view(self.p.name, "hero", "character")
            self.assertEqual([v for _, v in tag_list["choices"]], ["blue hair", "tattoo"])
            self.assertEqual(tag_list["value"], ["blue hair", "tattoo"])
            self.assertIn("hair colour", legend)
            self.assertEqual(box["choices"], [])
            gui.tag_absorb(self.p.name, "hero", ["blue hair"], "")
            tag_list, _, box, note = gui.goal_view(self.p.name, "hero", "character")
            self.assertEqual([v for _, v in tag_list["choices"]], ["tattoo"])
            self.assertEqual(box["choices"], [("blue hair · 2", "blue hair")])
            self.assertIn("put it back", note)
            self.assertEqual([v for _, v in gui.goal_view(self.p.name, "hero", "outfit")[0]["choices"]], ["skirt"])

    def test_box_actions_wait_for_the_character_being_rebuilt(self):
        char = self.write_build(captions={"a": "hero, blue hair"})
        with gui.working_on(char), use("en"):
            with self.assertRaises(gui.gr.Error):
                gui.tag_absorb(self.p.name, "hero", ["blue hair"], "")
            with self.assertRaises(gui.gr.Error):
                gui.tag_restore(self.p.name, "hero", ["blue hair"], "")

    def test_rebuild_keeps_the_box_out_of_new_captions_and_can_put_it_back(self):
        char = self.write_build(captions={"a": "hero, blue hair, smile", "b": "hero, blue hair, grin"})
        tags.absorb(char, ["blue hair"])
        with txn.build_txn(self.p, "hero"):
            self.write_build(("a", "c"), captions={"a": "hero, blue hair, smile, tattoo",
                                                   "c": "hero, smile, blue hair"})
        self.assertEqual(self.caption(char, "a"), "hero, smile, tattoo")
        self.assertEqual(self.caption(char, "c"), "hero, smile")
        self.assertEqual(sorted(tags.load_box(char)["blue hair"]), ["a", "b", "c"])
        self.assertEqual(versions.load_json(char / "review.json")["captions"], {})
        tags.restore(char, ["blue hair"])
        self.assertEqual(self.caption(char, "a"), "hero, blue hair, smile, tattoo")
        self.assertEqual(self.caption(char, "c"), "hero, smile, blue hair")

    def test_versions_keep_the_box(self):
        char = self.write_build(captions={"a": "hero, blue hair"})
        version = versions.save_version(self.p, "hero")
        tags.absorb(char, ["blue hair"])
        versions.restore_version(self.p, "hero", version)
        self.assertEqual(tags.load_box(char), {})
        self.assertEqual(self.caption(char, "a"), "hero, blue hair")


class BuildCaptionTests(ProjectTest):
    def test_captions_keep_every_tag(self):
        caption = captions.make_caption("hero", {"general": 0.9}, {"blue hair": 0.9, "1girl": 0.99, "solo": 0.95,
                                                                   "parody": 0.5}, "fairy tail")
        self.assertEqual(caption, "anime screencap, safe, 1girl, hero, fairy tail, solo, blue hair")
        self.assertEqual(captions.appearance_tags([{"blue hair": 1, "smile": 1}, {"blue hair": 1, "tattoo": 1}] * 3
                                                  + [{"tattoo": 1}] * 4), ["blue hair", "tattoo"])
