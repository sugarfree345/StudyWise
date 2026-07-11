# StudyWise 后端逻辑总览

一个「PDF 学习助手」的后端：上传 PDF → 远程 PaddleOCR 解析成分页 Markdown + 图片 →
前端左看 PDF、右与大模型对话，模型通过一组工具按需读取页面正文与图片。

技术栈：**FastAPI + SQLModel(SQLite) + 异步后台队列**；LLM 走 OpenAI / Anthropic 两种风格适配。

---

## 1. 应用启动与配置

- **`app/main.py`** — FastAPI 入口。`lifespan` 启动时：建表 + 轻量迁移、检查模型档案与 PaddleOCR 配置、
  启动后台解析队列；退出时优雅停队列。挂载 `/api` 路由，配置 CORS（Vite 5173 / Tauri 1420）。
  额外提供 `GET /api/health`（报告各项密钥是否已配置）。
- **`app/core/config.py`** — `Settings`（pydantic-settings），从 `backend/.env` 读取，前缀 `STUDYWISE_`。
  含数据目录、PaddleOCR 参数、各家 API key、CORS。派生出 `upload_dir` / `parsed_dir` / `database_url`（SQLite）。
- **`app/db.py`** — SQLite 引擎、`create_db_and_tables()`、`get_session()`（FastAPI 依赖，`yield` 会话）。
- **`app/db_migrations.py`** — 手写 SQLite 迁移（`appmeta.schema_version`）。把早期库升级到 Project/Page 模型，
  给 document/imageasset 补列、建默认项目、重置历史解析产物。模型稳定后可换 Alembic。

## 2. 数据模型（`app/models/document.py`）

| 模型 | 作用 | 关键字段 |
|---|---|---|
| `Project` | 一组学习资料 | name, summary |
| `Document` | 一份 PDF | filename, stored_path, page_count, summary, table_of_contents |
| `DocumentProcessing` | OCR 任务状态（与 Document 分表以兼容旧库） | status(pending/processing/ready/failed), processed_pages, paddle_job_id, error_message |
| `DocumentPage` | 一页解析结果 | page_number, text, **markdown**, raw_json, render_path |
| `ImageAsset` | 页内图片元数据 | page_number, image_index, stored_path, mime_type, **summary / is_useful / importance / retrieval_count** |

图片约定：大模型第一次读到某图后为它打标；`is_useful=False`（装饰性）之后不再提取原图，只用一句 summary 代替，省 token。

## 3. 文档解析流水线（异步后台队列）

- **`app/services/document_processing.py`** — `DocumentProcessingManager`：单 worker 串行队列。
  - 上传/重解析时 `enqueue(document_id)`；worker 用 `asyncio.to_thread` 跑阻塞解析。
  - 启动时 `_recover_jobs()` 把上次中断（status=processing）的任务恢复为 pending 重跑。
  - `_process_document`：置 processing → 提交 PaddleOCR 拿 job_id → 轮询状态（`_wait_for_result`，
    期间回写 page_count/processed_pages）→ 拉取分页结果 → `_replace_document_content` 落库 → 置 ready。
    支持 `ProcessingInterrupted`（停机）与失败（记 error_message）。
  - `_replace_document_content`：重置文件存储、逐页写 DocumentPage/ImageAsset、下载图片与整页渲染图、
    重写 Markdown 里的图片相对路径、清理本次不再出现的旧页/旧图。
- **`app/services/document_parser.py`** — 稳定边界：`DocumentParser` Protocol + 一堆冻结 dataclass
  （`ParseJobStatus/RemotePage/RemoteFile/StoredPage/StoredImage`）+ `image_filename()` 命名规则。
- **`app/services/paddleocr_service.py`** — `DocumentParser` 的远程 PaddleOCR 实现（submit/get_status/iter_pages/download）。
- **`app/services/page_content_store.py`** — 解析产物的文件存储层：`data/parsed/{doc}/{pages,images,renders}/`。
  原子写、按页读 `.md`/`.json`、图片/渲染图路径（含防路径穿越）。

## 4. HTTP API（`app/api/`）

`router.py` 汇总以下路由，统一挂 `/api`：

- **`routes/projects.py`** — 项目 CRUD；`GET/POST /projects/{id}/documents` 列出/上传项目下文档。
- **`routes/documents.py`** — 文档：`POST /documents` 上传（校验 PDF、落盘、建记录、入队解析）、
  列表/详情/`PATCH`、`POST /{id}/reparse` 重解析、`GET /{id}/file` 原文件（inline）。
- **`routes/pages.py`** — 页：列表/详情/`PATCH summary`、`/text`、`/json`、`/images`（可按 useful 过滤）、
  单图、`/render` 整页渲染图。
- **`routes/images.py`** — 图片：元数据、`PATCH`、`GET /images/{id}` 取原图（累加 retrieval_count）。
- **`routes/chat.py`** — LLM 对话（详见下节）。

**查询服务 `app/services/study_content_service.py`** 是 HTTP 与 LLM 工具**共用**的数据访问层：
`get_project/document/page_content`、`list_page_images`、`get_pages_markdown`（页码区间 Markdown）、
`get_useful_images`、`read_image_bytes`（取原图字节 + 累加检索、按扩展名纠正 MIME）、
`classify_image`（写入判定）、`get_page_render_path`、`guess_image_mime`。

