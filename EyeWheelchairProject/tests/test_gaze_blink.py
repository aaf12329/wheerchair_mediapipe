"""用确定的虹膜位置和开合比验证方向确认状态。"""

import pytest

import gaze_blink_confirm_demo as demo
import gaze_direction_preview as preview


@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setattr(demo, "gaze_score", lambda frame: frame[0])
    monkeypatch.setattr(demo, "average_ear", lambda frame: frame[1])
    detector = demo.GazeBlinkDetector(0.0)
    frame_number = 0

    def feed_frames(frame, count):
        nonlocal frame_number
        for _ in range(count):
            status = detector.update(frame_number / 30, frame)
            frame_number += 1
        return status

    assert feed_frames((0.5, 0.30), 100).state == "选择方向"
    return feed_frames


def test_steadily_looking_center_after_calibration_selects_forward(feed):
    status = feed((0.5, 0.30), 30)
    assert (status.state, status.active) == ("等待眨眼", "前进")


def test_looking_away_cancels_old_direction_before_blink(feed):
    status = feed((0.2, 0.30), 35)
    assert (status.state, status.active) == ("等待眨眼", "左转")

    status = feed((0.8, 0.30), 6)
    assert (status.state, status.active) == ("选择方向", None)
    feed((0.8, 0.0), 5)
    status = feed((0.8, 0.30), 5)
    assert (status.state, status.active) == ("选择方向", None)


def test_face_loss_discards_old_dwell_and_unfinished_blink(feed):
    assert feed((0.2, 0.30), 35).state == "等待眨眼"
    feed((0.2, 0.0), 4)
    status = feed(None, 1)
    assert (status.state, status.active) == ("选择方向", None)

    status = feed((0.2, 0.30), 5)
    assert (status.state, status.active) == ("选择方向", None)
    status = feed((0.2, 0.30), 25)
    assert (status.state, status.active) == ("等待眨眼", "左转")


def test_gaze_preview_can_select_center_without_first_looking_sideways(monkeypatch):
    monkeypatch.setattr(preview, "gaze_score", lambda frame: frame)
    detector = preview.GazeDirectionDetector(0.0)
    for index in range(130):
        status = detector.update(index / 30, 0.5)
    assert (status.raw_direction, status.candidate) == ("中", "中")
