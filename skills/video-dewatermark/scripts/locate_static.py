# 第2步 定位：逐像素时间标准差(背景在动、logo 不动 -> logo 处方差低)
# 多段素材含同一 logo 时传多个视频：取各段归一化方差的最大值 = "每段都不动"才算 logo，背景偶然静止块被排除
# 用法: python locate_static.py --video A.mp4[@起帧:止帧] [--video B.mp4@30:148 ...] --out-dir DIR [--max-frames 300]
#   起止帧用来避开淡入/黑场/转场，只取 logo 稳定显示的区间
import argparse, os, numpy as np, cv2
from vdw_common import check_env, probe, iter_frames, bbox
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("--video", action="append", required=True); ap.add_argument("--out-dir", required=True)
ap.add_argument("--max-frames", type=int, default=300)
a = ap.parse_args(); os.makedirs(a.out_dir, exist_ok=True)
rel_all = None
for spec in a.video:
    path, _, rng = spec.partition("@")
    info = probe(path); s, e = (0, info["frames"]) if not rng else map(int, rng.split(":"))
    step = max(1, (e - s) // a.max_frames)
    acc = [];
    for k, f in enumerate(iter_frames(path)):
        if s <= k < e and (k - s) % step == 0: acc.append(f.astype(np.float32))
    std = np.stack(acc).std(0).mean(2); med = float(np.median(std))
    rel = std / max(med, 1e-6)
    print(f"{os.path.basename(path)} 帧{s}-{e} 取{len(acc)}帧  背景方差中位数 {med:.1f}")
    rel_all = rel if rel_all is None else np.maximum(rel_all, rel)
np.save(os.path.join(a.out_dir, "static_rel.npy"), rel_all)
cv2.imwrite(os.path.join(a.out_dir, "static_rel.png"), np.clip(rel_all * 128, 0, 255).astype(np.uint8))
print("相对方差图(越黑越静止):", os.path.join(a.out_dir, "static_rel.png"))
for T in (0.3, 0.5, 0.7):
    m = (rel_all < T).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    comps = sorted([(st[k, 4], k) for k in range(1, n) if st[k, 4] >= 30], reverse=True)[:6]
    desc = "; ".join(f"面积{ar} 框({st[k,0]},{st[k,1]})-({st[k,0]+st[k,2]-1},{st[k,1]+st[k,3]-1})" for ar, k in comps)
    print(f"阈值 rel<{T}: 共 {int(m.sum())} 像素  最大连通块: {desc}")
print("提示: 半透明 logo 方差下降不多，阈值要放宽(0.6~0.75)；实心 logo 0.3~0.5。去 static_rel.png 看 logo 轮廓再定 --box/--thresh")
