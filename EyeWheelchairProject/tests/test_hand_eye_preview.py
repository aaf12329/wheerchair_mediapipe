"""验证手眼预览的同帧检测、渲染和假串口输出。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import hand_eye_preview as demo
from test_gaze_blink import eye_landmarks
from test_offline_workflows import FrameSource, simulate_window
from test_serial_link import FakeSerial, make_link, movement_letters


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
    make_link_for_mode = Mock(wraps=demo.WheelchairLink)
    monkeypatch.setattr(demo, "open_video", open_video)
    monkeypatch.setattr(demo.landmarks_preview, "create_detectors", create_detectors)
    monkeypatch.setattr(demo.landmarks_preview, "open_camera", open_camera)
    monkeypatch.setattr(demo, "WheelchairLink", make_link_for_mode)
    show, close = simulate_window(monkeypatch, [-1] * 3)

    demo.main(video)

    open_video.assert_called_once_with(video)
    open_camera.assert_not_called()
    make_link_for_mode.assert_called_once_with(None, firmware=None)
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


def test_video_cannot_open_serial_port(tmp_path, monkeypatch):
    transport = Mock()
    monkeypatch.setattr(demo, "WheelchairLink", transport)
    with pytest.raises(ValueError, match="不能同时指定串口"):
        demo.main(tmp_path / "sample.mp4", serial_port="COM9")
    transport.assert_not_called()


def test_live_preview_sends_confirmed_direction_and_processes_stop_key(monkeypatch, capsys):
    eyes_open = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.3)])
    eyes_closed = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.0)])
    before_blink = [eyes_open] * 130
    landmarks = before_blink + [eyes_closed] * 5 + [eyes_open] * 10
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    capture = FrameSource([frame] * len(landmarks))
    read_frame = capture.read
    frame_number = 0

    def read_at_recorded_rate():
        nonlocal frame_number
        frame_number += 1
        return read_frame()

    clock = SimpleNamespace(perf_counter=lambda: frame_number / 30)
    face_detector = SimpleNamespace(detect_for_video=Mock(side_effect=landmarks))
    hand_detector = SimpleNamespace(detect_for_video=Mock(return_value=SimpleNamespace(hand_landmarks=[])))
    port = FakeSerial()
    link = demo.WheelchairLink("COM9", firmware="wheelchair", port_factory=lambda *args, **kwargs: port)
    open_transport = Mock(return_value=link)
    displayed = Mock(return_value=frame)
    monkeypatch.setattr(capture, "read", read_at_recorded_rate)
    monkeypatch.setattr(demo, "time", clock)
    monkeypatch.setattr(demo.landmarks_preview, "time", clock)
    monkeypatch.setattr(demo.landmarks_preview, "open_camera", lambda: capture)
    monkeypatch.setattr(demo.landmarks_preview, "create_detectors", lambda: (face_detector, hand_detector))
    monkeypatch.setattr(demo, "WheelchairLink", open_transport)
    monkeypatch.setattr(demo, "render_preview", displayed)
    # S 和 Q 都应在上一次按键不到 0.25 秒时响应。
    simulate_window(monkeypatch, [-1] * (len(landmarks) - 3) + [ord("X"), ord("S"), ord("Q")])

    demo.main(serial_port="COM9", firmware="wheelchair")

    open_transport.assert_called_once_with("COM9", firmware="wheelchair")
    assert displayed.call_args_list[len(before_blink) - 1].args[4].state == "等待眨眼"
    confirmed = displayed.call_args_list[-2].args[4]
    assert (confirmed.state, confirmed.active) == ("确认成功", "前进")
    assert displayed.call_args.args[4].state == "校准"
    assert displayed.call_args.args[5].intent == "S"
    commands = movement_letters(port)
    first_movement = commands.index("F")
    assert commands[0] == "S"
    assert all(command == "S" for command in commands[:first_movement])
    assert commands[first_movement:] == ["F", "S"]
    assert "[串口 COM9] 已发送 F" in capsys.readouterr().out
    assert capture.released and port.closed


def test_lost_face_stops_before_the_next_motion_heartbeat():
    link, port = make_link()
    control = demo.WheelchairControl(link)
    control.update(0.0, "等待眨眼", "前进", face_present=True)
    assert movement_letters(port) == []
    control.update(0.1, "确认成功", "前进", face_present=True)
    control.update(0.3, "选择方向", None, face_present=False)
    control.update(1.2, "选择方向", None, face_present=False)
    control.update(2.31, "选择方向", None, face_present=False)

    assert movement_letters(port) == ["F", "F", "S"]
    link.close()
