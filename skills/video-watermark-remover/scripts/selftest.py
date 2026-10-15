# 端到端自检：合成一段"已知干净真值"的测试视频(平移纹理 + 中途淡入淡出转场 + 半透明假 logo + 假字幕)，
# 按 SKILL.md 的流程跑完 定位->蒙版->分段->修补(logo)->字幕蒙版->修补(字幕)->质检，再和真值比对给出 PASS/FAIL。
# 用法: python scripts/selftest.py [--work DIR] [--docs DIR(把对比图拷过去，给 README 用)]
import argparse, os, sys, subprocess, shutil, json, time, numpy as np, cv2, scipy.ndimage as nd
from vdw_common import check_env, FF, NOWIN, load_masks, bbox
check_env(True)

ap = argparse.ArgumentParser()
ap.add_argument("--work", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "selftest_out"))
ap.add_argument("--docs"); ap.add_argument("--keep", action="store_true", help="已存在测试视频时复用")
a = ap.parse_args(); W_ = a.work; os.makedirs(W_, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__)); t0 = time.time()
W, H, FPS, N, DIS = 640, 360, 30, 180, (90, 105)          # 画面 / 帧数 / 转场区间
rng = np.random.default_rng(7)

def texture(seed, w=1700, h=900):
    r = np.random.default_rng(seed); img = np.zeros((h, w, 3), np.uint8)
    img[:] = r.integers(60, 200, 3)
    for _ in range(260):
        c = tuple(int(v) for v in r.integers(0, 256, 3)); x, y = int(r.integers(0, w)), int(r.integers(0, h))
        if r.random() < 0.5: cv2.rectangle(img, (x, y), (x + int(r.integers(20, 160)), y + int(r.integers(20, 120))), c, -1)
        else: cv2.circle(img, (x, y), int(r.integers(10, 70)), c, -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    return np.clip(img.astype(np.int16) + r.integers(-8, 9, img.shape), 0, 255).astype(np.uint8)

def write(path, frames):
    p = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", path],
                         stdin=subprocess.PIPE, creationflags=NOWIN)
    for f in frames: p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()

def run(script, *args):
    print(f"\n$ {script} {' '.join(str(x) for x in args)}", flush=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *map(str, args)], cwd=HERE)
    if r.returncode: sys.exit(f"✗ {script} 失败 (rc={r.returncode})")

