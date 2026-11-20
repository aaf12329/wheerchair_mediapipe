# wheerchair_mediapipe

基于 OpenCV 和 MediaPipe 的眼控轮椅视觉原型，用摄像头识别人脸和手部关键点，演示注视选方向与眨眼确认。主演示默认使用屏幕模拟模式。

An eye-controlled wheelchair vision prototype using OpenCV and MediaPipe. It tracks face and hand landmarks and demonstrates gaze selection with blink confirmation. The main demo runs in on-screen simulation mode by default.

## 从这里开始 / Start here

| 要做什么 / Task | 入口 / Entry point |
|---|---|
| 了解交互设计与历史记录 / Read the design and project history | [项目文档 / Project notes](EyeWheelchairProject/README.md) |
| 检查摄像头 / Check the camera | [摄像头预览 / Camera preview](EyeWheelchairProject/src/camera/camera_preview.py) |
| 演示视线与眨眼交互 / Run the gaze and blink demo | [主程序 / Demo entry point](EyeWheelchairProject/src/interaction/gaze_blink_confirm_demo.py) |
| 同屏检测手部与眼睛 / Preview hands and eyes together | [手眼预览 / Hand and eye preview](EyeWheelchairProject/src/interaction/hand_eye_preview.py) |
| 接手仓库或修改代码 / Work on the repository | [AGENTS.md](AGENTS.md) |
| 查看许可 / Read the license | [MIT License](LICENSE) |

## 分支 / Branches

| 分支 / Branch | 用途 / Purpose |
|---|---|
| `main` | 本仓库的 MediaPipe 基线 / Baseline for this repository's MediaPipe implementation |
| `chen/main` | 从本仓库 `main` 建立的 Chen 开发主线 / Chen's development branch based on this repository's `main` |

`EyeWheelchairProject` 项目文档中的 `chen` 指原仓库的历史分支。`chen/main` 的起点是本仓库的 MediaPipe 代码。

The `chen` branch mentioned in the `EyeWheelchairProject` notes refers to the original repository. The `chen/main` branch starts from the MediaPipe code in this repository.

## 运行与测试 / Run and test

Windows 上可使用已有的 Conda 或 venv 环境。若使用已配置的 `mul_pro`，先运行 `conda activate mul_pro`。在新环境中安装依赖可参考下方命令。

On Windows, use an existing Conda environment or venv. If `mul_pro` is already set up, run `conda activate mul_pro` first. Use the following command to install dependencies in a fresh environment.

```powershell
python -m pip install opencv-contrib-python mediapipe numpy pillow pyserial pytest
```

在仓库根目录运行主演示或离线测试。主演示默认打开摄像头，也可用 `--video` 播放已有的 MP4。录像模式只使用屏幕模拟，播放完自动退出。离线测试无需摄像头，缺少可用录像时会跳过使用本地录像的测试。`pytest` 仅用于测试。

Run the demo or the offline tests from the repository root. The demo opens the camera by default and accepts an MP4 file through `--video`. Video playback uses on-screen simulation and exits at the end. The offline tests run without a camera and skip the test that uses a local recording when none is available. `pytest` is only needed for tests.

```powershell
python .\EyeWheelchairProject\src\interaction\gaze_blink_confirm_demo.py
python .\EyeWheelchairProject\src\interaction\gaze_blink_confirm_demo.py --video "C:\path\to\recording.mp4"
python .\EyeWheelchairProject\src\interaction\hand_eye_preview.py --video "C:\path\to\recording.mp4"
python -m pytest -q .\EyeWheelchairProject\tests
```
