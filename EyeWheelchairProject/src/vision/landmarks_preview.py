"""第 2 周：MediaPipe 人脸、眼睛和手部关键点可视化。

本程序仅把识别结果绘制到屏幕，绝不会向 Arduino 或轮椅发送命令。
按 Q 退出；按 S 保存当前带关键点的截图。

文件分三段：
  1) 关键点绘制（把模型给的 0~1 坐标翻译成屏幕上的点、线和文字）—— 不碰摄像头
  2) 摄像头与检测器（打开设备、建人脸与手部两个识别器）
  3) 主流程 main()：读帧 → 画 → 推窗口 → 按键

============================ 调用关系总览 ============================

  __main__  →  main()
  │
  ├─ 启动阶段（每个只执行一次）
  │   ├─ open_camera()                打开摄像头，返回 cap（后面每帧从它 read）
  │   ├─ create_detectors()           建两个识别器：人脸 + 手部
  │   │                                 （读 models/face_landmarker.task 和 hand_landmarker.task）
  │   └─ print(...)                   启动提示
  │
  ├─ 每帧循环（★ 每帧都执行；顺序 看 → 画 → 控）
  │   ├─★ read_and_detect(cap, face_detector, hand_detector, started)
  │   │    ├─ cap.read() / cv2.flip / cv2.cvtColor / mp.Image   取一帧并预处理
  │   │    ├─ face_detector.detect_for_video(图, 时间戳)   ← 第 1 次推理（人脸 478 点）
  │   │    ├─ hand_detector.detect_for_video(图, 时间戳)   ← 第 2 次推理（每只手 21 点）
  │   │    └─ 返回 (frame, now, 人脸结果, 手部结果)
  │   ├─★ draw_results(frame, 人脸结果, 手部结果, fps)
  │   │    ├─ draw_face(frame, 每张脸)      478 个绿点 + 双眼黄圈
  │   │    │    └─ point(lm, w, h)          归一化坐标 → 像素坐标
  │   │    ├─ draw_hands(frame, 手部结果)    为每只手选取左右手标签
  │   │    │    └─ draw_hand() → point()    绘制手部骨架与标签
  │   │    └─ 左上角黑底状态栏：FACE / HAND / FPS（英文，用 cv2.putText 画）
  │   ├─★ cv2.imshow(WINDOW_NAME, frame)    把这一帧推到窗口
  │   ├─★ window_is_alive()                 问窗口还活着没（点 ✕ 后为假）
  │   └─★ pressed_key(now, key_available_at)  读按键：q 退出 / s 存截图
  │        └─ save_snapshot(frame) → stamp()  存到 data/landmark_snapshots/
  │
  └─ finally（无论怎么退出都执行）
      ├─ cap.release()                  交还摄像头
      └─ cv2.destroyAllWindows()        关窗口

这个文件**没有状态机、也没有阈值判定**——它只做"翻译和显示"：

    模型输出（0~1 的归一化坐标）──point()──▶ 屏幕像素坐标 ──cv2──▶ 画面上的点 / 线 / 文字

唯一的"判断"是手的左右标签，直接取自模型给出的 handedness，本程序不做二次推断。

它和后面三步的关系：这里画出来的眼睛轮廓（12 个点）就是第 3 步算 EAR、第 4/5 步
取虹膜和眼角时用的同一批点号——所以这个脚本是"关键点质量"的目视验收工具。
"""
from datetime import datetime
from pathlib import Path
import sys
import time

import cv2
import numpy as np

# 兼容直接运行此脚本。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.video_input import open_camera as open_video_camera  # noqa: E402
from common.paths import FACE_MODEL, HAND_MODEL, LANDMARK_SNAPSHOTS_DIR as SNAPSHOT_DIR  # noqa: E402
from vision.eye_geometry import LEFT_EYE, RIGHT_EYE  # noqa: E402
from vision.mediapipe_video import create_face_landmarker, create_hand_landmarker, read_detection_input  # noqa: E402

