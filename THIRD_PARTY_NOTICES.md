# Third-party notices

## ProPainter (NOT included in this repository)

- Project: https://github.com/sczhou/ProPainter
- Pinned commit used by `setup_env.py`: `e870e79321c31b733e2031af5aa2fb1fe3ac7eec`
- License: **S-Lab License 1.0**. Redistribution and use are permitted **for non-commercial purposes only**. For commercial use, contact the authors. Contact details are listed in ProPainter's own LICENSE file.

`setup_env.py` downloads ProPainter from its official repository into `skills/video-watermark-remover/third_party/` on the user's machine. ProPainter downloads its own model weights at first run. Neither the ProPainter source code nor its weights are distributed with this repository. Your use of ProPainter is governed by its license, not by this repository's MIT license.

ProPainter in turn includes RAFT, which is licensed under the BSD 3-Clause License.

## Python packages

OpenCV (Apache-2.0), NumPy (BSD-3-Clause) and SciPy (BSD-3-Clause) are installed from PyPI via `requirements.txt`.

## ffmpeg

ffmpeg is installed separately by the user and invoked as an external program. It is licensed under LGPL/GPL, depending on the build.
