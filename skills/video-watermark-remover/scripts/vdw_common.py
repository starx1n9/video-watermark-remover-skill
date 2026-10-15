# video-watermark-remover 公共库：路径配置 / 读帧 / 蒙版存取 / ProPainter 调用 / 羽化 alpha
import os, sys, shutil, subprocess, json, numpy as np, cv2, scipy.ndimage as nd

for _s in (sys.stdout, sys.stderr):                    # Windows 控制台默认 GBK，统一 utf-8 输出
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

# 配置优先级：环境变量 > <skill>/config.json(setup_env.py 生成) > 默认(当前解释器 / <skill>/third_party/ProPainter)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg_path = os.path.join(SKILL_DIR, "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}
PY = os.environ.get("VDW_PYTHON") or _cfg.get("python") or sys.executable
PP_DIR = os.environ.get("VDW_PROPAINTER") or _cfg.get("propainter") or os.path.join(SKILL_DIR, "third_party", "ProPainter")
FF = os.environ.get("VDW_FFMPEG") or _cfg.get("ffmpeg") or shutil.which("ffmpeg") or "ffmpeg"
FP = os.environ.get("VDW_FFPROBE") or _cfg.get("ffprobe") or shutil.which("ffprobe") or "ffprobe"


def check_env(need_propainter=True):
    """缺依赖时给出明确提示后退出"""
    miss = []
    for name, exe in (("ffmpeg", FF), ("ffprobe", FP)):
        if not (os.path.exists(exe) or shutil.which(exe)): miss.append(f"找不到 {name}：装好并放进 PATH，或在 config.json 里写路径")
    if need_propainter and not os.path.exists(os.path.join(PP_DIR, "inference_propainter.py")):
        miss.append(f"找不到 ProPainter({PP_DIR})：先运行 python scripts/setup_env.py")
    if miss: sys.exit("环境未就绪:\n  " + "\n  ".join(miss))
NOWIN = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW：子进程不弹黑框
MIN_ROI = 160                                          # 实测 ROI 高 96 时 ProPainter 蒙版区输出全黑，>=160 正常


def probe(video):
    r = subprocess.run([FP, "-v", "error", "-count_frames", "-select_streams", "v",
                        "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames",
                        "-show_entries", "format=duration", "-of", "json", video],
                       capture_output=True, text=True, creationflags=NOWIN)
    j = json.loads(r.stdout); s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return dict(width=int(s["width"]), height=int(s["height"]), fps=float(num) / float(den),
                frames=int(s["nb_read_frames"]), duration=float(j["format"]["duration"]))


def has_audio(video):
    r = subprocess.run([FP, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", video], capture_output=True, text=True, creationflags=NOWIN)
    return bool(r.stdout.strip())


def iter_frames(video, crop=None):
    """逐帧生成 BGR；crop=(x0,y0,x1,y1) 右下开区间"""
    cap = cv2.VideoCapture(video)
    while True:
        ok, f = cap.read()
        if not ok: break
        yield f if crop is None else f[crop[1]:crop[3], crop[0]:crop[2]]
    cap.release()


def grab(video, idxs):
    """取指定帧号(顺序读，帧精确)"""
    want = set(idxs); out = {}
    for k, f in enumerate(iter_frames(video)):
        if k in want: out[k] = f
        if len(out) == len(want): break
    return out


# ---------- 蒙版 ----------
# 静态蒙版：.npy (H,W) bool
# 逐帧蒙版：.npz {bits: packbits(N,h,W), shape:(N,h,W), y0:int}，只存一条横带(y0..y0+h)，全帧坐标还原
def save_masks(path, masks, y0):
    m = np.asarray(masks, bool)
    np.savez_compressed(path, bits=np.packbits(m, axis=-1), shape=np.array(m.shape), y0=np.array(y0))


def load_masks(path, H, W):
    z = np.load(path); N, h, w = z["shape"]; y0 = int(z["y0"])
    band = np.unpackbits(z["bits"], axis=-1)[..., :w].astype(bool)
    class Full:
        def __len__(s): return int(N)
        def __getitem__(s, i):
            full = np.zeros((H, W), bool); full[y0:y0 + h, :w] = band[i]; return full
        def union(s):
            full = np.zeros((H, W), bool); full[y0:y0 + h, :w] = band.any(0); return full
    return Full()


def bbox(m):
    ys, xs = np.where(m)
    return None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def auto_roi(union_mask, W, H, margin=24):
    """蒙版并集外扩 margin，对齐 8，宽高都 >= MIN_ROI，夹在画面内"""
    x0, y0, x1, y1 = bbox(union_mask)
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + 1 + margin, y1 + 1 + margin
    def fit(a, b, lim):
        a = max(0, a // 8 * 8); b = min(lim, -(-b // 8) * 8)
        while b - a < MIN_ROI:                      # 不够高/宽就两头扩
            if a > 0: a = max(0, a - 8)
            if b - a < MIN_ROI and b < lim: b = min(lim, b + 8)
            if a == 0 and b == lim: break
        return a, b
    x0, x1 = fit(x0, x1, W); y0, y1 = fit(y0, y1, H)
    return x0, y0, x1, y1


def feather(mask, grow, sigma=1.2):
    a = nd.binary_dilation(mask, iterations=grow).astype(np.float32) if grow > 0 else mask.astype(np.float32)
    return (np.clip(cv2.GaussianBlur(a, (0, 0), sigma), 0, 1) * 255).astype(np.uint8)


def run_propainter(in_dir, mask, out_root, mask_dilation=4, fp16=True, fps=30):
    """mask：单张 png 路径或逐帧 png 目录。输出 out_root/<basename(in_dir)>/frames/0000.png"""
    cmd = [PY, "inference_propainter.py", "-i", in_dir, "-m", mask, "-o", out_root,
           "--mask_dilation", str(mask_dilation), "--save_frames", "--save_fps", str(int(round(fps)))]
    if fp16: cmd.append("--fp16")
    return subprocess.run(cmd, cwd=PP_DIR, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NOWIN)


def contact_sheet(tiles, cols, gap=4):
    h, w = tiles[0].shape[:2]
    while len(tiles) % cols: tiles.append(np.zeros((h, w, 3), np.uint8))
    rows = []
    for i in range(0, len(tiles), cols):
        row = []
        for t in tiles[i:i + cols]:
            row += [t, np.full((h, gap, 3), 255, np.uint8)]
        rows += [np.hstack(row), np.full((gap, (w + gap) * cols, 3), 255, np.uint8)]
    return np.vstack(rows)


def label(img, text, color=(0, 0, 255)):
    cv2.putText(img, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
    cv2.putText(img, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return img
