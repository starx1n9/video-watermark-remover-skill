# 第1步 探测：视频基本信息 + 均匀抽 N 帧拼图(看 logo/字幕在哪、是否淡入、有无转场)
# 用法: python probe.py VIDEO [VIDEO ...] --out-dir DIR [--n 12]
import argparse, os, numpy as np, cv2
from vdw_common import check_env, probe, has_audio, grab, contact_sheet, label
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("videos", nargs="+"); ap.add_argument("--out-dir", required=True); ap.add_argument("--n", type=int, default=12)
a = ap.parse_args(); os.makedirs(a.out_dir, exist_ok=True)
for v in a.videos:
    info = probe(v); info["audio"] = has_audio(v)
    print(f"{v}\n  {info['width']}x{info['height']} {info['fps']:.3f}fps {info['frames']}帧 {info['duration']:.3f}s 音频={info['audio']}")
    idx = np.linspace(0, info["frames"] - 1, a.n).astype(int).tolist()
    fr = grab(v, idx)
    tiles = [label(cv2.resize(fr[k], None, fx=0.4, fy=0.4), f"f{k} {k/info['fps']:.1f}s") for k in idx if k in fr]
    out = os.path.join(a.out_dir, os.path.splitext(os.path.basename(v))[0] + "_probe.png")
    cv2.imwrite(out, contact_sheet(tiles, 4)); print("  抽帧图:", out)
