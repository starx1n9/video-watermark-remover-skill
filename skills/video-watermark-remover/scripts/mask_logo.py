# 第3步 静态 logo 蒙版：笔画(相对方差阈值) + 可选整块/横条矩形，出预览图给用户确认
# 原则：细元素(文字/射线)按笔画抠，笔画间真实背景留给模型参考；只有实心块或抠不全的细小字(如小英文行)才用矩形
# 用法:
#   python mask_logo.py --rel DIR/static_rel.npy --box 180,185,770,365 --thresh 0.5 \
#       [--block x0,y0,x1,y1 ...] [--clear x0,y0,x1,y1 ...] [--stroke-grow 1] [--pp-dilation 2] \
#       --preview A.mp4@120 --preview B.mp4@60 --out-dir DIR
#   没有 rel 图时可纯矩形: --shape 960x540 --block ...
import argparse, os, numpy as np, cv2, scipy.ndimage as nd
from vdw_common import check_env, bbox, grab, label
check_env(False)

def rect(s): return tuple(int(v) for v in s.split(","))
ap = argparse.ArgumentParser()
ap.add_argument("--rel"); ap.add_argument("--shape"); ap.add_argument("--box", type=rect)
ap.add_argument("--thresh", type=float, default=0.5); ap.add_argument("--min-area", type=int, default=10)
ap.add_argument("--stroke-grow", type=int, default=1, help="笔画外扩像素(盖住抗锯齿边)")
ap.add_argument("--close", type=int, default=1, help="笔画闭运算次数(补笔画内小洞)")
ap.add_argument("--block", type=rect, action="append", default=[], help="整块填充矩形(含端点)，可多次")
ap.add_argument("--clear", type=rect, action="append", default=[], help="先清空的矩形(再用 block 重画)")
ap.add_argument("--pp-dilation", type=int, default=2, help="之后 inpaint.py 用的 mask_dilation，用于报告实际修补范围")
ap.add_argument("--preview", action="append", default=[]); ap.add_argument("--out-dir", required=True)
a = ap.parse_args(); os.makedirs(a.out_dir, exist_ok=True)

if a.rel:
    rel = np.load(a.rel); H, W = rel.shape
    low = rel < a.thresh
    if a.box:
        b = np.zeros_like(low); b[a.box[1]:a.box[3] + 1, a.box[0]:a.box[2] + 1] = True; low &= b
    n, lab, st, _ = cv2.connectedComponentsWithStats(low.astype(np.uint8))
    core = np.zeros_like(low)
    for k in range(1, n):
        if st[k, 4] >= a.min_area: core |= lab == k
    if a.close: core = nd.binary_closing(core, iterations=a.close)
    if a.stroke_grow: core = nd.binary_dilation(core, iterations=a.stroke_grow)
else:
    W, H = map(int, a.shape.split("x")); core = np.zeros((H, W), bool)
for x0, y0, x1, y1 in a.clear: core[y0:y1 + 1, x0:x1 + 1] = False
for x0, y0, x1, y1 in a.block: core[y0:y1 + 1, x0:x1 + 1] = True

np.save(os.path.join(a.out_dir, "mask.npy"), core)
cv2.imwrite(os.path.join(a.out_dir, "mask.png"), core.astype(np.uint8) * 255)
eff = nd.binary_dilation(core, iterations=a.pp_dilation) if a.pp_dilation else core
fea = nd.binary_dilation(core, iterations=a.pp_dilation + 2 + 2)
bb = bbox(core)
if bb is None: raise SystemExit("蒙版为空：检查 --box/--thresh")
print(f"蒙版像素 {int(core.sum())}  修补像素(含mask_dilation) {int(eff.sum())}")
print(f"  原元素范围   {bb[:2]}-{bb[2:]}")
print(f"  实际修补范围 {bbox(eff)[:2]}-{bbox(eff)[2:]}")
print(f"  含羽化最外圈 {bbox(fea)[:2]}-{bbox(fea)[2:]}   <- 叠新 logo 建议覆盖这个框")
rows = []
for spec in a.preview:
    path, _, k = spec.partition("@"); k = int(k or 0)
    f = grab(path, [k])[k]; o = f.copy()
    o[eff] = (0.45 * o[eff] + 0.55 * np.array([0, 0, 255])).astype(np.uint8)
    y0 = max(0, bb[1] - 60); y1 = min(H, bb[3] + 60)
    rows.append(np.hstack([label(f[y0:y1].copy(), f"{os.path.basename(path)} f{k}"), np.full((y1 - y0, 6, 3), 255, np.uint8), o[y0:y1]]))
if rows:
    w = max(r.shape[1] for r in rows)
    out = os.path.join(a.out_dir, "mask_preview.png"); cv2.imwrite(out, np.vstack(rows)); print("预览(左原片/右红色=将修补):", out)
