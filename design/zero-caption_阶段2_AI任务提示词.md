# Zero Caption 阶段 2 AI 任务提示词

> 说明：这份文档用于把 `design/zero-caption_阶段2_AI单次执行任务清单.md` 进一步转成可直接复制给 AI 的提示词。  
> 使用方式：每次复制“通用前置提示词” + 对应任务提示词，一次只发一个任务。

---

## 一、通用前置提示词

```text
你正在为 zero-caption 仓库执行阶段 2 的开发任务。

开始前必须先检查并读取仓库根目录的 AGENTS.md；如果存在，必须完整阅读，并在工作日志中说明已读取。

然后请继续阅读以下文档，并据此理解当前任务边界：
1. design/zero-caption_开发计划.md
2. design/zero-caption_阶段2开发计划.md
3. design/zero-caption_阶段2_AI单次执行任务清单.md
4. design/视频字幕生成与翻译软件_应用框架设计.md
5. design/推荐项目骨架说明.md

执行要求：
1. 严格只做我本次给你的任务，不要提前实现后续任务。
2. 遵守仓库分层：业务编排放 core，基础设施细节放 infrastructure，UI 不参与这次任务。
3. 先补测试，再实现，再运行相关测试。
4. 所有新增或修改的注释、docstring、测试说明必须使用中文。
5. 如果遇到阻塞，先说明阻塞点和原因，不要擅自扩展范围。
6. 完成后请汇报：修改了哪些文件、运行了哪些测试、结果如何、是否还有风险或后续依赖。
```

---

## 二、任务提示词

### S2-01：补工作区项目级目录测试

```text
请执行阶段2任务 S2-01：补工作区项目级目录测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先用测试把项目级目录结构约束钉住。

本次只做：
- 修改 tests/test_workspace.py
- 为项目级目录结构补测试
- 明确需要的子目录：source/、temp/、cache/、subtitles/、exports/、logs/

本次不要做：
- 不修改 infrastructure/storage/workspace.py
- 不新增 ffprobe
- 不实现任何生产代码

完成标准：
- 新测试能够清楚表达“当前应该失败，因为项目级目录功能尚未实现”

建议验证命令：
- pytest tests/test_workspace.py -v
```

### S2-02：实现项目级目录结构创建

```text
请执行阶段2任务 S2-02：实现项目级目录结构创建。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 让工作区层具备创建项目级目录结构的能力。

本次只做：
- 修改 infrastructure/storage/workspace.py
- 必要时调整 tests/test_workspace.py
- 为 WorkspaceManager 增加项目级目录相关接口
- 让 S2-01 的测试通过

本次不要做：
- 不处理媒体探测
- 不处理项目实体、仓储或任务服务

完成标准：
- 指定项目目录后，可以稳定创建阶段2需要的全部子目录

建议验证命令：
- pytest tests/test_workspace.py -v
```

### S2-03：增加媒体探测结果模型与测试样例约定

```text
请执行阶段2任务 S2-03：增加媒体探测结果模型与测试样例约定。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先把媒体探测输出结构和测试样例约定定清楚。

本次只做：
- 新增 core/dto/media_dto.py
- 新增或补充 tests/fixtures/README.md
- 新增 tests/integration/test_ffprobe_adapter.py
- 定义媒体基础信息 DTO
- 写 ffprobe 适配器测试骨架

本次不要做：
- 不实现 ffprobe 适配器
- 不修改 TranscribeVideo
- 不碰抽音频逻辑

完成标准：
- 测试和 DTO 能清楚表达需要读取的字段，例如时长、分辨率、音轨信息

建议验证命令：
- pytest tests/integration/test_ffprobe_adapter.py -v
```

### S2-04：实现 ffprobe 适配器

```text
请执行阶段2任务 S2-04：实现 ffprobe 适配器。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 真正读出视频媒体元数据。

本次只做：
- 新增 infrastructure/media/ffprobe.py
- 必要时调整 tests/integration/test_ffprobe_adapter.py
- 实现 ffprobe 命令封装
- 返回结构化探测结果
- 保留命令、退出码和错误输出

本次不要做：
- 不实现抽音频
- 不写切块逻辑
- 不修改 TaskService

完成标准：
- ffprobe 集成测试通过
- 结果结构稳定，可供后续用例使用

建议验证命令：
- pytest tests/integration/test_ffprobe_adapter.py -v
```

### S2-05：补抽音频适配器测试