# ---- 运行参数 ----
CAMERA_INDEX = 0
WIDTH, HEIGHT = 960, 540
KEY_DEBOUNCE_SECONDS = 0.25  # 两次按键响应的最小间隔：按住不放时不再连发

WINDOW_NAME = "MediaPipe Landmarks | Q quit | S snapshot"

# MediaPipe Face Landmarker 的眼睛轮廓关键点索引。
# 和第 3 步算 EAR（blink_preview.py）、第 4/5 步取虹膜与眼角用的是同一批点。
EYE_LOOPS = (LEFT_EYE, RIGHT_EYE)


# ============================ 1) 关键点绘制（不碰摄像头） ============================


def point(lm, width: int, height: int) -> tuple[int, int]:
    """把一个归一化关键点（0~1）换成屏幕像素坐标。

    调用关系：被 draw_face() 和 draw_hand() 调用；内部什么都不调用。
    """
    return int(lm.x * width), int(lm.y * height)


def draw_face(frame, face_landmarks) -> None:
    """绘制全部脸部点，并突出眼睛轮廓。

    调用关系：被 draw_results() 对每张脸调用一次；内部调用 point()。
    注意它直接在传入的 frame 上画（不返回新图），因为这里是"补充绘制"而不是产出一张新画面。
    """
    h, w = frame.shape[:2]
    for lm in face_landmarks:
        cv2.circle(frame, point(lm, w, h), 1, (0, 255, 0), -1)

    for loop in EYE_LOOPS:
        pts = [point(face_landmarks[i], w, h) for i in loop]
        cv2.polylines(frame, [np.array(pts, dtype=np.int32)], True, (0, 255, 255), 1)


