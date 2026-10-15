import re
from collections import Counter

COUNT_RE = re.compile(r"^(\d\+?(girl|boy|other)s?|multiple (girls|boys|others))$")
RATING_MAP = {"general": "safe", "sensitive": "sensitive", "questionable": "nsfw", "explicit": "explicit"}
DROP_TAGS = {"anime screencap", "parody"}

COLORS = {"aqua", "black", "blue", "brown", "green", "grey", "gray", "orange", "pink", "purple", "red", "white",
          "yellow", "blonde", "silver", "gold", "golden", "amber", "light", "dark", "multicolored", "gradient",
          "two-tone", "streaked", "rainbow", "crimson", "magenta", "violet", "teal", "platinum", "lavender",
          "navy", "cyan", "maroon", "beige"}
ACTION_WORDS = {"holding", "covering", "adjusting", "rubbing", "playing", "tying", "untying", "pulling", "grabbing",
                "touching", "wiping", "fixing", "removing", "drying", "brushing", "combing", "cutting", "biting",
                "licking", "kissing", "stroking", "petting", "lifting", "tugging", "tucking", "fiddling", "putting",
                "taking", "looking", "pointing", "reaching"}
ACTION_STARTS = ("hand on", "hands on", "hand in", "hands in", "hand to", "hands to", "hand over", "hands over",
                 "hand under", "hand between", "arm behind", "arms behind", "arm around", "arms around")
NOT_APPEARANCE = {"floating hair", "wet hair", "wind-blown hair", "pubic hair", "armpit hair", "body hair", "leg hair",
                  "arm hair", "constricted pupils", "dilated pupils", "no pupils", "eyebrows visible through hair",
                  "eyelashes visible through hair", "raised eyebrows", "raised eyebrow", "v-shaped eyebrows",
                  "hair spread out", "hair lift", "hair blowing", "eyes visible through hair"}
STYLE_TAGS = {"anime screencap", "anime coloring", "official style", "official art", "retro artstyle", "flat color",
              "cel shading", "parody", "style parody", "realistic", "sketch", "lineart", "monochrome", "greyscale",
              "sepia", "traditional media", "faux traditional media", "oekaki", "pixel art", "chibi", "super deformed",
              "blurry", "blurry background", "blurry foreground", "depth of field", "chromatic aberration",
              "film grain", "lens flare", "bloom", "letterboxed", "pillarboxed", "game cg", "jaggy lines",
              "limited palette", "spot color", "no lineart", "colored lineart", "thick outlines", "outline",
              "dithering", "halftone", "scanlines", "motion blur", "motion lines", "speed lines", "emphasis lines",
              "fake screenshot", "screencap", "cover", "cover page", "comic", "4koma", "photorealistic",
              "shiny skin", "glint", "sparkle", "light particles"}
MARK_WORDS = {"tattoo", "tattoos", "scar", "scars", "mole", "moles", "freckles", "birthmark", "markings", "mark",
              "marks", "bruise"}
PIERCING_WORDS = {"piercing", "piercings", "earring", "earrings"}
HAIR_ACCESSORIES = ("hair ornament", "hairclip", "hair clip", "hairpin", "hair pin", "hairband", "hair band",
                    "headband", "scrunchie", "hair ribbon", "hair bow", "hair tie", "hair flower", "hair bobbles",
                    "hair tubes", "hair stick", "hair beads", "hair bell", "kanzashi", "hair scarf")
HAIR_LENGTHS = {"very short hair", "short hair", "medium hair", "long hair", "very long hair", "absurdly long hair",
                "bald"}
HAIR_COLOUR_EXTRA = {"colored inner hair", "split-color hair", "colored tips", "white streak", "hair streak"}
HAIRSTYLE_LAST = {"bangs", "ponytail", "ponytails", "braid", "braids", "twintails", "bun", "buns", "updo",
                  "sidelocks", "ahoge", "afro", "dreadlocks", "drill", "drills", "mohawk", "pompadour", "quiff",
                  "ringlets", "cornrows", "topknot", "chignon", "undercut", "cut", "locks", "intakes", "flaps"}
HAIRSTYLE_EXACT = {"hair over one eye", "hair over both eyes", "hair between eyes", "hair over eyes",
                   "hair over shoulder", "hair behind ear", "one side up", "two side up", "hair up", "hair down",
                   "hair rings", "hair slicked back", "hair pulled back", "antenna hair"}
EYE_EXACT = {"heterochromia", "tsurime", "tareme", "sanpaku", "eyepatch", "long eyelashes", "thick eyelashes",
             "thick eyebrows", "short eyebrows", "eyelashes", "slit pupils", "symbol-shaped pupils"}
