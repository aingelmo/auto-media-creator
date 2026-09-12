"""Scene-cut detection over a proxy, per #4.2."""

from __future__ import annotations


def detect_scene_cuts(proxy_path: str) -> list[float]:
    """Detect scene cuts with PySceneDetect's `ContentDetector`, per #4.2.

    Args:
        proxy_path: Path to the proxy video to scan.

    Returns:
        Timestamps (seconds) of each detected scene cut (i.e. the start
        time of every scene after the first), using PySceneDetect's default
        detection threshold [validate].
    """
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(proxy_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video)
    scenes = manager.get_scene_list()
    return [start.get_seconds() for start, _ in scenes[1:]]
