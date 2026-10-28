import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from ai_content.domains.marketing.creative.adapters.managed_media import _extract_frame


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_next_scene_starts_from_the_frame_at_the_cut_point(tmp_path: Path) -> None:
    clip = tmp_path / "scene.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x112:d=1"]
        + ["-f", "lavfi", "-i", "color=c=blue:s=64x112:d=1", "-filter_complex"]
        + ["[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    early = Image.open(BytesIO(_extract_frame(clip, 0.5))).convert("RGB").getpixel((32, 56))
    late = Image.open(BytesIO(_extract_frame(clip, 1.5))).convert("RGB").getpixel((32, 56))
    past_end = Image.open(BytesIO(_extract_frame(clip, 9))).convert("RGB").getpixel((32, 56))
    assert early[0] > 200 and early[2] < 60
    assert late[2] > 200 and late[0] < 60
    assert past_end[2] > 200
