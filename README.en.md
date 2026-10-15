# video-watermark-remover-skill

<p align="center"><a href="README.md">简体中文</a> | <b>English</b></p>

<p align="center"><b>Video watermark remover · logo remover · hardsub (burned-in subtitle) remover</b><br>Runs locally · works as an agent skill for Claude Code / Codex</p>

A local toolkit for **removing logos, corner bugs, station marks and burned-in subtitles from videos**. It uses [ProPainter](https://github.com/sczhou/ProPainter) for video inpainting and is packaged as an **Agent Skill** that AI coding assistants such as Claude Code and Codex can follow step by step. Ask *"remove the logo in the top-left corner of this video"* and the assistant will:

1. Locate the element and the time ranges where it appears.
2. Generate a mask preview and **wait for your confirmation**.
3. Inpaint shot by shot. Shots are split at hard cuts and dissolves, and only a small region around the element is changed. All other pixels stay untouched.
4. Run quality checks: numeric metrics plus per-second contact sheets.
5. Deliver the clean video, before/after images, and a coordinates document for placing a new logo or new subtitles.

The scripts also work on their own from the command line, without an AI assistant.

## Showcase

**① Corporate promo: large centered logo.** Aerial camera motion; the logo is a semi-transparent ray icon with the brand name in Chinese and English.

![Centered logo removal: aerial outro](docs/showcase/corporate_center_logo.gif)

**② Corporate promo: top-left corner bug and burned-in subtitles.** Both were removed across the whole 126 s video (160 shot segments) to make room for new English subtitles.

![Corner logo + subtitle removal](docs/showcase/corporate_corner_logo_and_subtitles.gif)

**③ AI-generated video (Veo / Gemini): sparkle watermark in the bottom-right corner**

![Veo/Gemini sparkle removal](docs/showcase/veo_gemini_watermark.gif)

<details>
<summary>Full-size still comparisons (click to expand)</summary>

![Centered logo](docs/showcase/corporate_center_logo.jpg)
![Corner logo + subtitles](docs/showcase/corporate_corner_logo_and_subtitles.jpg)
![Veo/Gemini sparkle, zoomed below](docs/showcase/veo_gemini_watermark.jpg)
![Self-test: synthetic video](docs/images/selftest_before_after.jpg)
</details>

<sub>The corporate promo footage in ① and ② is used with the copyright holder's permission, for demonstration only. Please do not reuse it. ③ removes only the **visible** sparkle. The invisible SynthID watermark that Google embeds in Veo videos is not affected.</sub>

## What it can and cannot do
- ✅ Fixed-position logos, corner bugs and station marks. This includes semi-transparent ones, ones that fade in or out, and ones smeared by zoom or blur transitions in openings and outros.
- ✅ Fixed-position, horizontally centered, single-line burned-in subtitles. Light or dark text, with or without a shadow.
- ⚠️ Moving or scaling logos, scrolling subtitles and multi-line subtitles are not tracked automatically. They need manually specified time ranges, and results are weaker.
- ⚠️ Text that is part of the scene, such as signs or on-screen UI, gets smeared too if it overlaps the element being removed.

## Installation

**Requirements**: an NVIDIA GPU (≥4 GB free VRAM recommended; CPU-only works but is very slow), Python 3.8+, git, and ffmpeg.

```bash
git clone https://github.com/starx1n9/video-watermark-remover-skill.git
cd video-watermark-remover-skill/skills/video-watermark-remover

# 1) Create an isolated environment (conda shown; venv works too)
conda create -n vdw python=3.10 -y
conda activate vdw

# 2) Install CUDA-enabled PyTorch for your GPU (see https://pytorch.org/get-started/locally/)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 3) Install the rest: clones a pinned ProPainter and writes config.json
pip install -r ../../requirements.txt
python scripts/setup_env.py

# 4) Self-test: builds a synthetic video with known ground truth, runs the full pipeline, prints PASS / FAIL (~2 min)
python scripts/selftest.py
```

To install ffmpeg:

| OS | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Ubuntu | `sudo apt install ffmpeg` |

The model weights (about 200 MB) download automatically on the first run.

## Using it with an AI assistant

**Claude Code**: link the skill folder into your skills directory.

```bash
# macOS / Linux
ln -s "$(pwd)/skills/video-watermark-remover" ~/.claude/skills/video-watermark-remover
# Windows (admin PowerShell, or with Developer Mode enabled)
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\video-watermark-remover" -Target "$PWD\skills\video-watermark-remover"
```

Then ask something like *"remove the logo in the top-left of this video"*, or run `/video-watermark-remover`.

**Codex and other assistants**: start the assistant in the repository root. It reads [`AGENTS.md`](AGENTS.md), which walks it through installation and the self-test before the workflow. If your assistant supports Agent Skills (the `SKILL.md` format), you can also place `skills/video-watermark-remover` in its skills directory.

**What you provide**: the video file and one sentence saying what to remove. Positions and time ranges are found automatically, and **you get a mask preview to confirm before any inpainting starts**.

## Command line without an AI assistant
The full 8-step workflow and every parameter are documented in [`skills/video-watermark-remover/SKILL.md`](skills/video-watermark-remover/SKILL.md). The shortest path for a top-left logo:

```bash
cd skills/video-watermark-remover
python scripts/locate_static.py --video in.mp4 --out-dir work                 # find static pixels; inspect work/static_rel.png
python scripts/mask_logo.py --rel work/static_rel.npy --box 0,0,200,90 --thresh 0.6 --preview in.mp4@100 --out-dir work
python scripts/shots.py in.mp4 --out work/bounds.json                          # split at hard cuts and dissolves
python scripts/inpaint.py --video in.mp4 --mask work/mask.npy --bounds work/bounds.json --workdir work/run --out in-nologo.mp4
python scripts/qc.py --orig in.mp4 --out in-nologo.mp4 --mask work/mask.npy --bounds work/bounds.json --workdir work/run --out-dir qc
```

For subtitles, replace steps 1 and 2 with `mask_subtitle.py`, and pass `--masks work/masks.npz` when inpainting.

## Why this beats "draw a box and erase it" (pitfalls we actually hit)
| Pitfall | Symptom | What this tool does |
|---|---|---|
| Dissolves not split | Pill-shaped blobs in the colours of a neighbouring shot appear in static shots | Detects both hard cuts and dissolves, and cuts at both ends of each transition |
| Thin elements masked as a solid block | A fish-scale texture is hallucinated | Masks text and rays stroke by stroke, so the real background between strokes stays available as a reference |
| ROI too flat | ProPainter outputs pure black | The ROI is always at least 160 px in both width and height |
| Subtitle mask changes every frame | Flicker, and missed strokes during fade-in | One mask per subtitle line for its whole duration, extended ±3 frames |
| Trusting numbers alone | All metrics pass while blobs are still visible | QC always produces per-second contact sheets for human review |

## License and usage notice
- The code in this repository is released under the **MIT** license. See [LICENSE](LICENSE).
- **ProPainter is not included in this repository.** `setup_env.py` downloads it from the official repository. ProPainter uses the **S-Lab License 1.0, which permits non-commercial use only**. Commercial use requires permission from its authors. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Only process footage you have the rights to. Removing watermarks or copyright notices from other people's work may violate copyright law or platform terms.