MAKEUP_EXACT = {"makeup", "lipstick", "eyeshadow", "eyeliner", "mascara", "nail polish", "toenail polish", "lip gloss"}
BODY_EXACT = {"flat chest", "small breasts", "medium breasts", "large breasts", "huge breasts", "gigantic breasts",
              "dark skin", "dark-skinned female", "dark-skinned male", "pale skin", "tan", "tanned", "muscular",
              "muscular female", "muscular male", "toned", "toned male", "abs", "pectorals", "plump", "curvy",
              "petite", "skinny", "tall", "tall female", "wide hips", "thick thighs", "pointy ears", "long ears",
              "animal ears", "animal ear fluff", "fang", "fangs", "skin fang", "skin fangs", "sharp teeth", "horns",
              "single horn", "tail", "wings", "halo", "facial hair", "beard", "mustache", "stubble", "goatee",
              "sideburns", "long sideburns", "chest hair", "fat", "fat man", "old", "old man", "old woman",
              "mature female", "mature male", "colored skin"}
BODY_LAST = {"ears", "tail", "horns", "horn", "wings", "skin"}
CLOTHING_WORDS = {
    "shirt", "jacket", "coat", "vest", "dress", "uniform", "kimono", "yukata", "armor", "armour", "swimsuit",
    "bikini", "hoodie", "sweater", "cape", "cloak", "robe", "cardigan", "blazer", "serafuku", "tuxedo", "suit",
    "top", "camisole", "leotard", "bodysuit", "gown", "blouse", "tunic", "parka", "raincoat", "apron", "overalls",
    "sleeveless", "scarf", "haori", "poncho", "shawl", "corset", "bra", "necktie", "skirt", "pants", "shorts",
    "jeans", "trousers", "leggings", "pantyhose", "thighhighs", "kneehighs", "socks", "stockings", "shoes", "boots",
    "sneakers", "sandals", "heels", "loafers", "slippers", "gloves", "mittens", "hat", "cap", "beret", "hood",
    "helmet", "headwear", "headdress", "crown", "tiara", "veil", "mask", "glasses", "eyewear", "sunglasses",
    "goggles", "necklace", "choker", "collar", "pendant", "bracelet", "wristband", "armband", "armlet", "belt",
    "ribbon", "bow", "bowtie", "neckerchief", "sash", "obi", "jewelry", "brooch", "clothes", "clothing", "outfit",
    "costume", "lingerie", "panties", "underwear", "briefs", "trunks", "swimwear", "tankini", "sarong", "capelet",
    "gakuran", "hakama", "gauntlets", "pauldrons", "bandana", "bandeau", "garter", "garters", "headphones",
    "sleeves", "strapless", "halterneck", "off-shoulder", "cutout", "frills", "zipper", "buttons", "cuffs",
    "fur-trimmed", "trim", "print", "detached", "wristwatch", "earmuffs", "turtleneck", "t-shirt", "jersey",
    "pajamas", "nightgown", "negligee", "babydoll", "chemise", "tabard", "harness", "bodystocking", "loincloth",
    "fundoshi", "sarashi", "kilt", "epaulettes", "lanyard", "badge", "protector", "sundress", "miniskirt",
    "microskirt", "overskirt", "sweatshirt", "sweatpants", "undershirt", "bloomers", "buruma", "headscarf"}
APPEARANCE = ("hair_colour", "hair_length", "hairstyle", "hair_accessory", "eyes", "marks", "piercing", "makeup",
              "body")
GOALS = {"character": APPEARANCE, "outfit": ("clothing", "hair_accessory"), "style": ("style",)}
DETAILS = ("hair_accessory", "marks", "piercing")
SUGGEST_SHARE = 0.2
RECOVER_MIN, RECOVER_SHARE, RECOVER_COUNT = 0.2, 0.05, 3

FRAMING_TAGS = [("full body", "full_body"), ("cowboy shot", "cowboy_shot"), ("upper body", "upper_body"),
                ("portrait", "close_up"), ("close-up", "close_up")]
PORTRAIT_FRAMING = {"head": "close_up", "halfbody": "upper_body", "person": "full_body"}


def _is_action(tag, words):
    return (words[0] in ACTION_WORDS or tag.startswith(ACTION_STARTS) or "another's" in tag
            or tag.endswith((" in mouth", " removed", " lift", " grab", " pull")))


def _colour_words(words):
    return all(w in COLORS for w in words)


