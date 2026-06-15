# Zero Caption 分阶段开发计划

> 本计划基于 `design/视频字幕生成与翻译软件_应用框架设计.md`、`design/推荐项目骨架说明.md` 与仓库根目录 `AGENTS.md` 制定。执行时默认遵守以下前提：继续沿用现有骨架、坚持分层边界、本地优先、云端只翻译字幕文本、优先打通 `导入 -> 识别 -> 翻译 -> 导出` 主链路。

**目标：** 在现有 `PySide6` 桌面骨架上，逐步完成一个可导入视频、执行本地语音识别、调用云端翻译、导出字幕或视频，并支持持久化、恢复与重试的 Windows 桌面工具。

**架构策略：**

1. 先完成核心链路，再补强持久化、恢复、重试与增强能力。
2. 先验证无界面的核心处理链，再接入桌面 UI，减少界面先行带来的返工。
3. 所有可替换能力先落 `core/ports/` 抽象，再在 `infrastructure/` 写实现。

**技术栈：** `PySide6`、`SQLite`、`FFmpeg/ffprobe`、`faster-whisper`、云端翻译 API、本地工作区目录、后台任务队列。

---

## 1. 计划约束与总体原则

### 1.1 必须始终满足的约束

1. 不推倒重来，优先扩展现有目录和类。
2. UI 只负责交互和展示，不直接访问 `FFmpeg`、数据库或翻译 API。
3. 核心流程尽量放在 `core/usecases/` 与 `core/services/task_service.py` 的编排层。
4. 所有任务都要围绕“可持久化、可恢复、可重试”设计，即使第一版只先落最小能力。
5. 原始视频、音频和项目目录不上传云端；云端只接收字幕文本和必要上下文。
6. 新增公共接口、服务、适配器与测试时，注释和 `docstring` 继续使用中文。

### 1.2 推荐实施顺序

1. 先做环境与依赖探针，确认工具链可用。
2. 再稳定领域模型、端口和主流程用例。
3. 然后完成无界面的 MVP 主链路。
4. 再把主链路接入桌面界面。
5. 最后补齐持久化任务队列、恢复、增强导出与发布。

### 1.3 里程碑总览

| 阶段 | 目标 | 结果 |
|---|---|---|
| 阶段 0 | 基线与依赖准备 | 能检查运行环境，配置和目录约定稳定 |
| 阶段 1 | 领域模型与端口定型 | 主链路的实体、DTO、端口、用例骨架稳定 |
| 阶段 2 | 本地识别链路 MVP | 能从单个视频生成原文字幕 |
| 阶段 3 | 翻译与导出 MVP | 能生成翻译字幕并导出外挂字幕结果 |
| 阶段 4 | UI 接入 MVP | 用户可在桌面界面发起主链路并查看状态 |
| 阶段 5 | SQLite 与恢复能力 | 任务可持久化、可重启恢复、可重试 |
| 阶段 6 | 增强导出与稳定性 | 支持烧录、长视频、日志与诊断 |
| 阶段 7 | 打包发布与验收 | 形成可发布的 Windows 桌面版本 |
| 阶段 8 | 增强路线 | 批量、多引擎、双语字幕等扩展能力 |

---

## 2. 阶段 0：基线与依赖准备

### 2.1 目标

把“能不能开发、能不能跑、跑起来依赖什么”先收敛清楚，避免后续实现过程中不断返工配置。

### 2.2 重点文件

- 修改：`config/default.toml`
- 修改：`config/settings.py`
- 修改：`app/bootstrap.py`
- 新增：`config/profiles/cpu.toml`
- 新增：`config/profiles/gpu.toml`
- 新增：`scripts/check_runtime.py`
- 新增：`tests/integration/test_runtime_probe.py`
- 新增：`tests/fixtures/README.md`

### 2.3 任务拆解

1. 明确运行时依赖清单：`FFmpeg`、`ffprobe`、`faster-whisper`、翻译 API 配置、模型缓存目录。
2. 为配置层补充最小必需项：ASR 引擎名、翻译引擎名、导出模式默认值、语言、并发数、重试次数、缓存策略。
3. 提供 CPU/GPU 配置模板，让后续 ASR 与导出阶段可根据配置切换。
4. 编写运行时探针脚本，启动前检查外部程序、模型目录和关键配置是否完整。
5. 为测试准备规范化样例说明，明确短视频、长视频、纯语音、噪声视频各自的用途。

