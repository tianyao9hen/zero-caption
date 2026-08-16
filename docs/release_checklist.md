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
- [ ] 执行 `scripts/verify_installer.ps1`，确认带空格的自选目录安装、隔离环境启动和卸载清理均通过。
- [ ] 确认安装向导始终显示目录选择页，并拒绝不属于 Zero Caption 的非空目录。
- [ ] 确认普通卸载会清空安装目录并询问是否清理历史记录，默认选择“否”。
- [ ] 分别确认“保留历史”不会删除 `%LOCALAPPDATA%\ZeroCaption`，“清理历史”会删除该应用专属目录。
- [ ] 验收环境必须清除 `PYTHONHOME`、`PYTHONPATH`、虚拟环境和 Hugging Face 缓存变量，并把 PATH 限制到 Windows 系统目录。
- [ ] 确认安装目录包含 Python、VC 运行库、Qt、CTranslate2、`cuBLAS 12`、ONNX Runtime、FFmpeg、ffprobe 和 `small`、`medium` 两套模型。
- [ ] 确认首次启动会创建工作区、日志目录和 `zero_caption.sqlite3`。
- [ ] 确认日志和诊断包不包含原始视频或音频。

## 配置与隐私

- [ ] 翻译 API 地址、模型名和 API 密钥可在设置页提供；密钥也兼容从环境变量读取。
- [ ] 系统提示词可以编辑、保存并在下一次翻译生效；当前表单可以用用户提示词后台测试。
- [ ] 多条字幕会逐条独立请求模型，并在任务页实时追加原文与译文。
- [ ] 翻译中途失败后点击“从检查点继续”，确认已完成译文不会重复请求模型。
- [ ] 应用异常退出后重启，确认处理模式、导出模式和翻译上下文仍能恢复。
- [ ] 修改单句译文后重新导出，确认成品使用当前译文而不是旧旁车字幕。
- [ ] ASR 模型、设备、精度与 CPU 回退选项可在设置页保存，重启后仍保持。
- [ ] 检查翻译请求日志没有 API 密钥、原始视频或原始音频内容。
- [ ] 确认导出目录和临时目录位于用户工作区内。
