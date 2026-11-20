"""手眼预览通过同一帧跑双检测器，并分别绘制两种结果。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import hand_eye_preview as demo
from test_gaze_blink import eye_landmarks
from test_offline_workflows import FrameSource, simulate_window


def test_video_preview_draws_hands_and_eyes_together_and_independently(tmp_path, monkeypatch, capsys):
    video = tmp_path / "sample.mp4"
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    source = FrameSource([frame] * 3)
    eyes = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.3)])
    no_face = SimpleNamespace(face_landmarks=[])
    hand = [SimpleNamespace(x=0.65 + n % 5 * 0.035, y=0.65 + n // 5 * 0.035) for n in range(21)]
    hands = SimpleNamespace(hand_landmarks=[hand], handedness=[[SimpleNamespace(category_name="Right")]])
    no_hands = SimpleNamespace(hand_landmarks=[], handedness=[])
    face_detector = SimpleNamespace(detect_for_video=Mock(side_effect=[eyes, no_face, eyes]))
    hand_detector = SimpleNamespace(detect_for_video=Mock(side_effect=[hands, hands, no_hands]))
    create_detectors = Mock(return_value=(face_detector, hand_detector))
    open_video = Mock(return_value=(source, 10.0))
    open_camera = Mock(side_effect=AssertionError("录像模式不应打开摄像头"))
    monkeypatch.setattr(demo, "open_video", open_video)
    monkeypatch.setattr(demo.landmarks_preview, "create_detectors", create_detectors)
    monkeypatch.setattr(demo.landmarks_preview, "open_camera", open_camera)
    show, close = simulate_window(monkeypatch, [-1] * 3)

    demo.main(video)

    open_video.assert_called_once_with(video)
    open_camera.assert_not_called()
    create_detectors.assert_called_once()
    close.assert_called_once()
    assert source.released
    assert "录像播放结束" in capsys.readouterr().out

    face_inputs = face_detector.detect_for_video.call_args_list
    hand_inputs = hand_detector.detect_for_video.call_args_list
    assert [call.args[1] for call in face_inputs] == [0, 100, 200]
    assert [call.args[1] for call in hand_inputs] == [0, 100, 200]
    assert all(face.args[0] is hand.args[0] for face, hand in zip(face_inputs, hand_inputs))

    displayed = [call.args[1][demo.PANEL_HEIGHT:] for call in show.call_args_list]
    has_eyes = [np.any(np.all(pixels == (0, 255, 255), axis=-1)) for pixels in displayed]
    has_hands = [np.any(np.all(pixels == (0, 0, 255), axis=-1)) for pixels in displayed]
    assert has_eyes == [True, False, True]
    assert has_hands == [True, True, False]