### 2.4 完成标准

1. 新开发者拿到仓库后，能用统一脚本确认依赖是否满足。
2. 配置层已经能表达后续 MVP 需要的核心参数，不再只保留空字符串占位。
3. 样例素材标准清晰，后续测试不会临时拼凑。

---

## 3. 阶段 1：领域模型、端口与用例骨架定型

### 3.1 目标

把主链路涉及的业务对象、状态机和抽象端口先稳定下来，为后续真实实现提供统一协议。

### 3.2 重点文件

- 修改：`core/domain/entities.py`
- 修改：`core/domain/enums.py`
- 修改：`core/dto/app_state.py`
- 修改：`core/ports/asr.py`
- 修改：`core/ports/translator.py`
- 修改：`core/ports/exporter.py`
- 修改：`core/ports/repository.py`
- 修改：`core/services/task_service.py`
- 新增：`core/dto/project_dto.py`
- 新增：`core/dto/subtitle_dto.py`
- 新增：`core/dto/task_dto.py`
- 新增：`core/usecases/create_project.py`
- 新增：`core/usecases/transcribe_video.py`
- 新增：`core/usecases/translate_subtitles.py`
- 新增：`core/usecases/export_video.py`
- 新增：`tests/unit/test_entities.py`
- 新增：`tests/unit/test_usecase_contracts.py`

### 3.3 任务拆解

1. 扩展 `Project`、`Task` 实体，补上文件指纹、语言、当前步骤、重试次数、错误信息、项目目录等字段。
2. 为字幕片段、翻译片段、导出请求、检查点状态定义 DTO，避免后续在 UI 与基础设施之间传裸字典。
3. 细化 `TaskStatus` 与 `ProjectStatus`，保留现有语义并补充恢复场景需要的状态。
4. 升级端口定义，使其能表达批量字幕翻译、导出模式、媒体探测、仓储读写、任务事件发布等能力。
5. 新建四个核心用例骨架，并让 `TaskService` 变成这些用例的编排入口，而不是停留在只返回摘要字符串。
6. 明确检查点语义：已导入、已抽音频、已识别、已翻译、已合成、已导出。

### 3.4 完成标准

1. 所有主链路输入输出都能在 `core/` 层用明确类型表达。
2. 后续任意适配器接入前，都已经知道自己要实现哪个端口。
3. `TaskService` 已经成为 UI 唯一调用的核心流程入口。

---

## 4. 阶段 2：本地识别链路 MVP

### 4.1 目标

在不依赖桌面界面的前提下，完成“导入视频 -> 探测元数据 -> 抽取音频 -> 本地 ASR -> 生成原文字幕”的最小闭环。

### 4.2 重点文件

- 修改：`app/container.py`
- 修改：`infrastructure/media/ffmpeg.py`
- 修改：`infrastructure/storage/workspace.py`
- 修改：`core/services/task_service.py`
- 新增：`infrastructure/media/ffprobe.py`
- 新增：`infrastructure/media/segmenter.py`
- 新增：`infrastructure/asr/__init__.py`
- 新增：`infrastructure/asr/faster_whisper_engine.py`
- 新增：`infrastructure/subtitle/__init__.py`
- 新增：`infrastructure/subtitle/formatter.py`
- 新增：`infrastructure/subtitle/aligner.py`
- 新增：`infrastructure/subtitle/srt_writer.py`
- 新增：`tests/unit/test_subtitle_formatter.py`
- 新增：`tests/integration/test_ffmpeg_adapter.py`
- 新增：`tests/integration/test_transcribe_video_flow.py`

### 4.3 任务拆解

1. 在工作区层补齐项目级目录创建能力：`source/`、`temp/`、`cache/`、`subtitles/`、`exports/`、`logs/`。
2. 实现 `ffprobe` 适配器，读取时长、分辨率、音轨信息，为后续缓存和导出提供依据。
3. 实现 `FFmpeg` 抽音频适配器，支持输出 `wav` 或 `flac`，并保留命令、退出码与错误输出。
4. 实现音频切块组件，支持固定时长切块和少量重叠，为长视频识别做准备。
5. 实现 `faster-whisper` 适配器，输出带时间轴的原始分段结果。
6. 实现字幕后处理组件，完成基础的去重、断句、时间轴规整和 SRT 生成。
7. 落地 `CreateProject` 与 `TranscribeVideo` 用例，支持文件指纹、缓存命中和项目目录写入。
8. 通过服务层或脚本入口运行单视频识别流程，不依赖 UI 也能完成端到端验证。

