from .common import box_area, expand_box

THREE_QUARTER_OFFSET = 0.10
EYE_WIDTH_RATIO = 0.78
ONE_EYE_TAGS = ("one eye closed", "hair over one eye", "eyepatch", "one eye covered", "covering one eye")


def face_pose(frame_img, head_box, detect_faces, detect_eyes):
    if not head_box:
        return None
    W, H = frame_img.size
    region = frame_img.crop(expand_box(head_box, 1.3, W, H))
    faces = detect_faces(region)
    if not faces:
        return None
    fb = max(faces, key=lambda f: box_area(f[0]))[0]
    face = region.crop(fb)
    eyes = sorted(detect_eyes(face), key=lambda e: -e[2])[:2]
    if not eyes:
        return {"eyes": 0}
    xs = [(b[0] + b[2]) / 2 for b, _, _ in eyes]
    ws = [b[2] - b[0] for b, _, _ in eyes]
    return {"eyes": len(eyes), "offset": round(sum(xs) / len(xs) / face.width - 0.5, 3),
            "ratio": round(min(ws) / max(ws), 3) if len(ws) == 2 else 0.0}


def is_three_quarter(pose, general=()) -> bool:
    if not pose or pose.get("eyes", 0) == 0:
        return False
    if pose["eyes"] == 1:
        return not any(t in general for t in ONE_EYE_TAGS)
    return abs(pose["offset"]) >= THREE_QUARTER_OFFSET or pose["ratio"] < EYE_WIDTH_RATIO
