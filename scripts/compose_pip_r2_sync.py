#!/usr/bin/env python3
"""R2 circular PiP: host duration drives final length; base is speed-synced (no freeze pad).

Audio:
  - Always maps host narration (volume 1.0).
  - Optional music path (4th/5th arg or TVP_DH_MUSIC / MUSIC_PATH env): mix narration@1.0 + music@0.40.
  - If no music: narration-only (legacy) but prints a warning — final DH deliverables should restack BGM.
"""
import os
import subprocess
import sys
import json
import time
from pathlib import Path

# Defaults match gemini4_carbon-style mid card @1080 → ×2 for 4K
SCALE = 2
CARD = (64 * SCALE, 500 * SCALE, 1016 * SCALE, 960 * SCALE)
DIAM = 140 * SCALE
MARGIN = 28 * SCALE
RING = 5 * SCALE
NARRATION_VOL = 1.0
MUSIC_VOL = 0.40


def probe_dur(p: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(p),
    ], text=True).strip())


def resolve_music(argv: list[str]) -> Path | None:
    """Accept music as optional trailing path among args 3.., or env TVP_DH_MUSIC / MUSIC_PATH.

    Usage forms:
      compose_pip_r2_sync.py <base> <host> [out_dir] [stamp] [music]
      compose_pip_r2_sync.py <base> <host> [out_dir] [music]
      compose_pip_r2_sync.py <base> <host> [music]
    A path that exists as a media/audio file wins over stamp/out_dir heuristics.
    """
    env = os.environ.get("TVP_DH_MUSIC") or os.environ.get("MUSIC_PATH")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    # Prefer explicit trailing args that look like audio/video files
    for a in argv[3:]:
        p = Path(a)
        if p.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mov"} and p.is_file():
            candidates.append(p)
        elif p.is_file() and p.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
            candidates.append(p)
    for c in reversed(candidates):
        if c.is_file():
            return c
    return None