### 4.4 完成标准

1. 给定一个本地视频，系统可以生成原文 `SRT` 字幕。
2. 项目目录结构完整，原始视频、临时音频、缓存结果、字幕产物各归其位。
3. 同一视频重复执行时，至少能复用已抽取音频或已完成的识别结果。

---

## 5. 阶段 3：翻译与导出 MVP

### 5.1 目标

把“原文字幕 -> 云端翻译 -> 目标字幕 -> 外挂字幕导出”接上，使 MVP 真正跑通到用户可交付结果。

### 5.2 重点文件

- 修改：`config/default.toml`
- 修改：`app/container.py`
- 修改：`core/services/task_service.py`
- 修改：`core/ports/translator.py`
- 修改：`core/ports/exporter.py`
- 修改：`infrastructure/translation/base.py`
- 新增：`infrastructure/translation/openai_translator.py`
- 新增：`infrastructure/translation/batch_builder.py`
- 新增：`infrastructure/export/__init__.py`
- 新增：`infrastructure/export/soft_subtitle_exporter.py`
- 新增：`core/usecases/translate_subtitles.py`
- 新增：`core/usecases/export_video.py`
- 新增：`tests/unit/test_translation_batch_builder.py`
- 新增：`tests/integration/test_translate_subtitles_flow.py`
- 新增：`tests/integration/test_soft_export_flow.py`

### 5.3 任务拆解

1. 定义翻译请求结构，确保只发送字幕文本、源语言、目标语言和必要上下文。
2. 实现批量翻译构造器，按字幕条或小批次请求，处理限流、上下文拼接与响应回填。
3. 实现云端翻译适配器，统一处理认证、超时、重试、错误分类和摘要日志。
4. 生成翻译后的字幕版本，并保存在项目级 `subtitles/` 目录。
5. 实现外挂字幕导出器，至少支持“复制视频 + 输出字幕文件”与“生成导出记录”两种结果。
6. 把 `TranslateSubtitles`、`ExportVideo` 串入 `TaskService` 主流程，形成完整 MVP 工作流。

### 5.4 完成标准

1. 用户输入源视频和目标语言后，可以得到原文字幕、译文字幕和导出记录。
2. 云端翻译日志不会泄露密钥，也不会上传视频或音频。
3. 主链路第一次真正达到“导入 -> 识别 -> 翻译 -> 导出”。

---

## 6. 阶段 4：桌面 UI 接入 MVP

### 6.1 目标

把已经可用的主链路接入现有 `PySide6` 骨架，让用户可以在界面中完成单项目工作流。

### 6.2 重点文件

- 修改：`ui/windows/main_window.py`
- 修改：`ui/dialogs/import_dialog.py`
- 修改：`ui/pages/projects_page.py`
- 修改：`ui/pages/tasks_page.py`
- 修改：`ui/pages/settings_page.py`
- 修改：`ui/widgets/status_bar.py`
- 修改：`ui/widgets/navigation.py`
- 修改：`core/dto/app_state.py`
- 修改：`core/services/task_service.py`
- 新增：`ui/viewmodels/__init__.py`
- 新增：`ui/viewmodels/project_view_model.py`
- 新增：`ui/viewmodels/task_view_model.py`
- 新增：`tests/integration/test_main_window_smoke.py`

### 6.3 任务拆解

1. 让导入对话框真正收集视频路径、源语言、目标语言和导出模式，而不再只是占位弹窗。
2. 项目页显示项目列表、当前状态、源文件、输出目录和最近任务。
3. 任务页显示总进度、当前步骤、当前块进度、错误摘要与重试入口。
4. 设置页承载引擎选择、API 配置、语言默认值、CPU/GPU 配置和缓存策略。
5. 通过信号/槽或进度总线把后台状态推送到页面层，避免 UI 直接轮询基础设施。
6. 状态栏显示当前任务摘要、最后一次错误和工作区位置。

### 6.4 完成标准

