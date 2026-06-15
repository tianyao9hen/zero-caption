# Zero Caption 阶段 2 AI 单次执行任务清单

> 说明：本清单基于 `design/zero-caption_阶段2开发计划.md` 继续细化，目标是把阶段 2 拆成“单个 AI 一次只做一件小事”的执行颗粒度。  
> 约束来源：已读取仓库根目录 `AGENTS.md`，本清单默认继续遵守其中的分层、注释、测试和阶段边界要求。

**适用范围：**
- 只覆盖阶段 2：本地识别链路 MVP
- 只做 `导入视频 -> 探测元数据 -> 抽取音频 -> 本地 ASR -> 生成原文字幕`
- 不做翻译、不做导出、不做 SQLite 持久化、不做 UI 接入

**推荐使用方式：**
1. 按任务编号顺序执行
2. 每次只把一个任务交给 AI
3. 上一个任务未通过测试前，不要开始下一个任务
4. 每个任务结束后，先看测试结果，再决定是否进入下一项

---

## 一、执行总规则

### 1.1 单次任务必须满足的要求

1. 单次改动只聚焦一个明确边界。
2. 先补测试，再补实现，再回跑测试。
3. 不因为顺手就提前实现后续任务内容。
4. 注释、`docstring`、测试说明继续使用中文。
5. 业务编排留在 `core/`，基础设施细节留在 `infrastructure/`。

### 1.2 建议的 AI 提示词格式

每次派工时建议用下面这个模板：

```text
请执行阶段2任务 S2-XX。
严格只做该任务列出的范围，不要提前实现后续任务。
先读取 AGENTS.md，再阅读 design/zero-caption_阶段2开发计划.md 和 design/zero-caption_阶段2_AI单次执行任务清单.md。
先补测试，再实现，再运行文档里要求的测试。
如果遇到阻塞，请先说明阻塞点，不要擅自扩展范围。
```

---

## 二、任务总览

| 编号 | 任务名称 | 依赖 |
|---|---|---|
| S2-01 | 补工作区项目级目录测试 | 无 |
| S2-02 | 实现项目级目录结构创建 | S2-01 |
| S2-03 | 增加媒体探测结果模型与测试样例约定 | S2-02 |
| S2-04 | 实现 `ffprobe` 适配器 | S2-03 |
| S2-05 | 补抽音频适配器测试 | S2-04 |
| S2-06 | 实现 `FFmpeg` 抽音频能力 | S2-05 |
| S2-07 | 补音频切块组件测试 | S2-06 |
| S2-08 | 实现音频切块组件 | S2-07 |
| S2-09 | 补 `faster-whisper` 适配器测试 | S2-08 |
| S2-10 | 实现本地 ASR 适配器并接入容器 | S2-09 |
| S2-11 | 补字幕整理与 SRT 写出测试 | S2-10 |
| S2-12 | 实现字幕后处理与 SRT 写出 | S2-11 |
| S2-13 | 补端到端识别链路测试 | S2-12 |
| S2-14 | 串联 `TranscribeVideo` 主流程 | S2-13 |
| S2-15 | 增加重复执行的基础复用能力 | S2-14 |
| S2-16 | 做阶段 2 总验收 | S2-15 |

---

## 三、单次执行任务明细

### S2-01：补工作区项目级目录测试

**目标：** 先用测试把项目目录结构钉住。  
**建议修改文件：**
- 修改：`tests/test_workspace.py`

**本次只做：**
- 为项目级目录结构补测试
- 明确需要的子目录：`source/`、`temp/`、`cache/`、`subtitles/`、`exports/`、`logs/`

**本次不要做：**
- 不修改 `WorkspaceManager` 实现
- 不新增 `ffprobe`

**完成标准：**
- 新测试可以表达“当前应该失败，因为功能未实现”

**建议验证命令：**
- `pytest tests/test_workspace.py -v`

---

### S2-02：实现项目级目录结构创建

**目标：** 让工作区层具备创建项目级目录结构的能力。  
**建议修改文件：**
- 修改：`infrastructure/storage/workspace.py`
- 修改：`tests/test_workspace.py`

**本次只做：**
- 为 `WorkspaceManager` 增加项目级目录相关接口
- 让测试通过

**本次不要做：**
- 不处理媒体探测
- 不处理项目实体或仓储

**完成标准：**
- 指定项目目录后，可以稳定创建阶段 2 需要的全部子目录

**建议验证命令：**
- `pytest tests/test_workspace.py -v`

---

### S2-03：增加媒体探测结果模型与测试样例约定

**目标：** 先把“媒体探测输出长什么样”定清楚。  
**建议修改文件：**
- 新增：`core/dto/media_dto.py`
- 新增：`tests/fixtures/README.md`
- 新增：`tests/integration/test_ffprobe_adapter.py`

**本次只做：**
- 定义媒体基础信息 DTO
- 约定测试媒体样例需要覆盖的信息
- 写 `ffprobe` 适配器测试骨架

**本次不要做：**
- 不实现 `ffprobe` 适配器
- 不改 `TranscribeVideo`

