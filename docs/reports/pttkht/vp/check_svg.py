# Kiểm tra bố cục sơ đồ VP từ SVG do ExportDiagramImage xuất:
#  - chữ của quan hệ (tên, multiplicity, role, stereotype) đè lên chữ khác
#  - chữ của quan hệ đè lên hình (lớp, use case, actor, ghi chú)
#  - đoạn thẳng của đường nối đi xuyên qua một hình không phải hai đầu của nó
#  - chữ bất kỳ đè lên dòng watermark của VP
#  - chữ của quan hệ bị một đường nối cắt ngang; hai nhãn cùng dòng dính sát nhau
# Dùng: python3 check_svg.py thư_mục_svg
import re
import sys
import glob
import os
import xml.etree.ElementTree as ET
from PIL import ImageFont

NS = "{http://www.w3.org/2000/svg}"
_FONTS = {}


def font(bold, size):
    k = (bold, size)
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), size)
    return _FONTS[k]


def tr(el):
    t = el.get("transform") or ""
    m = re.search(r"translate\(([-\d.]+)[ ,]+([-\d.]+)\)", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"matrix\(([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)\)", t)
    if m:
        return float(m.group(5)), float(m.group(6))
    return 0.0, 0.0


def rotated(el):
    t = el.get("transform") or ""
    return "rotate" in t or ("matrix" in t and not re.search(r"matrix\(1[ ,]+0[ ,]+0[ ,]+1", t))


class Item:
    def __init__(self, kind, owner, box, text=None, seg=None):
        self.kind, self.owner, self.box, self.text, self.seg = kind, owner, box, text, seg
        self.ell = False
        self.clip = None       # vùng được vẽ (đa giác, chẵn-lẻ) — VP khoét lỗ quanh nhãn của chính đường nối


CLIPS = {}


def clip_polys(d):
    polys = []
    for sub in re.split(r"(?=M)", d):
        nums = [float(n) for n in re.findall(r"[-\d.]+", sub)]
        if len(nums) >= 6:
            polys.append(list(zip(nums[0::2], nums[1::2])))
    return polys


def in_clip(x, y, polys):
    inside_ = False
    for poly in polys:
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside_ = not inside_
    return inside_


def clip_of(el, ox, oy):
    m = re.search(r"url\(#([^)]+)\)", el.get("clip-path") or "")
    if not m or m.group(1) not in CLIPS:
        return None
    return [[(x + ox, y + oy) for x, y in poly] for poly in CLIPS[m.group(1)]]


