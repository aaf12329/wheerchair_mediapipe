"""同屏预览手部和眼睛，并将经视线与眨眼确认的方向交给轮椅串口层。

main() → 打开摄像头或录像 → landmarks_preview.create_detectors()
  每帧 → read_and_detect() → 同帧的人脸与手部结果
       → update_eyes() → 已有的眨眼与视线状态机
       → WheelchairControl.update() → WheelchairLink → 串口或模拟
       → render_preview() → 眼部关键点、手部骨架和状态栏
       → pressed_key() → Q 退出 / S 停止 / C 重新校准 / I 反转左右
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
import time

import cv2

# 保持从任意工作目录直接运行脚本的入口。
SRC_DIR = str(Path(__file__).resolve().parents[1])
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from camera.video_input import frame_delay_ms, open_video  # noqa: E402
from hardware.serial_link import PROTOCOLS, WheelchairLink  # noqa: E402
from interaction import blink_preview, gaze_direction_preview, keyboard_serial  # noqa: E402
from interaction.gaze_blink_confirm_demo import GazeBlinkDetector  # noqa: E402
from interaction.wheelchair_control import WheelchairControl  # noqa: E402
from vision import landmarks_preview  # noqa: E402

WINDOW_NAME = "MediaPipe Hand and Eye Preview"
PREVIEW_WIDTH, PREVIEW_HEIGHT = landmarks_preview.WIDTH, landmarks_preview.HEIGHT
PANEL_HEIGHT = 128


# ============================ 1) 判定逻辑 ============================


def update_eyes(now: float, face_result, blink, gaze):
    """将同帧的人脸结果送入两套状态机，返回眼部绘制和面板所需的数据。"""
    face = face_result.face_landmarks[0] if face_result.face_landmarks else None
    ear = blink_preview.average_ear(face) if face is not None else None
    return face, blink.update(now, ear), gaze.update(now, face)


# ============================ 2) 设备与画面 ============================


def render_preview(frame, face, hand_result, blink_status, gaze_status, link_status):
    """绘制眼部和手部关键点，在视频上方放置状态栏。"""
    height, width = frame.shape[:2]
    scale = min(PREVIEW_WIDTH / width, PREVIEW_HEIGHT / height)
    if scale != 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    else:
        frame = frame.copy()
    if face is not None:
        blink_preview.draw_eye_points(frame, face)
        gaze_direction_preview.draw_iris_points(frame, face)
    landmarks_preview.draw_hands(frame, hand_result)

    # 视频保持原宽高比，面板放在视频外，以免挡住关键点。
    side_padding = PREVIEW_WIDTH - frame.shape[1]
    frame = cv2.copyMakeBorder(
        frame, PANEL_HEIGHT, 0, side_padding // 2, side_padding - side_padding // 2,
        cv2.BORDER_CONSTANT, value=(18, 18, 18),
    )
    eye_text = "已检测" if face is not None else "未检测"
    gaze_text = gaze_status.raw_direction or "--"
    link_text = f"串口 {link_status.mode}" if link_status.connected else "模拟"
    if not link_status.connected and link_status.last_error:
        link_text = "模拟（串口未连接）"
    if link_status.is_low_battery:
        link_text += " / 低电锁定"
    return blink_preview.draw_chinese_status(frame, (
        f"眼睛 {eye_text}  |  手部 {len(hand_result.hand_landmarks)} 只  |  {link_text}  |  指令 {link_status.intent or '--'}",
        f"视线 {gaze_text}  |  眨眼 {blink_status.blink_count} 次",
        gaze_status.message,
        "Q 退出  |  S 停止  |  C 重新校准  |  I 反转左右",
    ))


# ============================ 3) 主流程 ============================


def main(video: Path | None = None, *, serial_port: str | None = None, firmware: str | None = None) -> None:
    """按同一输入帧驱动双模型、眼部判定、串口输出与窗口。"""
    if video is not None and serial_port is not None:
        raise ValueError("录像模式使用模拟，不能同时指定串口。")
    link = WheelchairLink(serial_port, firmware=firmware)
    capture, fps = (landmarks_preview.open_camera(), None) if video is None else open_video(video)
    try:
        face_detector, hand_detector = landmarks_preview.create_detectors()
        link.open()
        playback_started = time.perf_counter()
        started = playback_started if fps is None else 0.0
        blink = blink_preview.BlinkDetector(started)
        gaze = GazeBlinkDetector(started)
        control = WheelchairControl(link)
        frame_count = 0
        key_available_at = 0.0
        if link.connected:
            link.set_intent("停", now=started)
        elif link.last_error:
            print(f"串口未连接，已切到模拟模式。{link.last_error}")
        print("手部与眼睛预览已启动。请睁眼看正中校准，点击窗口后按 Q 退出或 S 停止。")

        while True:
            video_time = frame_count / fps if fps is not None else None
            result = landmarks_preview.read_and_detect(
                capture, face_detector, hand_detector, started, video_time=video_time,
            )
            if result is None:
                if frame_count == 0:
                    raise RuntimeError(f"录像没有可读取的画面：{video}")
                print("录像播放结束。")
                break
            frame, now, face_result, hand_result = result
            frame_count += 1
            face, blink_status, gaze_status = update_eyes(now, face_result, blink, gaze)
            link_status = control.update(now, gaze_status.state, gaze_status.active, face_present=face is not None)
            preview = render_preview(frame, face, hand_result, blink_status, gaze_status, link_status)
            cv2.imshow(WINDOW_NAME, preview)

            if not landmarks_preview.window_is_alive(WINDOW_NAME):
                break
            key_time = time.perf_counter()
            delay = frame_delay_ms(playback_started, frame_count, fps, key_time)
            key, key_available_at = landmarks_preview.pressed_key(
                key_time, key_available_at, delay, immediate_keys="sq",
            )
            if key == "q":
                break
            if key in ("s", "c"):
                link.set_intent("停", now=now)
                gaze.reset(now)
                if key == "c":
                    blink.reset(now)
            if key == "i":
                gaze.toggle_invert()
    finally:
        try:
            link.set_intent("停")
        finally:
            link.close()
            capture.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = ArgumentParser(description="MediaPipe 手部与眼睛集成预览")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video", type=Path, help="在模拟模式下播放录像")
    source.add_argument("--keyboard", action="store_true", help="在 Windows 终端使用键盘控制，不打开摄像头")
    parser.add_argument("--serial-port", help="连接指定串口，例如 COM3")
    parser.add_argument("--firmware", choices=PROTOCOLS, help="固件协议，指定串口时默认 motor-test")
    args = parser.parse_args()
    if args.video is not None and args.serial_port is not None:
        parser.error("录像模式使用模拟，不能同时指定串口。")
    if args.keyboard:
        keyboard_serial.main(args.serial_port, firmware=args.firmware)
    else:
        main(args.video, serial_port=args.serial_port, firmware=args.firmware)
