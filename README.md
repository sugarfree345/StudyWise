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
│   │   ├── api/routes/        # documents（上传/列表/取文件）、pages（逐页取内容）
│   │   └── services/          # pdf_service：页文字 / 页图片 / 整页渲染
│   └── data/                  # 本地数据（gitignore）：上传的 PDF、SQLite
└── 技术栈.md
```

## 本地开发

后端（默认 <http://127.0.0.1:8000>，接口文档在 `/docs`）：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

前端（默认 <http://localhost:5173>，`/api` 已代理到后端）：

```powershell
cd frontend
npm install
npm run dev
```

## 核心 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/documents` | 上传 PDF |
| GET | `/api/documents` | 文档列表 |
| GET | `/api/documents/{id}/file` | PDF 原文件（左侧窗格加载） |
| GET | `/api/documents/{id}/pages/{n}/text` | 第 n 页文字 |
| GET | `/api/documents/{id}/pages/{n}/images` | 第 n 页内嵌图片 |
| GET | `/api/documents/{id}/pages/{n}/render` | 第 n 页整页渲染成 PNG |

`pages` 系列接口对应 `backend/app/services/pdf_service.py` 里的三个工具函数，后续将作为 tools 暴露给大模型。

## 设计构想（Roadmap）

- [ ] **LLM 对话**：针对当前页提问，流式返回 Markdown 回答
- [ ] **小测验**：针对某个知识点快速生成 quiz
- [ ] **图片打标**：大模型首次读到某页图片后打标——装饰性图片（循环图标、大脑图标之类）以后不再提取原图，只保留一句文字描述以节省 token；`ImageAsset` 已预留 `summary` / `is_useful` / `importance` / `retrieval_count` 元数据字段
- [ ] **get_useful_images 工具**：只返回当前页"有用"的图片
- [ ] **pdf.js 页码双向同步**：替换浏览器原生 iframe 查看器
- [ ] **Tauri 2.0 桌面壳**：uv sidecar 跑后端源码，发布时 PyInstaller 打包