1. 用户能通过桌面界面完成单个视频的导入、识别、翻译和导出。
2. 界面线程不会因耗时任务卡死。
3. 页面层没有直接 new `FFmpeg`、翻译器或数据库连接。

---

## 7. 阶段 5：SQLite 持久化、恢复与重试

### 7.1 目标

把当前基于内存的占位任务系统升级成真正可恢复的桌面任务系统，这是软件从“能跑”走向“可长期使用”的关键阶段。

### 7.2 重点文件

- 修改：`app/container.py`
- 修改：`core/services/task_service.py`
- 修改：`infrastructure/task/job_queue.py`
- 修改：`core/ports/repository.py`
- 新增：`infrastructure/storage/sqlite_db.py`
- 新增：`infrastructure/storage/project_repository.py`
- 新增：`infrastructure/storage/task_repository.py`
- 新增：`infrastructure/storage/subtitle_repository.py`
- 新增：`infrastructure/storage/export_repository.py`
- 新增：`infrastructure/storage/cache_repository.py`
- 新增：`infrastructure/task/worker.py`
- 新增：`infrastructure/task/progress_bus.py`
- 新增：`infrastructure/task/retry.py`
- 新增：`tests/integration/test_sqlite_repositories.py`
- 新增：`tests/integration/test_persistent_job_queue.py`
- 新增：`tests/integration/test_resume_flow.py`

### 7.3 任务拆解

1. 设计 SQLite 表结构：项目、任务、字幕版本、导出记录、缓存索引、应用设置。
2. 把 `JobQueue` 从内存 `deque` 升级为“数据库记录 + worker 执行器”的持久化队列。
3. 为任务状态机加入检查点与重试计数，让失败任务具备清晰恢复策略。
4. 启动时扫描未完成任务，根据最后成功步骤决定续跑位置。
5. 为翻译失败、`FFmpeg` 失败、ASR 失败设计差异化重试策略和指数退避。
6. 保证状态先写库，再通知 UI，防止界面显示与真实状态不一致。

### 7.4 完成标准

1. 应用重启后可以看到历史项目和未完成任务。
2. 崩溃或中断后，系统能从最后成功检查点继续。
3. 内存队列不再是唯一真实状态来源。

---

## 8. 阶段 6：增强导出、长视频稳定性与诊断

### 8.1 目标

补齐设计文档中对长视频、烧录字幕、日志追踪和稳定性的要求，让软件具备真实生产可用性。

### 8.2 重点文件

- 修改：`infrastructure/media/segmenter.py`
- 修改：`infrastructure/subtitle/aligner.py`
- 修改：`core/services/task_service.py`
- 修改：`ui/pages/tasks_page.py`
- 新增：`infrastructure/subtitle/ass_writer.py`
- 新增：`infrastructure/export/burn_in_exporter.py`
- 新增：`infrastructure/logging/project_logger.py`
- 新增：`infrastructure/logging/diagnostic_bundle.py`
- 新增：`tests/integration/test_long_video_chunking.py`
- 新增：`tests/integration/test_burn_in_export.py`
- 新增：`tests/integration/test_retry_and_cleanup.py`

### 8.3 任务拆解

1. 增加 `ASS` 样式写出能力，为烧录和后续样式扩展做准备。
2. 实现烧录导出器，支持把字幕硬编码进视频。
3. 优化长视频切块、重叠回填和全局时间轴校正，降低句子截断与错位。
4. 引入三层进度显示：总任务、当前步骤、当前块。
5. 增加项目级日志与诊断包导出能力，方便问题排查。
6. 设计延迟清理和手动清理策略，避免误删仍可复用的中间产物。

### 8.4 完成标准

1. 用户可在外挂字幕和烧录字幕之间选择。
2. 2 小时级别长视频仍能以分段方式运行，而不是一次性占满内存。
3. 出错时可以定位到具体步骤、命令和日志文件。

---

## 9. 阶段 7：打包发布与最终验收

### 9.1 目标

让软件从开发状态走到“可安装、可分发、可验证”的 Windows 桌面版本。

### 9.2 重点文件

- 修改：`app/main.py`
- 修改：`config/default.toml`
- 新增：`scripts/build_windows.ps1`
- 新增：`scripts/smoke_test.ps1`
- 新增：`docs/release_checklist.md`
- 新增：`docs/user_guide.md`
- 新增：`tests/integration/test_packaged_startup.py`

