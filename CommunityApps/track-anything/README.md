# Track-Anything

> Click a target in any video, and track it frame-by-frame on the Snapdragon NPU.

![screenshot](assets/screenshot.png)

## What it does
Track-Anything takes a video, lets you **click one or more targets** on the first
frame, then segments and tracks those targets across every frame — writing an
output video with a semi-transparent mask overlaid on the tracked object.

It runs the [Track-Anything](https://huggingface.co/qualcomm/Track-Anything)
(XMem) segmentation models **fully on the Qualcomm NPU** through QAI AppBuilder's
`OnnxRuntimeContext` with HTP acceleration — no cloud, no internet needed at
inference time. The XMem working-memory bank (memory keys / shrinkage / values
with affinity read-out) is implemented in NumPy on top of the four ONNX graphs.

Point selection uses **matplotlib** rather than `cv2.imshow`, because the OpenCV
build available on Windows on ARM is headless (no GUI backend).

## Models
| Model | Runtime | Precision | Source |
|-------|---------|-----------|--------|
| Track-Anything (XMem, 4 ONNX graphs) | ONNX / HTP | float | [Qualcomm AI Hub](https://huggingface.co/qualcomm/Track-Anything) |

The four graphs are `encode_key_with_shrinkage`, `encode_key_without_shrinkage`,
`encode_value`, and `segment`. They are **auto-downloaded** on first run from the
Qualcomm AI Hub public asset bucket (~255 MB zip), extracted into `models/`, and
the archive is deleted. **No weights are committed to this repo.**

## Requirements
- OS: Windows on ARM64 (Snapdragon X Elite / X Plus)
- Python >= 3.10
- qai_appbuilder >= 2.24.0
- `opencv-python-headless`, `numpy`, `torch`, `onnxruntime`, `matplotlib`
- 16 GB RAM recommended

> **NPU vs CPU:** on a Snapdragon (Windows on ARM64) device, also install
> `onnxruntime-qnn` to run the ONNX graphs on the NPU/HTP. Without it — or on x64
> machines — the app automatically falls back to the ONNX Runtime **CPU**
> provider, so it still works, just slower.

## Run
```bash
pip install -r requirements.txt
python main.py
```

On Windows you can also double-click [`start.bat`](start.bat).

Then:
1. Pick a video from the list, or press **ENTER** to download and use the default
   `surfing_cutback.mp4` clip.
2. In the pop-up window, **click the target(s)** you want to track (e.g. the
   surfer's body), then press **ENTER** or close the window.
3. The app tracks frame-by-frame and writes `tracked_<video>.mp4` next to the input.

## Notes
- First run downloads models + (optionally) the sample video; subsequent runs
  reuse the local copies.
- `app.json` is the single source of truth for the gallery — see
  [../README.md](../README.md).
- Contribution standards: [../../docs/community.md](../../docs/community.md).

## Credits
Model: [Qualcomm AI Hub — Track-Anything](https://huggingface.co/qualcomm/Track-Anything)
(XMem). App contributed by [@tim202503](https://github.com/tim202503).
