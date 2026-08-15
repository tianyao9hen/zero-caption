# Zero Caption 发布检查清单

## 环境

- [ ] 使用受支持的 Python 版本创建干净虚拟环境。
- [ ] 执行 `scripts/build_windows.ps1`，由脚本安装运行依赖和 `PyInstaller`。
- [ ] 确认构建脚本可以准备 Inno Setup；它只属于开发期工具，不进入目标电脑依赖。
- [ ] 确认 `resources/bin/ffmpeg/` 中包含 `ffmpeg.exe` 和 `ffprobe.exe`。
- [ ] 确认 `resources/models/small/` 与 `resources/models/medium/` 都包含 `config.json`、`model.bin` 和 `tokenizer.json`。
- [ ] 确认 Windows 构建依赖已安装 `nvidia-cublas-cu12`，且虚拟环境中包含 `cublas64_12.dll`。

## 自动化验证

- [ ] 执行 `powershell -ExecutionPolicy Bypass -File scripts/smoke_test.ps1`。
- [ ] 执行完整 `pytest`，并记录真实 ASR 测试是否因环境缺少模型而跳过或失败。
- [ ] 使用独立 VS Code 调试配置启动 `app.main`，确认主窗口标题为 `Zero Caption`。
- [ ] 在 NVIDIA GPU 机器上确认设置页显示名称、显存和 `medium + CUDA + float16` 推荐。
- [ ] 分别验证自动 GPU 推理成功，以及模拟 CUDA 失败时自动回退 CPU。
- [ ] 用测试视频分别验证外挂字幕和烧录字幕导出。

## 打包

- [ ] 执行 `scripts/build_windows.ps1`，脚本会生成便携目录、安装包和 SHA256 文件。
- [ ] 或单独执行 `scripts/verify_packaged_app.ps1`，从没有仓库源码的目录启动 `dist/ZeroCaption/ZeroCaption.exe`。
- [ ] 执行 `scripts/verify_installer.ps1`，确认静默安装、隔离环境启动和卸载清理均通过。
- [ ] 验收环境必须清除 `PYTHONHOME`、`PYTHONPATH`、虚拟环境和 Hugging Face 缓存变量，并把 PATH 限制到 Windows 系统目录。
- [ ] 确认安装目录包含 Python、VC 运行库、Qt、CTranslate2、`cuBLAS 12`、ONNX Runtime、FFmpeg、ffprobe 和 `small`、`medium` 两套模型。
- [ ] 确认首次启动会创建工作区、日志目录和 `zero_caption.sqlite3`。
- [ ] 确认日志和诊断包不包含原始视频或音频。

## 配置与隐私

- [ ] 翻译 API 地址、模型名和 API 密钥可在设置页提供；密钥也兼容从环境变量读取。
- [ ] ASR 模型、设备、精度与 CPU 回退选项可在设置页保存，重启后仍保持。
- [ ] 检查翻译请求日志没有 API 密钥、原始视频或原始音频内容。
- [ ] 确认导出目录和临时目录位于用户工作区内。
