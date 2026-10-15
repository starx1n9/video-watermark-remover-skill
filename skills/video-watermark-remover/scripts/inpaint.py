# 第5+6步 修补+合成：裁 ROI -> 按分段逐段 ProPainter(并行/静默/查黑) -> 羽化 alpha 贴回原片
# 用法(静态 logo):  python inpaint.py --video IN.mp4 --mask DIR/mask.npy --bounds DIR/bounds.json --workdir W --out OUT.mp4
# 用法(逐帧字幕):  python inpaint.py --video IN.mp4 --masks DIR/masks.npz --bounds DIR/bounds.json --workdir W --out OUT.mp4
# 可选: --grow-from 178:14 (从第178帧起蒙版再外扩14px，盖缩放/模糊转场里被拉散的 logo，可多次)
#       --mask-dilation 2 (ProPainter 内部再外扩；半透明带光晕的 logo 用 4)  --workers 2  --roi x0,y0,x1,y1
# 同一视频既要去 logo 又要去字幕：分两次跑，第二次的 --video 用第一次的输出(两块 ROI 不要合并成一个大框)
# 中断后原命令重跑：已完成的段会跳过
import argparse, os, sys, json, glob, shutil, time, subprocess, numpy as np, cv2, scipy.ndimage as nd
from concurrent.futures import ThreadPoolExecutor
from vdw_common import (check_env, probe, has_audio, iter_frames, load_masks, auto_roi, feather, run_propainter,
                        FF, NOWIN, MIN_ROI)
check_env(True)

def rect(s): return tuple(int(v) for v in s.split(","))
ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True); ap.add_argument("--out", required=True); ap.add_argument("--workdir", required=True)
ap.add_argument("--mask"); ap.add_argument("--masks"); ap.add_argument("--bounds")
ap.add_argument("--grow-from", action="append", default=[]); ap.add_argument("--mask-dilation", type=int, default=2)
ap.add_argument("--workers", type=int, default=2); ap.add_argument("--roi", type=rect)
ap.add_argument("--crf", type=int, default=17); ap.add_argument("--fp32", action="store_true")
a = ap.parse_args()
if os.path.abspath(a.out) == os.path.abspath(a.video): sys.exit("禁止覆盖输入视频，换个 --out")
if not (a.mask or a.masks): sys.exit("需要 --mask 或 --masks")
t0 = time.time()
def log(s): print(f"[{time.time()-t0:5.0f}s] {s}", flush=True)
info = probe(a.video); N, W, H, fps = info["frames"], info["width"], info["height"], info["fps"]

# ---- 蒙版(全帧坐标) ----
static = np.load(a.mask).astype(bool) if a.mask else None
per = load_masks(a.masks, H, W) if a.masks else None
if per is not None and len(per) != N: sys.exit(f"逐帧蒙版 {len(per)} 帧 != 视频 {N} 帧")
grows = sorted((int(f), int(it)) for f, it in (g.split(":") for g in a.grow_from))
def grow_iter(k):
    it = 0
    for f, i in grows:
        if k >= f: it = i
    return it
def mask_at(k):
    m = static.copy() if static is not None else np.zeros((H, W), bool)
    if per is not None: m |= per[k]
    it = grow_iter(k)
    return nd.binary_dilation(m, iterations=it) if it else m
dynamic = per is not None or bool(grows)
union = (static.copy() if static is not None else np.zeros((H, W), bool))
if per is not None: union |= per.union()
for f, it in grows: union |= nd.binary_dilation(union, iterations=it)
if not union.any(): sys.exit("蒙版为空")
RX0, RY0, RX1, RY1 = a.roi or auto_roi(union, W, H, margin=24 + a.mask_dilation)
if RY1 - RY0 < MIN_ROI or RX1 - RX0 < MIN_ROI: log(f"⚠ ROI {RX1-RX0}x{RY1-RY0} 小于 {MIN_ROI}，ProPainter 可能输出全黑")
log(f"视频 {W}x{H} {N}帧 {fps:.2f}fps | ROI ({RX0},{RY0})-({RX1},{RY1}) {RX1-RX0}x{RY1-RY0} | 蒙版{'逐帧' if dynamic else '静态'}")

# ---- 分段 ----
B = json.load(open(a.bounds))["bounds"] if a.bounds else [0, N]
if B[-1] != N: sys.exit(f"bounds 末尾 {B[-1]} != 帧数 {N}，分段文件不是这个视频的")
if not a.bounds: log("⚠ 没给 --bounds：整片当一段。片内有转场/硬切时会出色块，先跑 shots.py")
os.makedirs(a.workdir, exist_ok=True)
def sd(i): return f"{a.workdir}/in/s{i:04d}"
def md(i): return f"{a.workdir}/mask/s{i:04d}"
def od(i): return f"{a.workdir}/pp/s{i:04d}/frames"
def done(i): return len(glob.glob(od(i) + "/*.png")) == B[i + 1] - B[i]
seg = 0
need_write = not all(done(i) for i in range(len(B) - 1))
if need_write:
    for k, f in enumerate(iter_frames(a.video, (RX0, RY0, RX1, RY1))):
        while k >= B[seg + 1]: seg += 1
        if done(seg): continue
        os.makedirs(sd(seg), exist_ok=True); cv2.imwrite(f"{sd(seg)}/{k-B[seg]:05d}.png", f)
        if dynamic:
            os.makedirs(md(seg), exist_ok=True)
            cv2.imwrite(f"{md(seg)}/{k-B[seg]:05d}.png", mask_at(k)[RY0:RY1, RX0:RX1].astype(np.uint8) * 255)
    if not dynamic:
        cv2.imwrite(f"{a.workdir}/mask_roi.png", static[RY0:RY1, RX0:RX1].astype(np.uint8) * 255)
    log(f"ROI 帧落盘完成，{len(B)-1} 段")

