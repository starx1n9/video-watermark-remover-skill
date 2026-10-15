# 一键环境检查/安装：ffmpeg、PyTorch(CUDA)、ProPainter(固定版本) -> 写 config.json
# 在"准备用来跑的 Python 环境"里执行(建议新建 conda/venv，先装好 CUDA 版 PyTorch):
#   python scripts/setup_env.py                       # 自动 clone ProPainter 到 <skill>/third_party/ProPainter
#   python scripts/setup_env.py --propainter D:/ProPainter   # 用已有的 ProPainter
#   python scripts/setup_env.py --skip-pip            # 不自动 pip 安装 ProPainter 依赖
import argparse, json, os, shutil, subprocess, sys

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

PROPAINTER_REPO = "https://github.com/sczhou/ProPainter.git"
PROPAINTER_COMMIT = "e870e79321c31b733e2031af5aa2fb1fe3ac7eec"      # 2025-02-19，本项目验证过的版本
# ProPainter 的依赖(去掉 torch/torchvision，避免把已装的 CUDA 版覆盖成 CPU 版)
PP_DEPS = ["av", "addict", "einops", "future", "numpy", "scipy", "opencv-python", "matplotlib",
           "scikit-image", "imageio-ffmpeg", "pyyaml", "requests", "timm", "yapf"]
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument("--propainter", help="已有 ProPainter 目录"); ap.add_argument("--skip-pip", action="store_true")
a = ap.parse_args()
ok = True
def step(msg): print(f"\n== {msg}")

step("Python"); print(sys.executable, sys.version.split()[0])
if sys.version_info < (3, 8): print("✗ 需要 Python >= 3.8"); ok = False

step("ffmpeg / ffprobe")
ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
if ff and fp: print("✓", ff); print("✓", fp)
else:
    ok = False
    print("✗ 没找到 ffmpeg/ffprobe。安装后重开终端：\n"
          "  Windows: winget install Gyan.FFmpeg   macOS: brew install ffmpeg   Ubuntu: sudo apt install ffmpeg")

step("PyTorch")
try:
    import torch
    cuda = torch.cuda.is_available()
    print(f"✓ torch {torch.__version__}  CUDA可用={cuda}" + (f"  GPU={torch.cuda.get_device_name(0)}" if cuda else ""))
    if cuda:
        free, total = torch.cuda.mem_get_info(); print(f"  显存 空闲 {free/2**30:.1f}G / 总 {total/2**30:.1f}G (建议空闲 >= 4G)")
    else: print("⚠ 没有 CUDA：能跑但会非常慢。NVIDIA 显卡请装 CUDA 版：https://pytorch.org/get-started/locally/")
except ImportError:
    ok = False
    print("✗ 没装 PyTorch。NVIDIA 显卡示例(CUDA 12.1)：\n"
          "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121\n"
          "  其他配置见 https://pytorch.org/get-started/locally/ ，装好后重跑本脚本")

step("ProPainter")
pp = os.path.abspath(a.propainter) if a.propainter else os.path.join(SKILL_DIR, "third_party", "ProPainter")
if not os.path.exists(os.path.join(pp, "inference_propainter.py")):
    if a.propainter: print(f"✗ {pp} 里没有 inference_propainter.py"); ok = False
    elif not shutil.which("git"): print("✗ 需要 git 来 clone ProPainter(或手动下载后用 --propainter 指定)"); ok = False
    else:
        os.makedirs(os.path.dirname(pp), exist_ok=True)
        print("clone", PROPAINTER_REPO, "->", pp)
        r = subprocess.run(["git", "clone", PROPAINTER_REPO, pp])
        if r.returncode == 0: subprocess.run(["git", "-C", pp, "checkout", "-q", PROPAINTER_COMMIT])
        else: ok = False
if os.path.exists(os.path.join(pp, "inference_propainter.py")):
    print("✓", pp)
    print("  ⚠ ProPainter 采用 S-Lab License 1.0：仅限非商业用途，商用需联系原作者授权(见其 LICENSE)")
    if not a.skip_pip:
        print("pip 安装 ProPainter 依赖(不含 torch) ...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PP_DEPS])
        if r.returncode: print("✗ pip 安装失败，可手动: pip install " + " ".join(PP_DEPS)); ok = False
    print("  模型权重首次运行时会自动下载到", os.path.join(pp, "weights"), "(约 200MB)")

step("写配置")
cfg = {"python": sys.executable, "propainter": pp, "ffmpeg": ff or "ffmpeg", "ffprobe": fp or "ffprobe"}
json.dump(cfg, open(os.path.join(SKILL_DIR, "config.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("✓", os.path.join(SKILL_DIR, "config.json"))
print("\n" + ("全部就绪。下一步运行自检: python scripts/selftest.py" if ok else "有未完成项(✗)，按提示处理后重跑本脚本"))
sys.exit(0 if ok else 1)