**完成标准：**
- 测试清楚表达需要读取哪些字段，例如时长、分辨率、音轨信息

**建议验证命令：**
- `pytest tests/integration/test_ffprobe_adapter.py -v`

---

### S2-04：实现 `ffprobe` 适配器

**目标：** 真正读出媒体元数据。  
**建议修改文件：**
- 新增：`infrastructure/media/ffprobe.py`
- 新增或修改：`tests/integration/test_ffprobe_adapter.py`

**本次只做：**
- 实现 `ffprobe` 命令封装
- 返回结构化探测结果
- 保留命令、退出码和错误输出

**本次不要做：**
- 不实现抽音频
- 不写切块逻辑

**完成标准：**
- 集成测试通过
- 结果结构稳定，可供后续用例使用

**建议验证命令：**
- `pytest tests/integration/test_ffprobe_adapter.py -v`

---

### S2-05：补抽音频适配器测试

**目标：** 先把抽音频行为用测试固定下来。  
**建议修改文件：**
- 新增：`tests/integration/test_ffmpeg_adapter.py`

**本次只做：**
- 补充“视频转 `wav` 或 `flac`”的测试
- 明确输出路径和产物存在性断言

**本次不要做：**
- 不修改 `infrastructure/media/ffmpeg.py`

**完成标准：**
- 测试能够失败并明确指出当前适配器仍是占位实现

**建议验证命令：**
- `pytest tests/integration/test_ffmpeg_adapter.py -v`

---

### S2-06：实现 `FFmpeg` 抽音频能力

**目标：** 让 `FFmpegAdapter` 具备最小可用抽音频能力。  
**建议修改文件：**
- 修改：`infrastructure/media/ffmpeg.py`
- 修改：`tests/integration/test_ffmpeg_adapter.py`

**本次只做：**
- 实现抽音频命令拼装和执行
- 支持最少一种稳定输出格式，推荐 `wav`
- 让测试通过

**本次不要做：**
- 不实现烧录
- 不实现视频导出
- 不写切块

**完成标准：**
- 可以从样例视频中抽出音频文件
- 异常信息可定位

**建议验证命令：**
- `pytest tests/integration/test_ffmpeg_adapter.py -v`

---

### S2-07：补音频切块组件测试

**目标：** 先固定切块行为，再补实现。  
**建议修改文件：**
- 新增：`tests/unit/test_segmenter.py`

**本次只做：**
- 为固定时长切块写测试
- 为少量重叠切块写测试
- 明确切块结果要保留原始时间偏移

**本次不要做：**
- 不新增切块实现文件内容

**完成标准：**
- 测试表达清楚每段起止时间和重叠关系

**建议验证命令：**
- `pytest tests/unit/test_segmenter.py -v`

---

### S2-08：实现音频切块组件

**目标：** 为长音频识别提供分段能力。  
**建议修改文件：**
- 新增：`infrastructure/media/segmenter.py`
- 修改：`tests/unit/test_segmenter.py`

**本次只做：**
- 实现固定时长切块
- 实现少量重叠切块
- 输出每段的源时间范围

**本次不要做：**
- 不接入 ASR
- 不做字幕对齐

**完成标准：**
- 单元测试通过
- 切块逻辑纯粹，不依赖 UI 或用例层

**建议验证命令：**
- `pytest tests/unit/test_segmenter.py -v`

---

### S2-09：补 `faster-whisper` 适配器测试

**目标：** 先用测试固定 ASR 输出结构。  
**建议修改文件：**
- 新增：`tests/integration/test_faster_whisper_engine.py`

**本次只做：**
- 写 ASR 集成测试
- 明确返回值是 `SubtitleSegmentDTO` 列表
- 断言至少包含文本和时间轴

**本次不要做：**
- 不实现 ASR 适配器
- 不接容器

**完成标准：**
- 测试能清楚表达“当前缺少真实 ASR 实现”

**建议验证命令：**
- `pytest tests/integration/test_faster_whisper_engine.py -v`

---

### S2-10：实现本地 ASR 适配器并接入容器

**目标：** 让项目真正能调用本地 ASR。  
**建议修改文件：**
- 新增：`infrastructure/asr/__init__.py`
- 新增：`infrastructure/asr/faster_whisper_engine.py`
- 修改：`app/container.py`
- 修改：`tests/integration/test_faster_whisper_engine.py`

**本次只做：**
- 实现 `faster-whisper` 适配器
- 适配 `AsrEngine` 端口
- 在容器里完成依赖装配

**本次不要做：**
- 不做字幕去重
- 不生成 SRT
- 不串联完整流程

**完成标准：**
- ASR 测试通过
- 用例层后续可以直接拿到真实 `AsrEngine`

**建议验证命令：**
- `pytest tests/integration/test_faster_whisper_engine.py -v`

---

### S2-11：补字幕整理与 SRT 写出测试