# ---- 逐段 ProPainter ----
cnt = [0]
def work(i):
    n = B[i + 1] - B[i]
    if done(i): cnt[0] += 1; return True
    mpath = md(i) if dynamic else f"{a.workdir}/mask_roi.png"
    empty = (dynamic and all(cv2.imread(p, 0).max() == 0 for p in glob.glob(mpath + "/*.png")))
    if empty:                                             # 整段无蒙版：原样拷贝
        os.makedirs(od(i), exist_ok=True)
        for j in range(n): shutil.copyfile(f"{sd(i)}/{j:05d}.png", f"{od(i)}/{j:04d}.png")
    else:
        r = run_propainter(sd(i), mpath, f"{a.workdir}/pp", a.mask_dilation, fp16=not a.fp32, fps=fps)
        if not done(i): log(f"[段{i}] 失败 rc={r.returncode}\n{(r.stderr or '')[-1200:]}"); return False
        # 查黑：蒙版区输出接近全黑而输入不黑 -> ProPainter 失效(典型原因 ROI 太小)
        j = n // 2; src = cv2.imread(f"{sd(i)}/{j:05d}.png"); out = cv2.imread(f"{od(i)}/{j:04d}.png")
        mk = (cv2.imread(f"{md(i)}/{j:05d}.png", 0) if dynamic else cv2.imread(mpath, 0)) > 0
        if mk.any() and out[mk].mean() < 12 and src[mk].mean() > 30:
            log(f"[段{i}] 蒙版区输出全黑！检查 ROI 尺寸(需>= {MIN_ROI})"); return False
    cnt[0] += 1
    if cnt[0] % 10 == 0 or cnt[0] == len(B) - 1: log(f"进度 {cnt[0]}/{len(B)-1}")
    return True
with ThreadPoolExecutor(a.workers) as ex: res = list(ex.map(work, range(len(B) - 1)))
if not all(res): log("有段失败，修正后原命令重跑(已完成段跳过)"); sys.exit(1)

# ---- 收集 + alpha ----
ro = f"{a.workdir}/roi_out"; al = f"{a.workdir}/alpha"; os.makedirs(ro, exist_ok=True); os.makedirs(al, exist_ok=True)
k = 0
for i in range(len(B) - 1):
    for j in range(B[i + 1] - B[i]):
        shutil.copyfile(f"{od(i)}/{j:04d}.png", f"{ro}/{k:05d}.png")
        if dynamic: cv2.imwrite(f"{al}/{k:05d}.png", feather(mask_at(k)[RY0:RY1, RX0:RX1], a.mask_dilation + 2))
        k += 1
if not dynamic: cv2.imwrite(f"{al}/static.png", feather(static[RY0:RY1, RX0:RX1], a.mask_dilation + 2))
log(f"收集 {k} 帧")

# ---- 合成 ----
alpha_in = (["-framerate", f"{fps}", "-i", f"{al}/%05d.png"] if dynamic
            else ["-loop", "1", "-framerate", f"{fps}", "-i", f"{al}/static.png"])
fc = (f"[0:v]setpts=PTS-STARTPTS[base];[1:v]format=rgba,setpts=PTS-STARTPTS[roi];"
      f"[2:v]format=gray,setpts=PTS-STARTPTS[a];[roi][a]alphamerge[ov];"
      f"[base][ov]overlay={RX0}:{RY0}:shortest=1:eof_action=pass,format=yuv420p[v]")
cmd = [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", a.video, "-framerate", f"{fps}", "-i", f"{ro}/%05d.png",
       *alpha_in, "-filter_complex", fc, "-map", "[v]"]
if has_audio(a.video): cmd += ["-map", "0:a", "-c:a", "copy"]
cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow", a.out]
r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN)
if r.returncode: log(r.stderr[-1500:]); sys.exit(1)
o = probe(a.out)
log(f"完成 -> {a.out}  {o['frames']}帧 {o['duration']:.3f}s" + ("" if o["frames"] == N else f"  ⚠ 帧数与输入 {N} 不一致"))
json.dump(dict(roi=[RX0, RY0, RX1, RY1], bounds=len(B) - 1, mask_dilation=a.mask_dilation, grows=grows),
          open(f"{a.workdir}/run_info.json", "w"))
print("INPAINT-DONE", flush=True)
