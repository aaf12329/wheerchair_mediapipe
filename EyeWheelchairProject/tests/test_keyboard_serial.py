"""验证 Windows 键码解析、主程序分派和假串口的停车行为。"""

import runpy
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import hand_eye_preview
from interaction import keyboard_serial
from test_serial_link import FakeSerial, make_link, movement_letters


def test_read_key_decodes_extended_arrows_and_letters():
    console = SimpleNamespace(
        kbhit=Mock(side_effect=[False, True, True, True, True]),
        getwch=Mock(side_effect=["\xe0", "H", "\x00", "K", "\xe0", "X", "R"]),
    )
    assert [keyboard_serial.read_key(console) for _ in range(5)] == [None, "up", "left", None, "r"]


def test_keyboard_cli_routes_to_console_mode_with_serial_port(monkeypatch):
    run = Mock()
    monkeypatch.setattr(keyboard_serial, "main", run)
    monkeypatch.setattr(sys, "argv", [hand_eye_preview.__file__, "--keyboard", "--serial-port", "COM9"])

    runpy.run_path(hand_eye_preview.__file__, run_name="__main__")

    run.assert_called_once_with("COM9")


def test_keyboard_sends_commands_and_stops_when_input_expires_or_exits(monkeypatch, capsys):
    port = FakeSerial()
    link = keyboard_serial.WheelchairLink("COM9", port_factory=lambda *args, **kwargs: port)
    transport = Mock(return_value=link)
    keys = ["up", "up", None, None, "right", "down", "left", "q"]
    times = Mock(side_effect=[0.0, 0.4, 0.8, 1.12, 1.14, 1.16, 1.18])
    monkeypatch.setattr(keyboard_serial, "sys", SimpleNamespace(platform="win32", stdin=Mock(isatty=lambda: True)))
    monkeypatch.setitem(sys.modules, "msvcrt", Mock())
    monkeypatch.setattr(keyboard_serial, "WheelchairLink", transport)
    monkeypatch.setattr(keyboard_serial, "time", SimpleNamespace(perf_counter=times, sleep=Mock()))
    monkeypatch.setattr(keyboard_serial, "read_key", Mock(side_effect=keys))

    keyboard_serial.main("COM9")

    transport.assert_called_once_with("COM9")
    assert movement_letters(port) == ["S", "F", "S", "R", "S", "L", "S"]
    assert "[串口 COM9] 已发送 F" in capsys.readouterr().out
    assert port.closed


def test_keyboard_checks_low_battery_before_sending_direction(monkeypatch):
    link, port = make_link(rx=b"BATTERY:10,188\n")
    monkeypatch.setattr(keyboard_serial, "time", SimpleNamespace(perf_counter=lambda: 0.0, sleep=Mock()))
    monkeypatch.setattr(keyboard_serial, "read_key", Mock(side_effect=["w", "q"]))
    try:
        keyboard_serial.run_keyboard(Mock(), link)
        assert movement_letters(port) == ["S"]
    finally:
        link.close()
