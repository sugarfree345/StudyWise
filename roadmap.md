# StudyWise Roadmap

## PDF 理解与图片工具

1. [x] 使用 React-PDF 替换浏览器原生 iframe 阅读器
   - 使用 PDF.js 渲染页面
   - 保持当前页与右侧学习面板同步
   - 为后续文字层、元素坐标和高亮交互提供基础

2. [x] 增加文档异步解析状态
   - 上传后记录 `pending / processing / ready / failed`
   - 展示总页数、已处理页数和失败原因
   - OCR 处理不阻塞上传请求

3. [x] 接入 PaddleOCR AI Studio 整文件 Job API
   - 整份 PDF 直接提交 PaddleOCR，不使用其他 PDF 解析器
   - 轮询远程任务状态并下载 JSONL 结果
   - 建立 Project → Document → DocumentPage → ImageAsset 数据模型
   - 每页保存简介、全文、Markdown、原始 JSON 与图片 ID 列表
   - 单独下载页面图片和渲染图，并通过稳定数据库 ID 查询
   - PaddleOCR 与 LLM 密钥统一由 Settings 和 `.env` 管理

4. [ ] 实现 PDF 元素高亮交互
   - 根据 OCR bbox 在 React-PDF 页面上叠加交互层
   - 支持文字、图片、表格和公式等元素的悬停及选中
   - 允许将选中内容发送到右侧对话

5. [ ] 统一 OpenAI 与 Anthropic 的工具调用协议
   - 在 Provider 层统一工具定义、调用事件和工具结果
   - 保持现有纯文本流式接口兼容

6. [ ] 实现页面与图片工具
   - `get_page_content(page_number)`：获取页面 Markdown 和图片元数据
   - `get_image(image_id)`：获取指定图片
   - `get_useful_images(page_number)`：获取当前页有用图片
   - `get_page_render(page_number)`：获取整页渲染图
   - `classify_image(...)`：写入图片分类、简介和重要性

## 有计划
- [ ] 加入笔记功能, 每一页都可以做笔记