```text
请执行阶段2任务 S2-05：补抽音频适配器测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先把视频抽音频行为用测试固定下来。

本次只做：
- 新增 tests/integration/test_ffmpeg_adapter.py
- 补充“视频转 wav 或 flac”的测试
- 明确输出路径和产物存在性断言

本次不要做：
- 不修改 infrastructure/media/ffmpeg.py
- 不实现切块

完成标准：
- 测试能够失败并明确指出当前 FFmpegAdapter 仍是占位实现

建议验证命令：
- pytest tests/integration/test_ffmpeg_adapter.py -v
```

### S2-06：实现 FFmpeg 抽音频能力

```text
请执行阶段2任务 S2-06：实现 FFmpeg 抽音频能力。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 让 FFmpegAdapter 具备最小可用的抽音频能力。

本次只做：
- 修改 infrastructure/media/ffmpeg.py
- 必要时调整 tests/integration/test_ffmpeg_adapter.py
- 实现抽音频命令拼装和执行
- 支持至少一种稳定输出格式，优先 wav

本次不要做：
- 不实现烧录
- 不实现视频导出
- 不写切块

完成标准：
- 可以从样例视频中抽出音频文件
- 异常信息可定位
- 测试通过

建议验证命令：
- pytest tests/integration/test_ffmpeg_adapter.py -v
```

### S2-07：补音频切块组件测试

```text
请执行阶段2任务 S2-07：补音频切块组件测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先固定音频切块行为，再补实现。

本次只做：
- 新增 tests/unit/test_segmenter.py
- 为固定时长切块写测试
- 为少量重叠切块写测试
- 明确切块结果要保留原始时间偏移

本次不要做：
- 不新增 infrastructure/media/segmenter.py 的实现
- 不接入 ASR

完成标准：
- 测试清楚表达每段起止时间和重叠关系

建议验证命令：
- pytest tests/unit/test_segmenter.py -v
```

### S2-08：实现音频切块组件

```text
请执行阶段2任务 S2-08：实现音频切块组件。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 为长音频识别提供分段能力。

本次只做：
- 新增 infrastructure/media/segmenter.py
- 必要时调整 tests/unit/test_segmenter.py
- 实现固定时长切块
- 实现少量重叠切块
- 输出每段的源时间范围

本次不要做：
- 不接入 ASR
- 不做字幕对齐
- 不改 TaskService

完成标准：
- 单元测试通过
- 切块逻辑纯粹，不依赖 UI 或用例层

建议验证命令：
- pytest tests/unit/test_segmenter.py -v
```

### S2-09：补 faster-whisper 适配器测试

```text
请执行阶段2任务 S2-09：补 faster-whisper 适配器测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先用测试固定 ASR 输出结构。

本次只做：
- 新增 tests/integration/test_faster_whisper_engine.py
- 写 ASR 集成测试
- 明确返回值是 SubtitleSegmentDTO 列表
- 断言至少包含文本和时间轴

本次不要做：
- 不实现 ASR 适配器
- 不接容器
- 不生成 SRT

完成标准：
- 测试能清楚表达当前缺少真实 ASR 实现

建议验证命令：
- pytest tests/integration/test_faster_whisper_engine.py -v
```

### S2-10：实现本地 ASR 适配器并接入容器

```text
请执行阶段2任务 S2-10：实现本地 ASR 适配器并接入容器。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 让项目能够真正调用本地 ASR。

本次只做：
- 新增 infrastructure/asr/__init__.py
- 新增 infrastructure/asr/faster_whisper_engine.py
- 修改 app/container.py
- 必要时调整 tests/integration/test_faster_whisper_engine.py
- 实现 faster-whisper 适配器
- 适配 AsrEngine 端口
- 在容器里完成依赖装配

本次不要做：
- 不做字幕去重
- 不生成 SRT
- 不串联完整流程

完成标准：
- ASR 测试通过
- 后续用例层可以直接拿到真实 AsrEngine

建议验证命令：
- pytest tests/integration/test_faster_whisper_engine.py -v
```

### S2-11：补字幕整理与 SRT 写出测试

```text
请执行阶段2任务 S2-11：补字幕整理与 SRT 写出测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先把字幕整理和 SRT 输出行为钉住。

本次只做：
- 新增 tests/unit/test_subtitle_formatter.py
- 新增 tests/unit/test_subtitle_aligner.py
- 新增 tests/unit/test_srt_writer.py
- 为基础去重写测试
- 为时间轴规整写测试
- 为 SRT 文本输出写测试

本次不要做：
- 不实现字幕组件
- 不改 TranscribeVideo

完成标准：
- 三组测试都能表达清楚输入和预期输出

建议验证命令：
- pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v
```