## 5. LLM 对话与工具（核心）

### 5.1 Provider 适配（`app/services/llm/`）

- **`base.py`** — `LLMProvider` Protocol：`stream_chat(system, messages, tools=None, tool_runner=None)`，
  流式返回**纯文本增量**。定义 `ToolRunner` 回调类型与 `MAX_TOOL_ROUNDS=8`（防工具死循环）。
- **`profiles.py`** — `ModelProfile`（name/style/model_id/base_url/max_tokens…），从 `data/models.json` 读，
  api_key 由 `.env` 按 credential 注入，不入档案。`PublicProfile` 供前端（不含 key）。
- **`factory.py`** — 按 `style` 选 Provider。
- **`openai_provider.py` / `anthropic_provider.py`** — 两种风格，内部各自跑
  **「模型 → 工具 → 模型」多轮循环**，把工具结果（含图片）按各自 API 格式回喂，最终只吐面向用户的文本，
  所以上层 SSE 无需感知工具。要点：
  - Anthropic：`system` 顶层参数；工具结果用 `tool_result` 块，图片走 base64 `image` 块。
  - OpenAI：`system` 是首条消息；工具结果用 `role=tool` 消息；**图片塞不进 tool 消息，改用随后一条
    `user` 消息的 `image_url`（data URL）承载**。GPT-5/o 系列按模型名前缀自动改用 `max_completion_tokens`
    （DeepSeek/Qwen/gpt-4.x 仍用 `max_tokens`）。

### 5.2 工具层（`app/services/llm/tools/` 包）

Provider 无关，可扩展：`@register(name, description, parameters)` 装饰 `(ctx, args) -> ToolResult` 即注册。

- **`base.py`** — 注册表 + `ToolContext`(session/document_id/current_page) + `ToolResult`/`ToolImage` +
  `run_tool()`（未知工具/缺参数/参数错误/数据未找到分门别类转成 error 结果，让模型自我纠正而非中断）+
  `tool_specs()` / `openai_tools()` / `anthropic_tools()` 两种风格转换。
- **`page_image.py`** — 7 个工具：
  | 工具 | 作用 |
  |---|---|
  | `get_full_pdf_text()` | 取整份 PDF 全文（每页带页码）；仅在对文档一无所知、需先建立整体了解时用（如首轮空上下文） |
  | `get_text(first_page, last_page)` | 取页码区间 Markdown（**最常用**取文工具，单页首尾填同值） |
  | `get_page_content(page_number)` | 某页 Markdown + 图片元数据 |
  | `get_image(image_id)` | 取原图；已判定装饰性(is_useful=false)则只回简介 |
  | `get_useful_images(page_number)` | 该页有用图片元数据 |
  | `get_page_render(page_number)` | 整页渲染大图 |
  | `classify_image(id, is_useful, summary, importance)` | 写入图片首次判定 |

### 5.3 对话接口（`app/api/routes/chat.py`）

- `GET /models` — 列出可用模型档案（不含 key）。
- `POST /documents/{id}/pages/{n}/chat` — 旧的**单页**对话（把该页 Markdown 注入 system，无工具）。
- `POST /documents/{id}/chat?page=N` — **当前主用**的整册共享对话：
  - **轻量导航式 system**：`_build_document_system` **不再注入全文、也不列工具清单**（工具的 schema 走
    API 的 `tools` 参数），只给「书名 / 总页数 / 当前第 N 页 / 行为约定 / 目录或摘要」（约数百字）。
    正文完全由模型按需用 `get_full_pdf_text`/`get_text`/`get_image` 等工具自取，
    大幅省 token，也让对话不必每轮携带整册内容。
  - **无状态**：前端每次带全量对话历史 `messages`。
  - 走 **SSE** 流式返回 `delta`/`usage`/`done`/`error` 事件（`usage` 携带本次提问累计 token，
    多轮工具调用会累加）；provider 出错以流内 error 事件收尾，不中途 500。
  - `_sse` 在流式期间**单独开一个 `Session(engine)`** 供工具执行读写，
    因为请求级 Depends 会话在响应体流式输出阶段不保证仍可用。

## 6. 测试（`backend/tests/`，标准库 unittest）

- `test_llm_tools.py` — 工具层：内存 SQLite + 临时图片，覆盖 6 个工具正常路径、装饰图简介代替原图、
  `get_text` 单页/越界、错误分类、注册表与两种风格转换。
- `test_llm.py` — Provider：工厂选型、档案加载、system 位置，以及 `ToolLoopTests` 用 mock 证明
  两种 provider 的「模型→工具→模型」往返闭环。
- `test_document_parsing.py` — 解析流水线与文件存储。

运行：`uv run python -m unittest discover -s tests`。

## 7. 端到端已验证

真实 gpt-5.5 跑通：轻量 system（~445 字）下，问「当前这一页讲什么」→ 模型自行 `get_text(3,3)` 取第 3 页作答；
让它逐张看并分类某页图片 → `get_image`+`classify_image` 结果正确落库（含把 UNSW 校徽判为装饰图）。
HTTP/SSE 端点亦验证：流式正常、工具真实触发、DB 副作用（retrieval_count/分类）符合预期。
