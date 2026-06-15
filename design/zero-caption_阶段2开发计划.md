# Zero Caption 阶段 2 开发计划

> **给执行型代理的说明：** 建议使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务逐步执行。本计划使用勾选框跟踪进度。

**目标：** 在不依赖桌面 UI 的前提下，打通“导入视频 -> 探测元数据 -> 抽取音频 -> 本地 ASR -> 生成原文字幕”的最小闭环。

**架构：** 这一阶段只做本地识别链路，不碰翻译和导出。实现顺序保持从下到上：先补工作区和媒体探测，再做抽音频与切块，再接入本地 ASR，最后做字幕后处理和端到端串联。所有能力仍然通过 `core/ports/` 和 `core/usecases/` 驱动，`infrastructure/` 只负责具体实现。

**技术栈：** `PySide6` 现有骨架、`FFmpeg/ffprobe`、`faster-whisper`、`Path`/`dataclass`、`pytest`

---

## 任务 1：工作区目录与媒体探测

**文件：**
- 修改：`infrastructure/storage/workspace.py`
- 新增：`infrastructure/media/ffprobe.py`
- 新增：`tests/unit/test_workspace.py`
- 新增：`tests/integration/test_ffprobe_adapter.py`

- [ ] **步骤 1：先补失败测试**

  为 `WorkspaceManager` 写测试，确认它会创建项目级目录结构；为 `ffprobe` 适配器写测试，确认它能返回时长、分辨率和音轨信息。

- [ ] **步骤 2：运行测试确认当前失败**

  运行：`pytest tests/unit/test_workspace.py tests/integration/test_ffprobe_adapter.py -v`

  预期：`ffprobe` 相关测试先失败，提示适配器还未实现。

- [ ] **步骤 3：实现最小功能**

  让 `WorkspaceManager` 生成 `source/`、`temp/`、`cache/`、`subtitles/`、`exports/`、`logs/`；让 `ffprobe` 适配器只负责把媒体基础信息读出来，不做其他编排。

- [ ] **步骤 4：回跑测试**

  运行：`pytest tests/unit/test_workspace.py tests/integration/test_ffprobe_adapter.py -v`

  预期：全部通过。

- [ ] **步骤 5：提交**

  提交范围只包含工作区和媒体探测。

---

## 任务 2：抽音频与音频切块

**文件：**
- 修改：`infrastructure/media/ffmpeg.py`
- 新增：`infrastructure/media/segmenter.py`
- 新增：`tests/integration/test_ffmpeg_adapter.py`
- 新增：`tests/unit/test_segmenter.py`

- [ ] **步骤 1：先补失败测试**

  为 `FFmpegAdapter` 写测试，确认它能抽出 `wav` 或 `flac`；为切块组件写测试，确认固定时长切块和少量重叠切块都能产出正确片段。

- [ ] **步骤 2：运行测试确认当前失败**

  运行：`pytest tests/integration/test_ffmpeg_adapter.py tests/unit/test_segmenter.py -v`

  预期：适配器和切块逻辑都还没有实现时，测试失败。

- [ ] **步骤 3：实现最小功能**

  让 `FFmpegAdapter` 只做抽音频；让 `segmenter` 只做一件事：把长音频拆成适合识别的小段，并保留每段起止时间。

- [ ] **步骤 4：回跑测试**

  运行：`pytest tests/integration/test_ffmpeg_adapter.py tests/unit/test_segmenter.py -v`

  预期：全部通过。

- [ ] **步骤 5：提交**

  提交范围只包含抽音频和切块。

---

## 任务 3：本地 ASR 适配器

**文件：**
- 新增：`infrastructure/asr/__init__.py`
- 新增：`infrastructure/asr/faster_whisper_engine.py`
- 修改：`app/container.py`
- 新增：`tests/integration/test_faster_whisper_engine.py`

- [ ] **步骤 1：先补失败测试**

  为 ASR 适配器写测试，确认它接收音频路径后，能返回带时间轴的字幕片段；如果模型加载较重，先用较小样例和明确的 fixture 路径。

- [ ] **步骤 2：运行测试确认当前失败**

  运行：`pytest tests/integration/test_faster_whisper_engine.py -v`

  预期：适配器未实现时失败。

- [ ] **步骤 3：实现最小功能**

  让 `faster-whisper` 适配器只负责把音频转成原始字幕片段，不做去重、断句或 SRT 输出。

- [ ] **步骤 4：把适配器接入容器**

  在 `app/container.py` 里完成依赖装配，让后续用例能拿到真实的 ASR 实现。

- [ ] **步骤 5：回跑测试**

  运行：`pytest tests/integration/test_faster_whisper_engine.py -v`

  预期：通过。

- [ ] **步骤 6：提交**

  提交范围只包含 ASR 适配器和容器接线。

---

## 任务 4：字幕后处理与 SRT 输出

**文件：**
- 新增：`infrastructure/subtitle/__init__.py`
- 新增：`infrastructure/subtitle/formatter.py`
- 新增：`infrastructure/subtitle/aligner.py`
- 新增：`infrastructure/subtitle/srt_writer.py`
- 新增：`tests/unit/test_subtitle_formatter.py`
- 新增：`tests/unit/test_subtitle_aligner.py`
- 新增：`tests/unit/test_srt_writer.py`

- [ ] **步骤 1：先补失败测试**

  为去重、断句、时间轴规整和 SRT 写出分别写测试，明确输入片段和期望输出。

- [ ] **步骤 2：运行测试确认当前失败**

  运行：`pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v`

  预期：字幕后处理组件未实现时失败。

- [ ] **步骤 3：实现最小功能**

  先把原始字幕片段整理成稳定可用的 SRT，再考虑更细的断句和边界修正。

- [ ] **步骤 4：回跑测试**

  运行：`pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v`

  预期：全部通过。

- [ ] **步骤 5：提交**

  提交范围只包含字幕后处理和 SRT 输出。

---

## 任务 5：端到端识别链路串联

**文件：**
- 修改：`core/usecases/transcribe_video.py`
- 修改：`core/services/task_service.py`
- 修改：`app/container.py`
- 新增：`tests/integration/test_transcribe_video_flow.py`

- [ ] **步骤 1：先补失败测试**

  写一个端到端测试，覆盖“导入视频 -> 探测 -> 抽音频 -> ASR -> 生成原文字幕”这条主路径。

- [ ] **步骤 2：运行测试确认当前失败**

  运行：`pytest tests/integration/test_transcribe_video_flow.py -v`

  预期：当前链路不完整时失败。

- [ ] **步骤 3：把各个基础设施能力串进用例**

  让 `TranscribeVideo` 负责编排，不直接碰具体命令细节；让 `TaskService` 只做入口转发和任务摘要更新。

- [ ] **步骤 4：补齐重复执行的基础复用**

  同一个视频再次执行时，优先复用已抽取音频或已有字幕结果，避免重复计算。

- [ ] **步骤 5：回跑测试**

  运行：`pytest tests/integration/test_transcribe_video_flow.py -v`

  预期：通过。

- [ ] **步骤 6：提交**

  提交范围只包含主链路串联和最终验收测试。

---

## 验收标准

1. 给定一个本地视频，可以生成原文 `SRT`。
2. 项目目录结构完整，临时产物和正式字幕各归其位。
3. 同一视频重复执行时，至少能复用已有抽音频结果或已有识别结果。
4. 阶段 2 不引入翻译、导出或 SQLite 持久化。

