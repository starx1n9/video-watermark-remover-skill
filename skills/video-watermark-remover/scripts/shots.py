# 第4步 分段：硬切 + 淡入淡出转场(两端都切开，转场帧单独成段)
# 为什么：ProPainter 会沿光流跨镜头借像素，转场不切开 -> 静止镜头里冒出邻镜头颜色的"药丸色块"(实测，扩蒙版/fp32 都不治)
# 用法: python shots.py VIDEO --out DIR/bounds.json [--min-len 6] [--extra 178,300]
import argparse, json, numpy as np, cv2
from vdw_common import check_env, iter_frames
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("--out", required=True)
ap.add_argument("--min-len", type=int, default=6); ap.add_argument("--extra", default="", help="额外强制切点(帧号,逗号分隔)")
ap.add_argument("--gap", type=int, default=8, help="转场检测跨度 K：比较 i-K 与 i+K")
a = ap.parse_args()
G, Hs, H2 = [], [], []
for f in iter_frames(a.video):
    s = cv2.resize(f, (96, 54), interpolation=cv2.INTER_AREA); hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    G.append(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32))
    Hs.append(cv2.normalize(cv2.calcHist([hsv], [0, 1, 2], None, [12, 6, 6], [0, 180, 0, 256, 0, 256]), None).flatten())
    H2.append(cv2.normalize(cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256]), None).flatten())
N = len(G); K = a.gap
d = np.zeros(N); h1 = np.zeros(N); L = np.zeros(N)
for i in range(1, N):
    d[i] = np.abs(G[i] - G[i - 1]).mean(); h1[i] = cv2.compareHist(H2[i - 1], H2[i], cv2.HISTCMP_BHATTACHARYYA)
for i in range(K, N - K):
    L[i] = cv2.compareHist(Hs[i - K], Hs[i + K], cv2.HISTCMP_BHATTACHARYYA)
hard = []
for i in range(1, N):                                   # 硬切：单帧差分尖峰，或相邻直方图突变
    nb = np.r_[d[max(1, i - 8):i], d[i + 1:min(N, i + 9)]]
    if (d[i] > 3 * (np.median(nb) + 1) and d[i] > 12) or h1[i] > 0.35: hard.append(i)
diss = [i for i in range(K, N - K) if L[i] >= L[max(0, i - K):i + K + 1].max() and L[i] > 0.3]
extra = [int(x) for x in a.extra.split(",") if x.strip()]
hs = set(hard) | set(extra) | {0, N}
cand = sorted(hs | {e - K for e in diss} | {e + K for e in diss})
cand = [c for c in cand if 0 <= c <= N]
B = [0]
for b in cand[1:]:
    if b - B[-1] >= a.min_len: B.append(b)
    elif b in hs and B[-1] not in hs and B[-1] != 0: B[-1] = b   # 太近时优先保留硬切点
if B[-1] != N:
    if N - B[-1] < a.min_len: B[-1] = N
    else: B.append(N)
json.dump({"frames": N, "bounds": B, "hard_cuts": hard, "dissolve_peaks": diss, "extra": extra}, open(a.out, "w"))
lens = np.diff(B)
print(f"{N} 帧 -> {len(B)-1} 段 (硬切 {len(hard)} 处, 转场峰 {len(diss)} 处)  段长 最短{lens.min()} 中位{int(np.median(lens))} 最长{lens.max()}")
print("写入:", a.out)