inp, gtp = os.path.join(W_, "input.mp4"), os.path.join(W_, "groundtruth.mp4")
SUBS = [(0, 60, "Hello, this is a test video"), (60, 120, "Second subtitle line here"), (120, N, "The end")]
# ---- 1) 合成测试视频 ----
logo_a = np.zeros((H, W), np.float32); logo_c = np.zeros((H, W, 3), np.float32)
for i in range(0, 60, 6): cv2.line(logo_a, (24 + i, 18), (24, 18 + i), 0.8, 2)        # 放射状条纹图标
logo_c[logo_a > 0] = (255, 255, 255)
txt = np.zeros((H, W), np.uint8); cv2.putText(txt, "DEMO", (92, 56), cv2.FONT_HERSHEY_DUPLEX, 1.2, 255, 3)
logo_c[txt > 0] = (230, 90, 50); logo_a[txt > 0] = 0.85                               # 蓝色品牌字
sm = np.zeros((H, W), np.uint8); cv2.putText(sm, "OPTO TEST CO.", (94, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 255, 1)
logo_c[sm > 0] = (230, 90, 50); logo_a[sm > 0] = 0.8                                  # 细小英文行
truth_logo = logo_a > 0
truth_sub = np.zeros((N, H, W), bool)
if not (a.keep and os.path.exists(inp) and os.path.exists(gtp)):
    ta, tb = texture(1), texture(2); gt, ip = [], []
    for k in range(N):
        fa = ta[int(1.5 * k):int(1.5 * k) + H, 3 * k:3 * k + W]; fb = tb[int(1.2 * k):int(1.2 * k) + H, int(2.5 * k):int(2.5 * k) + W]
        if k < DIS[0]: g = fa
        elif k >= DIS[1]: g = fb
        else: t = (k - DIS[0]) / (DIS[1] - DIS[0]); g = cv2.addWeighted(fa, 1 - t, fb, t, 0)
        g = g.copy(); gt.append(g)
        f = (g * (1 - logo_a[..., None]) + logo_c * logo_a[..., None]).astype(np.uint8)
        s = next(x[2] for x in SUBS if x[0] <= k < x[1])
        (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2); x0 = (W - tw) // 2
        cv2.putText(f, s, (x0 + 2, 332), cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(f, s, (x0, 330), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        ip.append(f)
    write(gtp, gt); write(inp, ip)
for k in range(N):                                         # 字幕真值(重画一遍取像素)
    s = next(x[2] for x in SUBS if x[0] <= k < x[1]); m = np.zeros((H, W), np.uint8)
    (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_DUPLEX, 0.8, 2); x0 = (W - tw) // 2
    cv2.putText(m, s, (x0 + 2, 332), cv2.FONT_HERSHEY_DUPLEX, 0.8, 255, 2, cv2.LINE_AA)
    cv2.putText(m, s, (x0, 330), cv2.FONT_HERSHEY_DUPLEX, 0.8, 255, 2, cv2.LINE_AA)
    truth_sub[k] = m > 0
print(f"测试视频: {inp}  ({W}x{H} {N}帧，含第{DIS[0]}-{DIS[1]}帧淡入淡出转场)")

# ---- 2) 按流程跑 ----
run("probe.py", inp, "--out-dir", W_)
run("locate_static.py", "--video", f"{inp}@0:{N}", "--out-dir", W_)
run("mask_logo.py", "--rel", f"{W_}/static_rel.npy", "--box", "10,5,260,90", "--thresh", "0.6",
    "--preview", f"{inp}@45", "--out-dir", W_)
run("shots.py", inp, "--out", f"{W_}/bounds.json")
out1, out2 = f"{W_}/out_nologo.mp4", f"{W_}/out_nologo_nosub.mp4"
run("inpaint.py", "--video", inp, "--mask", f"{W_}/mask.npy", "--bounds", f"{W_}/bounds.json", "--workdir", f"{W_}/run_logo", "--out", out1)
run("mask_subtitle.py", out1, "--out-dir", W_, "--shadow", "2,2", "--preview-times", "1,3,5")
run("inpaint.py", "--video", out1, "--masks", f"{W_}/masks.npz", "--bounds", f"{W_}/bounds.json", "--workdir", f"{W_}/run_sub", "--out", out2)
run("qc.py", "--orig", inp, "--out", out2, "--mask", f"{W_}/mask.npy", "--masks", f"{W_}/masks.npz", "--bounds", f"{W_}/bounds.json",
    "--times", "1,2.5,3.2,4,5.5", "--out-dir", f"{W_}/qc")

# ---- 3) 与真值比对 ----
def frames(p):
    c = cv2.VideoCapture(p); out = []
    while True:
        ok, f = c.read()
        if not ok: break
        out.append(f.astype(np.float32))
    return out
G, I, O = frames(gtp), frames(inp), frames(out2)
res = {"frames_ok": len(O) == N}
RL = nd.binary_dilation(truth_logo, iterations=2)
eL_in = np.mean([np.abs(I[k] - G[k]).mean(2)[RL].mean() for k in range(N)])
eL_out = np.mean([np.abs(O[k] - G[k]).mean(2)[RL].mean() for k in range(N)])
eS_in = np.mean([np.abs(I[k] - G[k]).mean(2)[nd.binary_dilation(truth_sub[k], iterations=2)].mean() for k in range(N)])
eS_out = np.mean([np.abs(O[k] - G[k]).mean(2)[nd.binary_dilation(truth_sub[k], iterations=2)].mean() for k in range(N)])
far = ~nd.binary_dilation(truth_logo | truth_sub.any(0), iterations=40)
e_far = np.mean([np.abs(O[k] - I[k]).mean(2)[far].mean() for k in range(0, N, 10)])
M = np.load(f"{W_}/mask.npy"); cover = (M & truth_logo).sum() / truth_logo.sum()
print("\n================ 自检结果 ================")
print(f"logo 区与真值误差: 修补前 {eL_in:.1f} -> 修补后 {eL_out:.1f}   (蒙版覆盖真值 logo {cover:.0%})")
print(f"字幕区与真值误差: 修补前 {eS_in:.1f} -> 修补后 {eS_out:.1f}")
print(f"远离修补区的像素变化: {e_far:.2f} (只应有重编码误差)")
checks = [("帧数一致", res["frames_ok"]), ("logo 蒙版覆盖 >= 90%", cover >= 0.9),
          ("logo 误差降到修补前 35% 以下", eL_out < 0.35 * eL_in), ("字幕误差降到修补前 35% 以下", eS_out < 0.35 * eS_in),
          ("远处像素未被改动(<2)", e_far < 2)]
for n_, ok in checks: print(("  ✓ " if ok else "  ✗ ") + n_)
allok = all(ok for _, ok in checks)
print(f"\n{'PASS' if allok else 'FAIL'}  用时 {time.time()-t0:.0f}s   成片: {out2}   质检图: {W_}/qc/")
if a.docs:
    os.makedirs(a.docs, exist_ok=True)
    for src, dst in [(f"{W_}/qc/before_after.png", "selftest_before_after.png"), (f"{W_}/mask_preview.png", "selftest_mask_preview.png"),
                     (f"{W_}/subtitle_mask_preview.png", "selftest_subtitle_mask.png")]:
        if os.path.exists(src): shutil.copyfile(src, os.path.join(a.docs, dst))
sys.exit(0 if allok else 1)