def parse_out_dir_stamp(argv: list[str], host: Path, music: Path | None) -> tuple[Path, str]:
    """out_dir = first non-music directory-like arg after host; stamp = non-path token or time."""
    extras = []
    for a in argv[3:]:
        p = Path(a)
        if music is not None and p.resolve() == music.resolve():
            continue
        extras.append(a)
    out_dir = host.parent
    stamp = time.strftime("%Y%m%d-%H%M")
    if extras:
        p0 = Path(extras[0])
        # treat as out_dir if it exists as dir, or has no media suffix / looks like a path
        if p0.is_dir() or extras[0].endswith(("/", "\\")) or ("/" in extras[0] or "\\" in extras[0]):
            out_dir = p0
            if len(extras) > 1:
                # second may be stamp unless it is a media file (already filtered)
                if Path(extras[1]).suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4"}:
                    stamp = extras[1]
        else:
            # first extra is stamp
            stamp = extras[0]
    return out_dir, stamp


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "usage: compose_pip_r2_sync.py <base_4k.mp4> <host_merged.mp4> "
            "[out_dir] [stamp] [music.wav]\n"
            "       music may also be set via TVP_DH_MUSIC or MUSIC_PATH",
            file=sys.stderr,
        )
        sys.exit(2)
    base = Path(sys.argv[1])
    host = Path(sys.argv[2])
    music = resolve_music(sys.argv)
    out_dir, stamp = parse_out_dir_stamp(sys.argv, host, music)
    out_dir.mkdir(parents=True, exist_ok=True)

    cx = CARD[2] - MARGIN - (DIAM + 2 * RING) // 2
    cy = CARD[3] - MARGIN - (DIAM + 2 * RING) // 2
    ox, oy = cx - DIAM // 2, cy - DIAM // 2
    glow = DIAM + 2 * RING
    gx, gy = cx - glow // 2, cy - glow // 2
    r = glow / 2

    base_d, host_d = probe_dur(base), probe_dur(host)
    final_d = host_d
    speed = base_d / final_d
    print(json.dumps({
        "base_d": base_d, "host_d": host_d, "final_d": final_d, "speed": speed,
        "cx": cx, "cy": cy, "diam": DIAM, "margin": MARGIN,
        "music": str(music) if music else None,
        "narration_vol": NARRATION_VOL,
        "music_vol": MUSIC_VOL if music else None,
    }, ensure_ascii=False))

    if music is None:
        print(
            "WARNING: no BGM provided. Narration-only mix kept for compatibility, "
            "but final DH deliverables MUST restack tech-broadcast-fit BGM at ~0.40 "
            "with narration at 1.0 (pass music path or set TVP_DH_MUSIC).",
            file=sys.stderr,
        )

    work = out_dir / "_host_pip_prep_sync.mp4"
    subprocess.check_call([
        "ffmpeg", "-y", "-i", str(host),
        "-vf", f"scale={DIAM}:{DIAM}:force_original_aspect_ratio=increase,crop={DIAM}:{DIAM},fps=30,format=yuv420p",
        "-an", "-t", f"{final_d:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(work),
    ])

    # Inputs: 0=base video, 1=host circle prep, 2=host (narration audio)
    # Optional 3=music
    if music is None:
        fc = (
            f"[0:v]setpts=PTS/{speed:.6f},fps=30,format=yuv420p,trim=duration={final_d:.3f},setpts=PTS-STARTPTS[base];"
            f"color=c=white@0.5:s={glow}x{glow}:d={final_d:.3f}:r=30,format=rgba,"
            f"geq=r='255':g='255':b='255':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow({r-1},2)),"
            f"if(gte(pow(X-W/2,2)+pow(Y-H/2,2),pow({DIAM/2},2)),128,0),0)'[ring];"
            f"[1:v]format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow({DIAM/2-2},2)),255,0)'[hostc];"
            f"[base][ring]overlay={gx}:{gy}:format=auto[bg];"
            f"[bg][hostc]overlay={ox}:{oy}:format=auto[vout];"
            f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={NARRATION_VOL},atrim=0:{final_d:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", str(base), "-i", str(work), "-i", str(host),
            "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{final_d:.3f}", "-movflags", "+faststart",
        ]
    else:
        fc = (
            f"[0:v]setpts=PTS/{speed:.6f},fps=30,format=yuv420p,trim=duration={final_d:.3f},setpts=PTS-STARTPTS[base];"
            f"color=c=white@0.5:s={glow}x{glow}:d={final_d:.3f}:r=30,format=rgba,"
            f"geq=r='255':g='255':b='255':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow({r-1},2)),"
            f"if(gte(pow(X-W/2,2)+pow(Y-H/2,2),pow({DIAM/2},2)),128,0),0)'[ring];"
            f"[1:v]format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow({DIAM/2-2},2)),255,0)'[hostc];"
            f"[base][ring]overlay={gx}:{gy}:format=auto[bg];"
            f"[bg][hostc]overlay={ox}:{oy}:format=auto[vout];"
            f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={NARRATION_VOL},atrim=0:{final_d:.3f},asetpts=PTS-STARTPTS[narr];"
            f"[3:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={MUSIC_VOL},atrim=0:{final_d:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={max(0.0, final_d-1.5):.3f}:d=1.5[mus];"
            f"[narr][mus]amix=inputs=2:duration=first:dropout_transition=0,"
            f"aformat=sample_rates=48000:channel_layouts=stereo[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", str(base), "-i", str(work), "-i", str(host),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{final_d:.3f}", "-movflags", "+faststart",
        ]

    out4k = out_dir / f"口播-圆PiP-R2-画面同步-{stamp}.mp4"
    out1080 = out_dir / f"口播-圆PiP-R2-画面同步-{stamp}-1080.mp4"
    subprocess.check_call(cmd + [str(out4k)])
    subprocess.check_call([
        "ffmpeg", "-y", "-i", str(out4k), "-vf", "scale=1080:1920",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out1080),
    ])
    print(json.dumps({"out4k": str(out4k), "out1080": str(out1080), "music": str(music) if music else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