def walk(el, ox, oy, owner, out, bold=False, rot=False, size=11, dashed=False):
    dx, dy = tr(el)
    ox, oy = ox + dx, oy + dy
    rot = rot or rotated(el)
    mid = el.get("model-id")
    if mid:
        owner = mid
    if el.get("font-weight") in ("bold", "700"):
        bold = True
    if el.get("stroke-dasharray") not in (None, "none"):
        dashed = True
    m = re.match(r"([\d.]+)", el.get("font-size") or "")
    if m:
        size = round(float(m.group(1)))
    tag = el.tag.replace(NS, "")
    if tag in ("defs", "clipPath"):
        return
    if tag == "text" and "".join(el.itertext()).strip() and not rot:
        s = "".join(el.itertext()).strip()
        x, y = float(el.get("x", 0)) + ox, float(el.get("y", 0)) + oy
        w = font(bold, size).getlength(s)
        out.append(Item("text", owner, (x, y - size * 0.9, x + w, y + size * 0.25), text=s))
    elif tag == "line":
        x1, y1, x2, y2 = (float(el.get(k, 0)) for k in ("x1", "y1", "x2", "y2"))
        dashed = dashed or (el.get("stroke-dasharray") not in (None, "none"))
        it = Item("seg", owner, None, seg=(x1 + ox, y1 + oy, x2 + ox, y2 + oy))
        it.clip = clip_of(el, ox, oy)
        it.dashed = dashed
        out.append(it)
    elif tag == "path":
        nums = [float(n) for n in re.findall(r"[-\d.]+", el.get("d", ""))]
        pts = list(zip(nums[0::2], nums[1::2]))
        if pts:
            xs = [p[0] + ox for p in pts]; ys = [p[1] + oy for p in pts]
            d = el.get("d", "")
            closed = d.strip().upper().endswith("Z")
            if closed:
                it = Item("shape", owner, (min(xs), min(ys), max(xs), max(ys)))
                it.ell = bool(re.search(r"[CQA]", d))
                out.append(it)
            elif len(pts) >= 2:
                cl = clip_of(el, ox, oy)
                for (a, b), (c, d) in zip(pts, pts[1:]):
                    it = Item("seg", owner, None, seg=(a + ox, b + oy, c + ox, d + oy))
                    it.clip = cl
                    out.append(it)
    elif tag in ("polygon", "rect", "ellipse"):
        if tag == "polygon":
            nums = [float(n) for n in re.findall(r"[-\d.]+", el.get("points", ""))]
            xs, ys = nums[0::2], nums[1::2]
        elif tag == "rect":
            x, y, w, h = (float(el.get(k, 0)) for k in ("x", "y", "width", "height"))
            xs, ys = [x, x + w], [y, y + h]
        else:
            cx, cy, rx, ry = (float(el.get(k, 0)) for k in ("cx", "cy", "rx", "ry"))
            xs, ys = [cx - rx, cx + rx], [cy - ry, cy + ry]
        if xs:
            it = Item("shape", owner, (min(xs) + ox, min(ys) + oy, max(xs) + ox, max(ys) + oy))
            it.ell = tag == "ellipse"
            out.append(it)
    elif tag == "image":
        x, y = float(el.get("x", 0)) + ox, float(el.get("y", 0)) + oy
        out.append(Item("wm", owner, (x - 270, y - 4, x + float(el.get("width", 16)), y + float(el.get("height", 16)))))
    for ch in el:
        walk(ch, ox, oy, owner, out, bold, rot, size, dashed)


def inter(a, b, pad=0.0):
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def seg_hits_box(s, b, ell=False, clip=None):
    # đoạn thẳng có đi vào trong hình (đã co lại) không — kiểm tra bằng lấy mẫu; bỏ phần bị xén
    x1, y1, x2, y2 = s
    cx, cy, rx, ry = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2
    for i in range(1, 60):
        t = i / 60
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        if ell:
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1:
                return True
        elif b[0] < x < b[2] and b[1] < y < b[3] and (clip is None or in_clip(x, y, clip)):
            return True
    return False


def inside(t, b, tol=2):
    return t[0] >= b[0] - tol and t[2] <= b[2] + tol and t[1] >= b[1] - tol and t[3] <= b[3] + tol


