# 第3步(字幕) 逐帧字幕笔画蒙版：亮笔画 top-hat + 时间稳定 + 居中单行约束 + 同句同蒙版
# 适用：固定位置、水平居中、单行、浅色字(白字带阴影)的字幕(压在画面上的)。深色字加 --dark
# 用法: python mask_subtitle.py VIDEO --out-dir DIR [--rows 489,518] [--center 480] [--preview-times 3,12,20,...]
#   不给 --rows 时自动在画面下 40% 找字幕行
import argparse, os, json, numpy as np, cv2
from vdw_common import check_env, probe, iter_frames, save_masks, bbox, grab, label, contact_sheet
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("--out-dir", required=True)
ap.add_argument("--rows", help="字幕文字所在行 y0,y1(全帧坐标)")
ap.add_argument("--center", type=int, help="字幕水平中心，默认画面中线")
ap.add_argument("--gap", type=int, default=30, help="从中心向两侧延伸时允许的最大空隙(px)")
ap.add_argument("--tophat", type=int, default=45); ap.add_argument("--bright", type=int, default=170)
ap.add_argument("--dark", action="store_true", help="深色字幕")
ap.add_argument("--shadow", default="3,3", help="阴影偏移 dx,dy；无阴影填 0,0")
ap.add_argument("--preview-times", default="")
a = ap.parse_args(); os.makedirs(a.out_dir, exist_ok=True)
info = probe(a.video); W, H, fps = info["width"], info["height"], info["fps"]
C = a.center or W // 2
ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
def strokes_raw(f):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    if a.dark: g = 255 - g
    t = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, ker)
    return ((t > a.tophat) & (g > a.bright)).astype(np.uint8)

# 1) 字幕行：未指定则在下 40%、中间 40% 宽度里按行统计亮笔画
if a.rows:
    R0, R1 = map(int, a.rows.split(","))
else:
    y_lo = int(H * 0.6); acc = np.zeros(H - y_lo)
    idx = set(np.linspace(0, info["frames"] - 1, 60).astype(int).tolist())
    for k, f in enumerate(iter_frames(a.video)):
        if k in idx: acc += strokes_raw(f[y_lo:])[:, int(W * 0.3):int(W * 0.7)].sum(1)
    med = float(np.median(acc)); pk = float(acc.max())
    if pk < med * 1.8 + 1: raise SystemExit("没找到明显的字幕行(峰值不突出)，用 --rows 手动指定")
    thr = med + 0.5 * (pk - med)                         # 半高阈值：纹理多的背景下中位数本身就高，不能用倍数
    rows = np.where(acc > thr)[0]
    segs = np.split(rows, np.where(np.diff(rows) > 2)[0] + 1)
    best = max(segs, key=lambda s: acc[s].sum())         # 取能量最大的连续段
    R0, R1 = y_lo + int(best[0]) - 3, y_lo + int(best[-1]) + 3
print(f"字幕行 y{R0}-{R1}  中心 x{C}")
Y0, Y1 = max(0, R0 - 21), min(H, R1 + 22)              # 处理横带(含阴影/外扩余量)
r0, r1 = R0 - Y0, R1 - Y0 + 1

TH = [strokes_raw(f) for f in iter_frames(a.video, (0, Y0, W, Y1))]
N = len(TH)
def T(i): return TH[min(max(i, 0), N - 1)]
def strokes(i):
    s_a = T(i) & T(i - 4) & T(i - 8); s_b = T(i) & T(i + 4) & T(i + 8)   # 字幕停留、背景在动
    txt = (s_a | s_b).astype(np.uint8); txt[:r0] = 0; txt[r1:] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(txt)
    keep = np.zeros_like(txt)
    for k in range(1, n):
        if st[k, 4] >= 3: keep[lab == k] = 1
    col = keep.any(0)
    if not col[max(0, C - 40):C + 40].any(): return np.zeros_like(keep)
    L = R = C
    for step in (-1, 1):                                                  # 从中心向两侧连续延伸
        x = C; gap = 0
        while 0 < x < W - 1:
            x += step; gap = 0 if col[x] else gap + 1
            if gap > a.gap: break
            if col[x]:
                if step < 0: L = x
                else: R = x
    h = min(C - L, R - C) + 24                                            # 居中对称：裁掉单侧多出的背景亮条
    L = max(L, C - h); R = min(R, C + h)
    keep[:, :L] = 0; keep[:, R + 1:] = 0
    return keep
