# AGENTS.md

本仓库是一个"视频去 logo / 去字幕"的 Agent Skill，外加一组命令行脚本。给 Codex 等 AI 助手看的说明如下。

## 用户让你去掉视频里的 logo、角标、水印、字幕时
1. **先完整阅读 [`skills/video-watermark-remover/SKILL.md`](skills/video-watermark-remover/SKILL.md)**，严格按其中的 8 步流程和硬规则执行。
2. 所有脚本都要在 `skills/video-watermark-remover/` 目录下运行，用法是 `python scripts/xxx.py`。
3. 如果 `skills/video-watermark-remover/config.json` 不存在，说明环境还没装好。先按下面的"首次安装"做，自检 PASS 后再干活。
4. **修补开始前，必须把蒙版预览图和识别清单给用户确认。** 不覆盖原视频，不删除用户的文件。
5. 修补耗时较长（每分钟视频大约 5–10 分钟）。放后台运行，定时查看输出、汇报进度。

## 首次安装（在用户机器上）
```bash
cd skills/video-watermark-remover
# 建议先建独立环境：conda create -n vdw python=3.10 -y && conda activate vdw
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
#   ↑ 报错或输出 False：让用户按显卡装 CUDA 版 PyTorch，例如
#     pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -r ../../requirements.txt
python scripts/setup_env.py     # 检查 ffmpeg，clone 固定版本的 ProPainter，写 config.json；按 ✗ 提示处理后重跑
python scripts/selftest.py      # 必须输出 PASS
```
- 缺 ffmpeg 时：Windows 用 `winget install Gyan.FFmpeg`，装完要重开终端。
- ProPainter 的模型权重第一次运行时会自动下载，约 200MB，需要能访问 GitHub Releases。
- `selftest.py` 输出 FAIL 时，把输出贴给用户，并定位是哪一步出的问题，**不要跳过自检直接处理用户的视频**。

## 开发约定
- 脚本之间共享的逻辑放在 `scripts/vdw_common.py`。配置优先级：环境变量 `VDW_PYTHON` / `VDW_PROPAINTER` / `VDW_FFMPEG`，然后是 `config.json`，最后是默认值。
- 改动后跑一遍 `python scripts/selftest.py`，确认仍然 PASS。
- 不要把 ProPainter 的代码或权重提交进本仓库（许可证不同，已在 `.gitignore` 里忽略）。
