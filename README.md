# StudyWise

一个辅助学习的桌面工具：上传 PDF（课件、论文等），主界面左右对照——**左侧是 PDF 原文，右侧是学习面板**，两侧页码一一对应。可以针对当前页向大模型提问，或让它围绕某个知识点快速生成小测验。

技术选型见 [技术栈.md](./技术栈.md)。

## 目录结构

```
StudyWise/
├── frontend/                  # React 19 + TypeScript + Vite
│   └── src/
│       ├── pages/             # 路由页面（HomePage 上传/列表，StudyPage 左右对照）
│       ├── components/
│       │   ├── layout/        # SplitView 左右布局
│       │   ├── pdf/           # 左侧 PDF 窗格
│       │   ├── study/         # 右侧学习面板
│       │   └── ui/            # shadcn/ui 组件（npx shadcn add <name>）
│       ├── stores/            # Zustand（当前页码等全局状态）
│       └── lib/               # API 封装、QueryClient、工具函数
├── backend/                   # Python 3.12 + FastAPI
│   ├── app/
│   │   ├── main.py            # 应用入口
│   │   ├── core/              # 配置（pydantic-settings）
│   │   ├── db.py              # SQLModel + SQLite
│   │   ├── models/            # Document、ImageAsset（图片元数据）
│   │   ├── api/routes/        # 文档、页面内容、LLM 流式对话接口
│   │   └── services/
│   │       └── llm/           # OpenAI / Anthropic 双风格适配层
│   ├── models.example.json    # 模型档案示例
│   └── data/                  # 本地数据（gitignore）：PDF、SQLite、模型密钥
└── 技术栈.md
```

## 本地开发

后端（默认 <http://127.0.0.1:8000>，接口文档在 `/docs`）：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload --reload-dir app
```

首次使用前创建统一的密钥配置和模型档案：

```powershell
cd backend
Copy-Item .env.example .env
New-Item -ItemType Directory -Force -Path data
Copy-Item models.example.json data\models.json
```

在 `backend/.env` 填写 `STUDYWISE_PADDLEOCR_API_TOKEN` 和所使用的
LLM 密钥。密钥只存放在 `.env`，不会进入模型档案或提交到版本库。

`backend/data/models.json` 只管理 `model_id`、`base_url` 和 API 风格：

- `openai`：OpenAI 及其兼容接口，例如 DeepSeek、通义、Kimi、Ollama、vLLM。
- `anthropic`：Anthropic Messages API 及其兼容接口。

上传后，后端把整份 PDF 提交给 PaddleOCR AI Studio Job API，轮询任务进度，
再将 JSONL 结果拆分为 Page 与 ImageAsset。后端不会使用其他 PDF 解析器。

前端（默认 <http://localhost:5173>，`/api` 已代理到后端）：

```powershell
cd frontend
npm install
npm run dev
```

## 核心 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST/GET | `/api/projects` | 创建或列出 Project |
| GET/PATCH | `/api/projects/{id}` | 查询或更新 Project 简介 |
| POST | `/api/projects/{id}/documents` | 向指定 Project 上传 PDF |
| POST | `/api/documents` | 上传 PDF，并加入异步 OCR 队列 |
| GET | `/api/documents` | 文档列表及解析状态 |
| GET/PATCH | `/api/documents/{id}` | 查询或更新 PDF 简介、目录 |
| GET | `/api/documents/{id}/file` | PDF 原文件（左侧窗格加载） |
| POST | `/api/documents/{id}/reparse` | 重新解析失败或已有文档 |
| GET | `/api/documents/{id}/pages` | PDF 的 Page 对象列表 |
| GET/PATCH | `/api/documents/{id}/pages/{n}` | 查询 Page 全文、图片 ID 或更新简介 |
| GET | `/api/documents/{id}/pages/{n}/text` | 第 n 页 OCR Markdown |
| GET | `/api/documents/{id}/pages/{n}/json` | 第 n 页结构化 OCR JSON |
| GET | `/api/documents/{id}/pages/{n}/images` | 第 n 页图片元数据 |
| GET | `/api/documents/{id}/pages/{n}/images/{index}` | 获取单张 OCR 图片 |
| GET | `/api/documents/{id}/pages/{n}/render` | PaddleOCR 返回的页面渲染图 |
| GET | `/api/images/{id}` | 按图片 ID 获取原图 |
| GET/PATCH | `/api/images/{id}/metadata` / `/api/images/{id}` | 查询或更新图片标签 |
| GET | `/api/models` | 可用模型档案（不返回密钥） |
| POST | `/api/documents/{id}/pages/{n}/chat` | 针对当前页进行 SSE 流式对话 |

对话接口根据请求中的模型档案选择 OpenAI 或 Anthropic Provider。两种 Provider
对上层暴露相同的流式文本接口，协议差异不会进入 API 或前端。

## 设计构想（Roadmap）

- [x] **LLM 对话**：双风格模型切换，针对当前页提问并流式返回 Markdown 回答
- [ ] **小测验**：针对某个知识点快速生成 quiz
- [ ] **图片打标**：大模型首次读到某页图片后打标——装饰性图片（循环图标、大脑图标之类）以后不再提取原图，只保留一句文字描述以节省 token；`ImageAsset` 已预留 `summary` / `is_useful` / `importance` / `retrieval_count` 元数据字段
- [ ] **get_useful_images 工具**：只返回当前页"有用"的图片
- [ ] **pdf.js 页码双向同步**：替换浏览器原生 iframe 查看器
- [ ] **Tauri 2.0 桌面壳**：uv sidecar 跑后端源码，发布时 PyInstaller 打包