### S2-12：实现字幕后处理与 SRT 写出

```text
请执行阶段2任务 S2-12：实现字幕后处理与 SRT 写出。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 把原始 ASR 结果变成稳定可落盘的 SRT。

本次只做：
- 新增 infrastructure/subtitle/__init__.py
- 新增 infrastructure/subtitle/formatter.py
- 新增 infrastructure/subtitle/aligner.py
- 新增 infrastructure/subtitle/srt_writer.py
- 必要时调整对应测试文件
- 实现基础去重
- 实现时间轴规整
- 实现 SRT 写出

本次不要做：
- 不处理翻译字幕
- 不做 ASS
- 不做复杂字幕编辑逻辑

完成标准：
- 三组单元测试通过
- 可以从字幕片段稳定生成 SRT

建议验证命令：
- pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v
```

### S2-13：补端到端识别链路测试

```text
请执行阶段2任务 S2-13：补端到端识别链路测试。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 先把阶段2主链路用测试串起来。

本次只做：
- 新增 tests/integration/test_transcribe_video_flow.py
- 写“创建项目 -> 探测 -> 抽音频 -> ASR -> 生成原文字幕”的主链路测试
- 先允许测试失败

本次不要做：
- 不修改 core/usecases/transcribe_video.py
- 不改 TaskService

完成标准：
- 测试已能表达完整期望路径和产物

建议验证命令：
- pytest tests/integration/test_transcribe_video_flow.py -v
```

### S2-14：串联 TranscribeVideo 主流程

```text
请执行阶段2任务 S2-14：串联 TranscribeVideo 主流程。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 让 TranscribeVideo 真正成为阶段2的识别编排入口。

本次只做：
- 修改 core/usecases/transcribe_video.py
- 修改 core/services/task_service.py
- 修改 app/container.py
- 必要时调整 tests/integration/test_transcribe_video_flow.py
- 把探测、抽音频、ASR、字幕保存串进用例
- 保持 TaskService 只做入口转发和摘要更新

本次不要做：
- 不引入 UI 信号
- 不接 SQLite
- 不做翻译流程

完成标准：
- 端到端测试通过
- 任务检查点至少推进到 TRANSCRIBED

建议验证命令：
- pytest tests/integration/test_transcribe_video_flow.py -v
```

### S2-15：增加重复执行的基础复用能力

```text
请执行阶段2任务 S2-15：增加重复执行的基础复用能力。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 同一视频重复执行时，避免全量重算。

本次只做：
- 修改 core/usecases/transcribe_video.py
- 视实现需要修改 infrastructure/storage/workspace.py
- 必要时调整 tests/integration/test_transcribe_video_flow.py
- 增加最小缓存复用判断
- 优先复用已抽取音频或已有识别结果

本次不要做：
- 不设计完整缓存仓储
- 不引入数据库索引
- 不碰翻译和导出

完成标准：
- 重复执行时测试可以验证至少一层复用命中

建议验证命令：
- pytest tests/integration/test_transcribe_video_flow.py -v
```

### S2-16：做阶段2总验收

```text
请执行阶段2任务 S2-16：做阶段2总验收。

在执行前，请先使用通用前置提示词中要求的方式阅读 AGENTS.md 和相关设计文档。

本次任务目标：
- 对阶段2做一次完整收口，不再扩展新功能。

本次只做：
- 统一运行阶段2全部相关测试
- 检查当前实现是否仍然符合“只做本地识别链路”的阶段边界
- 如任务涉及 app/container.py，请按仓库约定补充桌面启动层面的说明性验收
- 如有必要，只补测试说明或文档，不再扩展实现范围

本次不要做：
- 不顺手开启阶段3
- 不新增翻译、导出、SQLite、UI 能力

完成标准：
- 可以明确回答下面四个问题：
  1. 是否能从本地视频生成原文 SRT
  2. 项目目录结构是否完整
  3. 重复执行是否有基础复用
  4. 是否没有混入翻译、导出、SQLite

建议验证命令：
- pytest tests/test_workspace.py tests/integration/test_ffprobe_adapter.py tests/integration/test_ffmpeg_adapter.py tests/unit/test_segmenter.py tests/integration/test_faster_whisper_engine.py tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py tests/integration/test_transcribe_video_flow.py -v
```