def draw_hand(frame, landmarks, label: str) -> None:
    """绘制 21 个手部点与基础骨架连接。

    调用关系：被 draw_results() 对每只手调用一次；内部调用 point()。
    label 是 LEFT / RIGHT / HAND（拿不到左右时用 HAND），画在手腕上方。
    """
    h, w = frame.shape[:2]
    links = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
    ]
    pts = [point(lm, w, h) for lm in landmarks]
    for a, b in links:
        cv2.line(frame, pts[a], pts[b], (255, 100, 0), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (0, 0, 255), -1)
    cv2.putText(frame, label, (pts[0][0] + 8, pts[0][1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2)


def draw_results(frame, face_result, hand_result, fps: float) -> None:
    """把一帧的所有识别结果画到画面上：人脸点、手部骨架、左上角状态栏。

    调用关系：被 main() 每帧调用一次；内部调用 draw_face()（每张脸一次）
    和 draw_hands()，最后铺黑底画两行英文状态。
    它只读识别结果，不改任何状态——所以调它不会影响别的东西。
    """
    for landmarks in face_result.face_landmarks:
        draw_face(frame, landmarks)

    draw_hands(frame, hand_result)

    faces = len(face_result.face_landmarks)
    hands = len(hand_result.hand_landmarks)
    cv2.rectangle(frame, (0, 0), (410, 82), (0, 0, 0), -1)
    cv2.putText(frame, f"FACE: {faces} | HAND: {hands} | {fps:.1f} FPS", (14, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, "Q quit | S snapshot | VISUAL ONLY", (14, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)


def draw_hands(frame, hand_result) -> None:
    """为关键点预览和手眼集成预览绘制手部骨架与左右手标签。"""
    for index, landmarks in enumerate(hand_result.hand_landmarks):
        label = "HAND"
        if index < len(hand_result.handedness) and hand_result.handedness[index]:
            label = hand_result.handedness[index][0].category_name.upper()
        draw_hand(frame, landmarks, label)


# ============================ 2) 摄像头与检测器 ============================


def open_camera() -> cv2.VideoCapture:
    """启动预览时按本入口的分辨率打开摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, WIDTH, HEIGHT,
        error_message="摄像头无法打开：请关闭占用摄像头的软件，或将 CAMERA_INDEX 改为 1。",
    )


def create_detectors():
    """创建同帧预览使用的人脸和手部检测器。"""
    missing = [path.name for path in (FACE_MODEL, HAND_MODEL) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少模型：{', '.join(missing)}")
    return create_face_landmarker(FACE_MODEL), create_hand_landmarker(HAND_MODEL)


# ============================ 3) 主流程 ============================


def read_and_detect(cap, face_detector, hand_detector, started: float, *, video_time: float | None = None):
    """对同一张推理图运行双模型，返回帧、当前时间及两个检测结果。"""
    prepared = read_detection_input(cap, started, clock=time.perf_counter, video_time=video_time)
    if prepared is None:
        return None
    frame, now, image, timestamp_ms = prepared
    face_result = face_detector.detect_for_video(image, timestamp_ms)
    hand_result = hand_detector.detect_for_video(image, timestamp_ms)
    return frame, now, face_result, hand_result


def stamp() -> str:
    """生成"年月日_时分秒"格式的时间戳，用来拼截图文件名。

    调用关系：只被 save_snapshot() 调用。
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_snapshot(frame) -> Path:
    """把当前画面存成 jpg，返回保存路径。

    调用关系：被 main() 的 S 键分支调用；内部调用 stamp() 拼文件名。
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"landmarks_{stamp()}.jpg"
    cv2.imwrite(str(path), frame)
    return path


def window_is_alive(window_name: str = WINDOW_NAME) -> bool:
    """点窗口右上角 ✕ 不会让 waitKey 返回任何值，只能自己问窗口还活着没。

    调用关系：被 main() 每帧调用；返回 False 时 main() 就 break 退出循环。
    """
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def pressed_key(now: float, key_available_at: float, delay_ms: int = 1, *, immediate_keys: str = ""):
    """读一次按键并去抖，返回（按键小写字符 或 None, 新的可响应时间）。

    调用关系：被预览入口每帧调用；内部调用 cv2.waitKey(delay_ms)
    （这一次调用同时兼职：取按键 + 让窗口有机会刷新）。
    immediate_keys 指定不等待防抖间隔的键，例如停止和退出。
    """
    raw_key = cv2.waitKey(delay_ms)
    if raw_key == -1:
        return None, key_available_at
    key = chr(raw_key & 0xFF).lower()
    if key not in immediate_keys and now < key_available_at:
        return None, key_available_at
    return key, now + KEY_DEBOUNCE_SECONDS


def main() -> None:
    """程序入口：建好摄像头和两个识别器后，每帧走一遍 看→画→控。"""
    # ==================== 启动阶段（下面每个调用只执行一次）====================
    cap = open_camera()                       # ① 打开摄像头
    face_detector, hand_detector = create_detectors()  # ② 建两个识别器
    started = time.perf_counter()             # 给 MediaPipe 算毫秒时间戳 + 算帧率用
    frame_count = 0                           # 帧计数器（只用来算帧率）
    key_available_at = 0.0                    # 按键防抖：下次允许响应的时间点

    print("关键点预览已启动：请先点一下视频窗口让它获得焦点，然后 Q 退出、S 保存截图。")
    try:
        # ================= 每帧循环：看 → 画 → 控 =================
        while True:
            # ---- ① 看：取一帧并跑两个识别器 ----
            frame, now, face_result, hand_result = read_and_detect(cap, face_detector, hand_detector, started)

            # ---- ② 画：人脸点 + 手部骨架 + 左上角状态栏 ----
            frame_count += 1
            fps = frame_count / max(now - started, 0.001)
            draw_results(frame, face_result, hand_result, fps)
            cv2.imshow(WINDOW_NAME, frame)

            # ---- ③ 控：先看窗口还活着没，再读键盘 ----
            if not window_is_alive():            # 窗口被点 ✕ 关掉就退出
                print("窗口已关闭，退出。")
                break
            key, key_available_at = pressed_key(now, key_available_at)
            if key == "q":
                break
            if key == "s":
                print(f"截图已保存：{save_snapshot(frame)}")
    finally:
        # 不调用两个检测器的 close()：实测它要卡约 42 秒（MediaPipe 1.0.1 拆推理图的等待）。
        # 配合 create_detectors() 里的保活引用，进程 1 秒内干净退出，内存由系统回收。
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
