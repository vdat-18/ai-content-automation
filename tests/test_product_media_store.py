from pathlib import Path

import pytest

from ai_content.domains.marketing.products.media_store import KEY_PREFIX, MediaStore


class _Remote:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, source: Path, content_type: str) -> None:
        self.objects[key] = source.read_bytes()

    def get(self, key: str, target: Path) -> bool:
        if key not in self.objects:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.objects[key])
        return True

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


async def test_without_a_remote_it_is_just_the_local_folder(tmp_path) -> None:
    store = MediaStore(tmp_path)
    await store.write("keyframes/p/shot_0.jpg", b"img")
    assert (tmp_path / "keyframes/p/shot_0.jpg").read_bytes() == b"img"
    assert await store.read("keyframes/p/shot_0.jpg") == b"img"
    assert await store.fetch("keyframes/p/missing.jpg") is None
    assert not await store.exists("keyframes/p/missing.jpg")


async def test_writes_go_to_the_remote_and_a_lost_local_file_comes_back(tmp_path) -> None:
    remote = _Remote()
    store = MediaStore(tmp_path, remote)
    await store.write("clips/p/shot_0.mp4", b"video")
    assert remote.objects[KEY_PREFIX + "clips/p/shot_0.mp4"] == b"video"

    (tmp_path / "clips/p/shot_0.mp4").unlink()
    assert await store.exists("clips/p/shot_0.mp4")
    restored = await store.fetch("clips/p/shot_0.mp4")
    assert restored is not None and restored.read_bytes() == b"video"


async def test_push_uploads_a_file_made_by_ffmpeg_and_remove_deletes_both_copies(tmp_path) -> None:
    remote = _Remote()
    store = MediaStore(tmp_path, remote)
    target = store.path("videos/p/video.mp4")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"final")
    await store.push("videos/p/video.mp4")
    assert remote.objects[KEY_PREFIX + "videos/p/video.mp4"] == b"final"

    await store.remove("videos/p/video.mp4")
    assert not target.exists() and not remote.objects
    assert await store.fetch_first(["videos/p/voiceover.mp3", "videos/p/video.mp4"]) is None


def test_paths_cannot_leave_the_media_folder(tmp_path) -> None:
    store = MediaStore(tmp_path)
    for bad in ("../x", "/etc/passwd", "a/../../x", ""):
        with pytest.raises(ValueError):
            store.path(bad)


async def test_remove_tree_deletes_a_folder_in_both_places(tmp_path) -> None:
    remote = _Remote()
    remote.delete_prefix = lambda prefix: [  # type: ignore[attr-defined]
        remote.objects.pop(key) for key in list(remote.objects) if key.startswith(prefix)
    ]
    store = MediaStore(tmp_path, remote)
    await store.write("clips/p/shot_0.mp4", b"a")
    await store.write("clips/p/shot_1.mp4", b"b")
    await store.write("clips/other/shot_0.mp4", b"c")

    await store.remove_tree("clips/p")
    assert not (tmp_path / "clips" / "p").exists()
    assert list(remote.objects) == [KEY_PREFIX + "clips/other/shot_0.mp4"]