def check(path, cross=True):
    root = ET.parse(path).getroot()
    CLIPS.clear()
    for cp in root.iter(NS + "clipPath"):
        for pa in cp:
            if pa.get("d"):
                CLIPS[cp.get("id")] = clip_polys(pa.get("d"))
    items = []
    walk(root, 0, 0, None, items)
    texts = [i for i in items if i.kind == "text"]
    wmt = [t for t in texts if "Powered" in t.text]
    texts = [t for t in texts if "Powered" not in t.text]
    W = max((i.box[2] for i in items if i.box), default=0)
    H = max((i.box[3] for i in items if i.box), default=0)
    # hình: path khép kín, bỏ khung System (chứa nhiều hình khác) và hình quá nhỏ (ô nhỏ của lớp, mũi tên)
    # VP identifies System boundaries explicitly. Actor associations must cross that boundary;
    # treating a small boundary (1–2 use cases) as an obstacle is a false positive.
    import json
    boundaries = {e.get('model-id') for e in root.iter() if e.get('model-id') and
                  json.loads(e.get('data', '{}')).get('modelType') == 'System'}
    raw0 = [i for i in items if i.owner not in boundaries and i.kind == "shape" and (i.box[2] - i.box[0]) > 18 and (i.box[3] - i.box[1]) > 12]
    ells = {tuple(round(v, 1) for v in i.box) for i in raw0 if i.ell}
    raw = list(dict.fromkeys(tuple(round(v, 1) for v in i.box) for i in raw0))
    big = [b for b in raw if sum(1 for o in raw if o != b and inside(o, b)) >= 3 or (b[3] - b[1]) > 480]
    # gộp các ngăn của một lớp: giữ hộp ngoài cùng
    shapes = [b for b in raw if b not in big and not any(o != b and o not in big and inside(b, o, 0.5) for o in raw)]
    labels = [t for t in texts if not any(inside(t.box, b) for b in shapes)]
    probs = []
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            if inter(a.box, b.box, 0.5):
                probs.append(f"CHỮ ĐÈ CHỮ  '{a.text}'  ×  '{b.text}' @{int(a.box[0])},{int(a.box[1])}")
            elif min(a.box[3], b.box[3]) - max(a.box[1], b.box[1]) > 3 and max(b.box[0] - a.box[2], a.box[0] - b.box[2]) < 6:
                probs.append(f"CHỮ DÍNH    '{a.text}'  ×  '{b.text}' @{int(a.box[0])},{int(a.box[1])}")
        for b in shapes:
            if inter(a.box, b, 1.0):
                probs.append(f"CHỮ ĐÈ HÌNH '{a.text}' trên hình @{int(b[0])},{int(b[1])}")
    for w in wmt:
        wb = (w.box[0] - 4, w.box[1] - 4, W, H)
        for t in texts:
            if inter(t.box, wb):
                probs.append(f"CHỮ ĐÈ WATERMARK '{t.text}'")
        for b in shapes:
            if inter(b, wb):
                probs.append(f"HÌNH ĐÈ WATERMARK @{int(b[0])},{int(b[1])}")
    # hình đè hình (không tính hình nằm trọn trong hình khác)
    for i, a in enumerate(shapes):
        for b in shapes[i + 1:]:
            if inter(a, b, 2.0) and not inside(a, b) and not inside(b, a):
                probs.append(f"HÌNH ĐÈ HÌNH @{int(a[0])},{int(a[1])} × @{int(b[0])},{int(b[1])}")
    if cross:
        segs = [i.seg for i in items if i.kind == "seg"
                and not (getattr(i, "dashed", False) and abs(i.seg[0] - i.seg[2]) < 1 and abs(i.seg[3] - i.seg[1]) > 40)]
        for t in labels:       # VP xén đường nối của chính nhãn đó quanh chữ; chỉ tính đường của quan hệ khác
            core = (t.box[0] + 1, t.box[1] + 2, t.box[2] - 1, t.box[3] - 1)
            for it in (i for i in items if i.kind == "seg"
                       and ((i.seg[2] - i.seg[0]) ** 2 + (i.seg[3] - i.seg[1]) ** 2) ** 0.5 >= 15):   # bỏ đầu mũi tên
                if seg_hits_box(it.seg, core, clip=it.clip):
                    probs.append(f"ĐƯỜNG CẮT CHỮ '{t.text}' @{int(t.box[0])},{int(t.box[1])}")
                    break
        for sg in segs:
            if any(inside((min(sg[0], sg[2]), min(sg[1], sg[3]), max(sg[0], sg[2]), max(sg[1], sg[3])), b, 0.5) for b in shapes):
                continue          # đường kẻ bên trong một hình (vạch ngăn của lớp, use case)
            for b in shapes:
                e = b in ells
                inner = (b[0] + 4, b[1] + 4, b[2] - 4, b[3] - 4)
                if inner[0] < inner[2] and inner[1] < inner[3] and seg_hits_box(sg, inner, e):
                    probs.append(f"ĐƯỜNG XUYÊN HÌNH @{int(b[0])},{int(b[1])} đoạn {tuple(int(v) for v in sg)}")
    return sorted(set(probs))


if __name__ == "__main__":
    total = 0
    for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.svg"))):
        p = check(f)
        total += len(p)
        print(f"== {os.path.basename(f)}: {len(p)}")
        for x in p:
            print("   ", x)
    print("TỔNG", total)