dx, dy = map(int, a.shadow.split(","))
def grow(keep):
    m = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    if dx or dy:
        sh = np.zeros_like(m); sh[dy:, dx:] = m[:m.shape[0] - dy, :m.shape[1] - dx]; m |= sh
    return cv2.dilate(m, np.ones((3, 3), np.uint8))
D = [grow(strokes(i)) for i in range(N)]

# 2) 按句分组，同句取并集；再前后各扩 3 帧盖淡入淡出
def iou(p, q):
    p, q = p > 0, q > 0; u = (p | q).sum()
    return 1.0 if u == 0 else (p & q).sum() / u
gid = np.zeros(N, int); g = 0; ref = D[0]
for i in range(1, N):
    if iou(D[i - 1], D[i]) < 0.3 or iou(ref, D[i]) < 0.5: g += 1; ref = D[i]
    elif D[i].sum() > ref.sum(): ref = D[i]
    gid[i] = g
GM = {}
for i in range(N): GM[gid[i]] = GM.get(gid[i], 0) | D[i]
M = np.zeros((N, Y1 - Y0, W), bool)
for i in range(N):
    for j in range(max(0, i - 3), min(N, i + 4)): M[i] |= GM[gid[j]] > 0
save_masks(os.path.join(a.out_dir, "masks.npz"), M, Y0)
U = M.any(0); bb = bbox(U)
groups = []
for gg in range(g + 1):
    fr = np.where(gid == gg)[0]; b = bbox(GM[gg] > 0)
    if b: groups.append(dict(start=int(fr[0]), end=int(fr[-1]), x0=b[0], x1=b[2]))
json.dump(dict(rows=[R0, R1], band=[Y0, Y1], center=C, groups=groups,
               union_box=[bb[0], bb[1] + Y0, bb[2], bb[3] + Y0] if bb else None), open(os.path.join(a.out_dir, "subtitle_info.json"), "w"), ensure_ascii=False)
print(f"{N} 帧, {len(groups)} 句, 有字幕帧 {int(M.any((1,2)).sum())}")
if bb: print(f"蒙版并集 ({bb[0]},{bb[1]+Y0})-({bb[2]},{bb[3]+Y0})  单帧平均面积 {int(M.sum((1,2)).mean())}")
wide = [x for x in groups if x["x0"] < W * 0.1 or x["x1"] > W * 0.9]
if wide: print("⚠ 以下句子蒙版贴近画面边缘，可能误抠背景，看预览:", [(x["start"], x["x0"], x["x1"]) for x in wide])

# 3) 预览
ts = [float(t) for t in a.preview_times.split(",") if t] or list(np.linspace(1, info["duration"] - 1, 12))
idx = [min(N - 1, int(t * fps)) for t in ts]; fr = grab(a.video, idx); tiles = []
for k in idx:
    f = fr[k][Y0:Y1].copy(); o = f.copy(); m = M[k]
    o[m] = (0.4 * o[m] + 0.6 * np.array([0, 0, 255])).astype(np.uint8)
    tiles.append(np.hstack([label(f, f"{k/fps:.1f}s"), np.full((Y1 - Y0, 4, 3), 255, np.uint8), o]))
out = os.path.join(a.out_dir, "subtitle_mask_preview.png"); cv2.imwrite(out, contact_sheet(tiles, 1)); print("预览(左原片/右红色=将修补):", out)