**目标：** 先把字幕整理和输出行为钉住。  
**建议修改文件：**
- 新增：`tests/unit/test_subtitle_formatter.py`
- 新增：`tests/unit/test_subtitle_aligner.py`
- 新增：`tests/unit/test_srt_writer.py`

**本次只做：**
- 为基础去重写测试
- 为时间轴规整写测试
- 为 `SRT` 文本输出写测试

**本次不要做：**
- 不实现字幕组件

**完成标准：**
- 三组测试都能表达清楚输入和预期输出

**建议验证命令：**
- `pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v`

---

### S2-12：实现字幕后处理与 SRT 写出

**目标：** 把原始 ASR 结果变成稳定可落盘的 `SRT`。  
**建议修改文件：**
- 新增：`infrastructure/subtitle/__init__.py`
- 新增：`infrastructure/subtitle/formatter.py`
- 新增：`infrastructure/subtitle/aligner.py`
- 新增：`infrastructure/subtitle/srt_writer.py`
- 修改：对应测试文件

**本次只做：**
- 实现基础去重
- 实现时间轴规整
- 实现 `SRT` 写出

**本次不要做：**
- 不处理翻译字幕
- 不做 ASS
- 不做复杂字幕编辑逻辑

**完成标准：**
- 三组单元测试通过
- 可以从字幕片段稳定生成 `SRT`

**建议验证命令：**
- `pytest tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py -v`

---

### S2-13：补端到端识别链路测试

**目标：** 先把阶段 2 主链路用测试串起来。  
**建议修改文件：**
- 新增：`tests/integration/test_transcribe_video_flow.py`

**本次只做：**
- 写“创建项目 -> 探测 -> 抽音频 -> ASR -> 生成原文字幕”的主链路测试
- 先允许测试失败

**本次不要做：**
- 不修改 `TranscribeVideo` 实现

**完成标准：**
- 测试已能表达完整期望路径和产物

**建议验证命令：**
- `pytest tests/integration/test_transcribe_video_flow.py -v`

---

### S2-14：串联 `TranscribeVideo` 主流程

**目标：** 让 `TranscribeVideo` 真正成为阶段 2 的识别编排入口。  
**建议修改文件：**
- 修改：`core/usecases/transcribe_video.py`
- 修改：`core/services/task_service.py`
- 修改：`app/container.py`
- 修改：`tests/integration/test_transcribe_video_flow.py`

**本次只做：**
- 把探测、抽音频、ASR、字幕保存串进用例
- 保持 `TaskService` 只做入口转发和摘要更新

**本次不要做：**
- 不引入 UI 信号
- 不接 SQLite
- 不做翻译流程

**完成标准：**
- 端到端测试通过
- 任务检查点至少推进到 `TRANSCRIBED`

**建议验证命令：**
- `pytest tests/integration/test_transcribe_video_flow.py -v`

---

### S2-15：增加重复执行的基础复用能力

**目标：** 同一视频重复执行时，避免全量重算。  
**建议修改文件：**
- 修改：`core/usecases/transcribe_video.py`
- 视实现需要修改：`infrastructure/storage/workspace.py`
- 修改：`tests/integration/test_transcribe_video_flow.py`

**本次只做：**
- 增加最小缓存复用判断
- 优先复用已抽取音频或已有识别结果

**本次不要做：**
- 不设计完整缓存仓储
- 不引入数据库索引

**完成标准：**
- 重复执行时测试可以验证至少一层复用命中

**建议验证命令：**
- `pytest tests/integration/test_transcribe_video_flow.py -v`

---

### S2-16：做阶段 2 总验收

**目标：** 对阶段 2 做一次完整收口。  
**建议修改文件：**
- 如有必要，只补测试说明或文档，不再扩展实现范围

**本次只做：**
- 统一运行阶段 2 全部相关测试
- 检查是否仍然符合“只做本地识别链路”的阶段边界
- 如任务涉及 `app/container.py`，按仓库约定补桌面启动层面的说明性验收

**本次不要做：**
- 不顺手开启阶段 3

**完成标准：**
- 可以明确回答下面四个问题：
  1. 是否能从本地视频生成原文 `SRT`
  2. 项目目录结构是否完整
  3. 重复执行是否有基础复用
  4. 是否没有混入翻译、导出、SQLite

**建议验证命令：**
- `pytest tests/test_workspace.py tests/integration/test_ffprobe_adapter.py tests/integration/test_ffmpeg_adapter.py tests/unit/test_segmenter.py tests/integration/test_faster_whisper_engine.py tests/unit/test_subtitle_formatter.py tests/unit/test_subtitle_aligner.py tests/unit/test_srt_writer.py tests/integration/test_transcribe_video_flow.py -v`

---

## 四、阶段 2 完成口径

满足以下条件，即可认为阶段 2 完成：

1. 能从本地视频得到原文字幕文件。
2. 工作区内项目目录结构符合设计约定。
3. `TranscribeVideo` 已成为阶段 2 的主流程入口。
4. 基础设施职责没有跑进 `ui/` 或页面层。
5. 阶段边界保持干净，没有提前混入阶段 3、4、5 的内容。