def tag_category(tag: str):
    tag = tag.strip()
    words = re.split(r"\s+", tag)
    if not tag or tag in NOT_APPEARANCE or _is_action(tag, words):
        return None
    if tag in STYLE_TAGS or tag.endswith(("(style)", "(medium)")) or "artstyle" in tag:
        return "style"
    if MARK_WORDS & set(words) or tag == "facial mark":
        return "marks"
    if PIERCING_WORDS & set(words):
        return "piercing"
    if any(a in tag for a in HAIR_ACCESSORIES):
        return "hair_accessory"
    if tag in BODY_EXACT:
        return "body"
    if tag in HAIR_LENGTHS:
        return "hair_length"
    if tag in HAIR_COLOUR_EXTRA or (words[-1] == "hair" and len(words) > 1 and _colour_words(words[:-1])):
        return "hair_colour"
    if (tag in HAIRSTYLE_EXACT or words[-1] in HAIRSTYLE_LAST or tag.endswith("side up")
            or (words[-1] == "hair" and len(words) > 1)):
        return "hairstyle"
    if tag in EYE_EXACT or (words[-1] in ("eyes", "pupils", "eyebrows", "eyelashes") and len(words) > 1
                            and _colour_words(words[:-1])):
        return "eyes"
    if tag in MAKEUP_EXACT or (words[-1] in ("nails", "lips", "lipstick", "eyeshadow", "eyeliner")
                               and len(words) > 1 and _colour_words(words[:-1])):
        return "makeup"
    if words[-1] in BODY_LAST and len(words) > 1:
        return "body"
    if CLOTHING_WORDS & set(re.split(r"[\s_()]+", tag)):
        return "clothing"
    return None


def goal_suggestions(counts: Counter, n: int, goal: str, skip=lambda tag: False):
    wanted = GOALS[goal]
    rows = []
    for tag, c in counts.items():
        cat = tag_category(tag)
        if cat in wanted and not skip(tag):
            rows.append({"tag": tag, "category": cat, "count": c, "suggested": c / max(n, 1) >= SUGGEST_SHARE})
    order = {c: i for i, c in enumerate(wanted)}
    return sorted(rows, key=lambda r: (order[r["category"]], -r["count"], r["tag"]))


def appearance_tags(generals) -> list:
    n = len(generals)
    cnt = Counter(t for g in generals for t in g)
    return sorted(t for t, c in cnt.items() if c / max(n, 1) >= SUGGEST_SHARE and tag_category(t) in APPEARANCE)


def low_scores(embs, tagger):
    import numpy as np
    from imgutils.tagging import convert_wd14_emb_to_prediction
    return convert_wd14_emb_to_prediction(np.stack(embs).astype(np.float32), model_name=tagger,
                                          general_threshold=RECOVER_MIN, no_underline=True, fmt="general")


def recover_details(generals, scores):
    from imgutils.tagging import drop_overlap_tags
    n = len(generals)
    cnt = Counter(t for g in generals for t in g if tag_category(t) in DETAILS)
    known = {t for t, c in cnt.items() if c >= max(RECOVER_COUNT, RECOVER_SHARE * n)}
    out, added = [], Counter()
    for general, score in zip(generals, scores):
        extra = {t: float(v) for t, v in score.items() if t in known and t not in general and v >= RECOVER_MIN}
        if extra:
            merged = drop_overlap_tags({**general, **extra})
            added.update(t for t in extra if t in merged)
            general = merged
        out.append(general)
    return out, added


def rating_tag(rating: dict) -> str:
    return RATING_MAP.get(max(rating, key=rating.get), "safe")


def people_count(general) -> int:
    total = 0
    for tag in general:
        m = COUNT_RE.match(tag)
        if m:
            total += 2 if tag.startswith("multiple") else int(tag[0])
    return total


def classify(crop_type: str, general: dict, portrait: str, pose=None):
    from .angles import is_three_quarter
    if crop_type == "head":
        framing = "close_up"
    else:
        framing = next((f for t, f in FRAMING_TAGS if t in general), PORTRAIT_FRAMING.get(portrait, "upper_body"))
    if "from behind" in general:
        view = "back"
    elif "from side" in general or "profile" in general:
        view = "side"
    elif "from above" in general:
        view = "above"
    elif "from below" in general:
        view = "below"
    elif is_three_quarter(pose, general):
        view = "three_quarter"
    else:
        view = "front"
    return framing, view


def make_caption(trigger: str, rating: dict, general: dict, series=None, screencap=True) -> str:
    tags = [t for t, _ in sorted(general.items(), key=lambda kv: -kv[1])]
    counts = [t for t in tags if COUNT_RE.match(t)]
    rest = [t for t in tags if not COUNT_RE.match(t) and t not in DROP_TAGS]
    head = (["anime screencap"] if screencap else []) + [rating_tag(rating)]
    return ", ".join(head + counts + [trigger] + ([series] if series else []) + rest)
