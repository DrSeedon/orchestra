#!/usr/bin/env python3
"""Build the silent README preview from V-686's finished dashboard tour."""
import subprocess
import sys
from pathlib import Path


source = Path(sys.argv[1])
output = Path(sys.argv[2])
temp = Path(sys.argv[3])
temp.mkdir(parents=True, exist_ok=True)

segments = [
    (9.5, 12.3, "You describe the job"),
    (13.0, 15.8, "The orchestrator splits the work"),
    (17.4, 20.2, "Workers start in parallel"),
    (27.0, 29.8, "Follow work and status"),
    (32.0, 34.8, "The worker reports DONE"),
    (37.5, 40.3, "The orchestrator reviews and tests"),
    (42.2, 45.0, "Approved work is merged"),
    (47.2, 49.8, "Tasks stay visible"),
    (49.7, 52.5, "Track model quotas"),
    (59.0, 61.8, "See spend by day and agent"),
]
fps = 10
width = 1100
caption_height = 130
caption_top = 43
font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

filters = []
for i, (start, end, caption) in enumerate(segments):
    filters.append(
        f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,fps={fps},"
        f"scale={width}:-2:flags=lanczos,setsar=1,"
        f"drawbox=x=0:y=ih-{caption_height}:w=iw:h={caption_height}:color=black@1:t=fill,"
        f"drawtext=fontfile={font}:text='{caption}':fontcolor=white:fontsize=34:"
        f"x=(w-text_w)/2:y=h-{caption_height}+{caption_top}:borderw=1:bordercolor=black@0.7[v{i}]"
    )

labels = "".join(f"[v{i}]" for i in range(len(segments)))
filters.append(f"{labels}concat=n={len(segments)}:v=1:a=0,settb=expr=1/{fps}[montage]")

# Fade back to the exact opening frame so the GIF's final image and first image match.
opening = segments[0][0]
filters.append(
    f"[0:v]trim=start={opening}:end={opening + 0.04},setpts=PTS-STARTPTS,fps={fps},"
    f"scale={width}:-2:flags=lanczos,setsar=1,"
    f"drawbox=x=0:y=ih-{caption_height}:w=iw:h={caption_height}:color=black@1:t=fill,"
    f"drawtext=fontfile={font}:text='{segments[0][2]}':fontcolor=white:fontsize=34:"
    f"x=(w-text_w)/2:y=h-{caption_height}+{caption_top}:borderw=1:bordercolor=black@0.7,"
    f"tpad=stop_mode=clone:stop_duration=1.0,settb=expr=1/{fps}[opening]"
)
main_duration = sum(end - start for start, end, _ in segments)
filters.append(
    f"[montage][opening]xfade=transition=fade:duration=0.7:offset={main_duration - 0.7},"
    "format=yuv420p[loop]"
)

preview = temp / "dashboard-live-preview.mp4"
subprocess.run([
    "ffmpeg", "-v", "error", "-y", "-i", str(source), "-filter_complex", ";".join(filters),
    "-map", "[loop]", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
    "-pix_fmt", "yuv420p", str(preview),
], check=True)

palette = temp / "palette.png"
subprocess.run([
    "ffmpeg", "-v", "error", "-y", "-i", str(preview),
    "-vf", "palettegen=max_colors=256:stats_mode=full", str(palette),
], check=True)
subprocess.run([
    "ffmpeg", "-v", "error", "-y", "-i", str(preview), "-i", str(palette),
    "-lavfi", "[0:v][1:v]paletteuse=dither=sierra2_4a", "-loop", "0", str(output),
], check=True)
print(f"GIF written: {output} ({output.stat().st_size} bytes)")