### 9.3 任务拆解

1. 确定打包方案，优先在 `PyInstaller` 与 `Nuitka` 中选择一种并固定流程。
2. 处理 `FFmpeg`、模型缓存、配置文件和图标资源的打包路径问题。
3. 提供 Windows 下的一键构建脚本和烟雾测试脚本。
4. 完成安装包或便携版的启动验证、主链路回归验证和异常恢复验证。
5. 补齐用户文档：环境要求、导入流程、翻译配置、导出说明、常见故障排查。

### 9.4 完成标准

1. 非开发环境机器上可以安装或直接启动应用。
2. 首次启动能正确创建工作区与日志目录。
3. 发布前有一套固定的回归清单可重复执行。

---

## 10. 阶段 8：增强路线图

这一阶段不阻塞 MVP 发布，但适合作为后续版本迭代池。

### 10.1 优先级较高的增强项

1. 批量导入与批量任务编排。
2. 多翻译引擎和多 ASR 引擎切换。
3. GPU/CPU 自动探测与配置推荐。
4. 双语字幕输出。
5. 更细的项目历史与字幕版本比较。

### 10.2 明确延后事项

1. 复杂字幕编辑器。
2. 在线协作。
3. 插件市场化。
4. Web 前后端分离改造。

---

## 11. 推荐开发批次与依赖关系

为了降低返工，建议严格按下面的批次推进：

1. **批次 A：阶段 0 + 阶段 1**  
   先把配置、实体、端口、用例骨架做稳。

2. **批次 B：阶段 2 + 阶段 3**  
   先在无界面状态下打通主链路，确认识别、翻译、导出三件事都可用。

3. **批次 C：阶段 4**  
   把已经验证过的能力接入 UI，而不是在 UI 里边写边猜。

4. **批次 D：阶段 5**  
   升级为可恢复、可重试、可持久化的任务系统。

5. **批次 E：阶段 6 + 阶段 7**  
   做稳定性、增强导出、诊断和发布交付。

6. **批次 F：阶段 8**  
   进入版本迭代和扩展功能阶段。

---

## 12. 每阶段都要执行的测试策略

### 12.1 单元测试

优先覆盖 `core/` 的纯业务逻辑：

1. 状态迁移是否合法。
2. DTO 与实体转换是否稳定。
3. 字幕分段、时间轴格式化、缓存命中规则是否正确。

### 12.2 集成测试

优先覆盖 `infrastructure/` 适配器：

1. `FFmpeg` / `ffprobe` 调用是否能返回结构化结果。
2. `faster-whisper` 适配器是否能在样例媒体上输出时间轴。
3. 翻译适配器是否能处理重试、限流和错误回填。
4. SQLite 仓储与任务队列是否能恢复状态。

### 12.3 UI 烟雾测试

1. 主窗口是否能启动。
2. 导入对话框是否能提交参数。
3. 任务状态是否会及时刷新。
4. 异常情况下界面是否能显示日志和错误提示。

### 12.4 回归重点

每次进入新阶段前后，都至少回归以下场景：

1. 单个短视频完整链路。
2. 重复导入同一视频的缓存复用。
3. 翻译失败后的重试。
4. 应用重启后的任务恢复。
5. 外挂字幕与烧录字幕两种导出模式。

---

## 13. 建议的阶段验收口径

### MVP 可对外试用的最低标准

满足以下条件即可视为第一版可试用：

1. 阶段 0 到阶段 5 已完成。
2. 单文件工作流可稳定跑通。
3. 任务状态可持久化，应用重启后可恢复。
4. 默认导出外挂字幕，烧录可暂时作为后续增强项。

### 正式发布前的最低标准

满足以下条件再进入公开发布：

1. 阶段 6 与阶段 7 已完成。
2. 长视频、失败恢复、日志追踪已验证。
3. 打包流程与回归清单固定。
4. 用户文档可支持非开发者完成安装和基本使用。

---

## 14. 一句话执行顺序

先把 `core` 与 `infrastructure` 中的无界面主链路做通，再把它接进 `PySide6`，随后补齐 `SQLite` 持久化任务系统、恢复机制和增强导出，最后再进入打包发布与扩展能力阶段。
