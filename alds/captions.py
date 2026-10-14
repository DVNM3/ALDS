import re
from collections import Counter

COUNT_RE = re.compile(r"^(\d\+?(girl|boy|other)s?|multiple (girls|boys|others))$")
RATING_MAP = {"general": "safe", "sensitive": "sensitive", "questionable": "nsfw", "explicit": "explicit"}
DROP_TAGS = {"anime screencap", "parody"}

COLORS = {"aqua", "black", "blue", "brown", "green", "grey", "gray", "orange", "pink", "purple", "red", "white",
          "yellow", "blonde", "silver", "gold", "golden", "amber", "light", "dark", "multicolored", "gradient",
          "two-tone", "streaked", "rainbow", "crimson", "magenta", "violet", "teal"}
HAIR_NOT_CORE = {"floating hair", "wet hair", "hand in own hair", "adjusting hair", "eyes visible through hair",
                 "holding hair", "playing with own hair", "hand in another's hair", "tucking hair", "pubic hair",
                 "armpit hair", "body hair", "chest hair", "leg hair", "wind-blown hair", "hair down"}
CORE_EXACT = {"ahoge", "bangs", "blunt bangs", "swept bangs", "parted bangs", "asymmetrical bangs", "crossed bangs",
              "sidelocks", "twintails", "low twintails", "short twintails", "ponytail", "high ponytail",
              "low ponytail", "side ponytail", "braid", "single braid", "twin braids", "french braid", "crown braid",
              "braided ponytail", "bob cut", "hime cut", "drill hair", "hair bun", "single hair bun",
              "double bun", "antenna hair", "hair intakes", "hair over one eye", "half updo", "one side up",
              "two side up", "hair flaps", "hair between eyes", "heterochromia", "tsurime", "tareme", "fang",
              "skin fang", "freckles", "dark skin", "dark-skinned female", "dark-skinned male", "pointy ears",
              "animal ears", "cat ears", "fox ears", "wolf ears", "dog ears", "rabbit ears", "horns", "tail",
              "cat tail", "fox tail", "wolf tail", "facial mark", "flat chest", "small breasts", "medium breasts",
              "large breasts", "huge breasts", "facial hair", "beard", "mustache", "stubble"}
CORE_FREQ = 0.2

FRAMING_TAGS = [("full body", "full_body"), ("cowboy shot", "cowboy_shot"), ("upper body", "upper_body"),
                ("portrait", "close_up"), ("close-up", "close_up")]
PORTRAIT_FRAMING = {"head": "close_up", "halfbody": "upper_body", "person": "full_body"}


def is_core_candidate(tag: str) -> bool:
    if tag in CORE_EXACT:
        return True
    words = tag.split()
    if tag.endswith(" hair") and tag not in HAIR_NOT_CORE:
        return True
    if tag.endswith(" eyes") and words[0] in COLORS:
        return True
    if tag.endswith(" pupils") or words[0] in ("mole", "scar"):
        return True
    return False


def find_core_tags(generals) -> set:
    n = len(generals)
    cnt = Counter(t for g in generals for t in g)
    return {t for t, c in cnt.items() if c / max(n, 1) >= CORE_FREQ and is_core_candidate(t)}


def rating_tag(rating: dict) -> str:
    return RATING_MAP.get(max(rating, key=rating.get), "safe")


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


def make_caption(trigger: str, rating: dict, general: dict, core: set, series=None, screencap=True) -> str:
    tags = [t for t, _ in sorted(general.items(), key=lambda kv: -kv[1])]
    counts = [t for t in tags if COUNT_RE.match(t)]
    rest = [t for t in tags if not COUNT_RE.match(t) and t not in core and t not in DROP_TAGS]
    head = (["anime screencap"] if screencap else []) + [rating_tag(rating)]
    return ", ".join(head + counts + [trigger] + ([series] if series else []) + rest)
