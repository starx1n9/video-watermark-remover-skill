# 第7步 质检：数值指标 + 逐秒抽帧联系图 + 前后对比图
# ⚠ 数值全过也可能有"药丸色块"等局部幻觉 —— 必须打开联系图逐张肉眼看，这一步不能省
# 用法: python qc.py --orig IN.mp4 --out OUT.mp4 (--mask DIR/mask.npy | --masks DIR/masks.npz) [--bounds b.json]
#                    [--workdir W(读 ROI)] [--residue blue] [--times 3,12,20] --out-dir QC
import argparse, os, json, numpy as np, cv2, scipy.ndimage as nd
from vdw_common import check_env, probe, iter_frames, load_masks, bbox, label, contact_sheet
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("--orig", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--mask"); ap.add_argument("--masks"); ap.add_argument("--bounds"); ap.add_argument("--workdir")
ap.add_argument("--residue", default="none", choices=["none", "blue", "red", "green", "white"])
ap.add_argument("--times", default=""); ap.add_argument("--every", type=float, default=1.0, help="联系图抽帧间隔(秒)")
ap.add_argument("--out-dir", required=True)
a = ap.parse_args(); os.makedirs(a.out_dir, exist_ok=True)
io, iu = probe(a.orig), probe(a.out); N, W, H, fps = io["frames"], io["width"], io["height"], io["fps"]
print(f"帧数 原片 {N} / 成片 {iu['frames']}  时长 {io['duration']:.3f}/{iu['duration']:.3f}s" + ("" if N == iu["frames"] else "  ⚠ 不一致"))
static = np.load(a.mask).astype(bool) if a.mask else None
per = load_masks(a.masks, H, W) if a.masks else None
union = static.copy() if static is not None else per.union()
if per is not None and static is not None: union |= per.union()
eff_u = nd.binary_dilation(union, iterations=4)
ring_u = nd.binary_dilation(eff_u, iterations=10) & ~nd.binary_dilation(eff_u, iterations=3)
if a.workdir and os.path.exists(f"{a.workdir}/run_info.json"):
    rx0, ry0, rx1, ry1 = json.load(open(f"{a.workdir}/run_info.json"))["roi"]
else:
    b = bbox(nd.binary_dilation(union, iterations=16)); rx0, ry0, rx1, ry1 = b[0], b[1], b[2] + 1, b[3] + 1
outside = np.ones((H, W), bool); outside[ry0:ry1, rx0:rx1] = False
bb = bbox(eff_u); cx0, cy0 = max(0, bb[0] - 40), max(0, bb[1] - 40); cx1, cy1 = min(W, bb[2] + 41), min(H, bb[3] + 41)

def residue(img, m):
    if a.residue == "none": return 0
    p = img[m].astype(int); b, g, r = p[:, 0], p[:, 1], p[:, 2]
    if a.residue == "blue": s = (b > r + 45) & (b > g + 35)
    elif a.residue == "red": s = (r > b + 45) & (r > g + 35)
    elif a.residue == "green": s = (g > r + 35) & (g > b + 35)
    else: s = (p.min(1) > 225)
    return int(s.sum())

step = max(1, int(round(fps * a.every)))
times = [float(t) for t in a.times.split(",") if t] or list(np.linspace(0.5, io["duration"] - 0.5, 8))
cmp_idx = {min(N - 1, int(t * fps)) for t in times}
std_o, std_n, d_in, d_ring, outerr, res_o, res_n, black, tiles, cmp = [], [], [], [], [], [], [], [], [], {}
prev = None
for k, (fo, fn) in enumerate(zip(iter_frames(a.orig), iter_frames(a.out))):
    m = union if per is None else (per[k] | (static if static is not None else False))
    if m.any():
        e = nd.binary_dilation(m, iterations=4) if per is not None else eff_u
        if fn[e].mean() < 12 and fo[e].mean() > 30: black.append(k)
        res_o.append(residue(fo, m)); res_n.append(residue(fn, m))
    fnf = fn.astype(np.float32)
    if prev is not None:
        df = np.abs(fnf - prev).mean(2); d_in.append(df[eff_u].mean()); d_ring.append(df[ring_u].mean())
    prev = fnf
    if static is not None and k % step == 0:
        std_o.append(fo[cy0:cy1, cx0:cx1].astype(np.float32)); std_n.append(fnf[cy0:cy1, cx0:cx1])
    if k % 15 == 0: outerr.append(np.abs(fo.astype(np.float32) - fnf)[outside].mean())
    if k % step == 0: tiles.append(label(cv2.resize(fn[cy0:cy1, cx0:cx1], None, fx=0.6, fy=0.6), f"f{k} {k/fps:.1f}s"))
    if k in cmp_idx: cmp[k] = (fo[cy0:cy1, cx0:cx1].copy(), fn[cy0:cy1, cx0:cx1].copy())

if static is not None:
    so = np.stack(std_o).std(0).mean(2); sn = np.stack(std_n).std(0).mean(2)
    core_c = static[cy0:cy1, cx0:cx1]; ring_c = ring_u[cy0:cy1, cx0:cx1]
    print(f"[残影] 蒙版区时间方差 原片 {so[core_c].mean():.1f} -> 成片 {sn[core_c].mean():.1f} | 外圈背景 {sn[ring_c].mean():.1f}  (成片≈外圈 = 无残影)")
d_in, d_ring = np.array(d_in), np.array(d_ring); ratio = (d_in + 1) / (d_ring + 1)
bad = [int(i + 1) for i in np.where((ratio > 3) & (d_in > 6))[0]]
print(f"[闪烁] 帧间变化 修补区 {d_in.mean():.2f} / 外圈 {d_ring.mean():.2f}  比值中位 {np.median(ratio):.2f}  突跳帧 {len(bad)} 个 {bad[:20]}")
if a.bounds:
    B = json.load(open(a.bounds))["bounds"][1:-1]
    worst = sorted((((d_in[c - 1] + 1) / (d_ring[c - 1] + 1), c) for c in B if 0 < c <= len(d_in)), reverse=True)[:5]
    print("[接缝] 段边界处 修补区跳变/外圈跳变 最大5个:", [(c, round(float(v), 2)) for v, c in worst],
          "(≈1 或更小 = 修补区跟着画面一起变、无接缝；>2 且该处不是镜头切换要去联系图看)")
print(f"[区外] ROI 以外平均像素差 {np.mean(outerr):.2f} (只有重编码误差应 <2)")
if a.residue != "none":
    print(f"[残留色:{a.residue}] 蒙版内像素数 原片中位 {int(np.median(res_o))} -> 成片中位 {int(np.median(res_n))} 最大 {max(res_n)} @帧{int(np.argmax(res_n))}"
          + ("  (white 在白墙/白楼顶背景下会误报，只作参考)" if a.residue == "white" else ""))
print(f"[全黑] 蒙版区输出全黑的帧: {len(black)} 个 {black[:10]}")
cols = 6; page = 48
for p in range(0, len(tiles), page):
    out = os.path.join(a.out_dir, f"sheet_{p//page+1:02d}.png"); cv2.imwrite(out, contact_sheet(tiles[p:p + page], cols))
print(f"逐 {a.every}s 联系图 {(len(tiles)-1)//page+1} 页: {a.out_dir}/sheet_XX.png  <- 必须逐页肉眼看(色块/鳞片纹理/残字)")
rows = [np.hstack([label(o.copy(), f"before {k/fps:.1f}s"), np.full((o.shape[0], 6, 3), 255, np.uint8), label(n.copy(), "after")])
        for k, (o, n) in sorted(cmp.items())]
out = os.path.join(a.out_dir, "before_after.png"); cv2.imwrite(out, contact_sheet(rows, 2)); print("前后对比:", out)
