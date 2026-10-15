# 第8步(可选) 拼接多段成完整版：每段音频按该段视频帧数精确裁齐，保证总帧数 = 各段之和
# 用法: python concat.py A.mp4 B.mp4 C.mp4 --out FULL.mp4 [--crf 17]
import argparse, subprocess, sys
from vdw_common import check_env, probe, has_audio, FF, NOWIN
check_env(False)

ap = argparse.ArgumentParser()
ap.add_argument("inputs", nargs="+"); ap.add_argument("--out", required=True); ap.add_argument("--crf", type=int, default=17)
a = ap.parse_args()
infos = [probe(p) for p in a.inputs]
sizes = {(i["width"], i["height"]) for i in infos}; rates = {round(i["fps"], 3) for i in infos}
if len(sizes) > 1 or len(rates) > 1: sys.exit(f"各段分辨率/帧率不一致: {sizes} {rates}，先统一")
audio = all(has_audio(p) for p in a.inputs)
cmd = [FF, "-hide_banner", "-loglevel", "error", "-y"]
for p in a.inputs: cmd += ["-i", p]
fc = []; cat = ""
for k, i in enumerate(infos):
    fc.append(f"[{k}:v]setpts=PTS-STARTPTS[v{k}]"); cat += f"[v{k}]"
    if audio:
        fc.append(f"[{k}:a]atrim=duration={i['frames']/i['fps']:.6f},asetpts=PTS-STARTPTS[a{k}]"); cat += f"[a{k}]"
fc.append(f"{cat}concat=n={len(infos)}:v=1:a={1 if audio else 0}[v]" + ("[a]" if audio else ""))
cmd += ["-filter_complex", ";".join(fc), "-map", "[v]"] + (["-map", "[a]", "-c:a", "aac", "-b:a", "192k"] if audio else [])
cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", a.out]
r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN)
if r.returncode: sys.exit(r.stderr[-1500:])
o = probe(a.out); exp = sum(i["frames"] for i in infos)
t = 0.0
for p, i in zip(a.inputs, infos):
    print(f"  {t:8.3f}s  帧{int(round(t*i['fps'])):6d}  {p}  ({i['frames']}帧)"); t += i["frames"] / i["fps"]
print(f"完成 -> {a.out}  {o['frames']}帧 {o['duration']:.3f}s" + ("  ✓ 帧数吻合" if o["frames"] == exp else f"  ⚠ 应为 {exp} 帧"))
