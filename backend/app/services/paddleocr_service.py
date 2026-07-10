"""PaddleOCR AI Studio 整文件 Job API 客户端。"""

from collections.abc import Iterator
import json
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.document_parser import (
    DocumentParser,
    ParseJobStatus,
    RemoteFile,
    RemotePage,
)


class PaddleOCRDocumentParser(DocumentParser):
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=settings.paddleocr_timeout_seconds,
            follow_redirects=True,
        )

    @property
    def _headers(self) -> dict[str, str]:
        if not settings.paddleocr_api_token:
            raise RuntimeError("未配置 STUDYWISE_PADDLEOCR_API_TOKEN")
        return {"Authorization": f"bearer {settings.paddleocr_api_token}"}

    def submit(self, pdf_path: Path) -> str:
        optional_payload = {
            "useDocOrientationClassify": (
                settings.paddleocr_use_doc_orientation_classify
            ),
            "useDocUnwarping": settings.paddleocr_use_doc_unwarping,
            "useChartRecognition": settings.paddleocr_use_chart_recognition,
            "prettifyMarkdown": settings.paddleocr_prettify_markdown,
        }
        with pdf_path.open("rb") as pdf_file:
            response = self._client.post(
                settings.paddleocr_job_url,
                headers=self._headers,
                data={
                    "model": settings.paddleocr_model,
                    "optionalPayload": json.dumps(optional_payload),
                },
                files={"file": (pdf_path.name, pdf_file, "application/pdf")},
            )
        response.raise_for_status()
        return str(response.json()["data"]["jobId"])

    def get_status(self, job_id: str) -> ParseJobStatus:
        response = self._client.get(
            f"{settings.paddleocr_job_url}/{job_id}",
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()["data"]
        progress = data.get("extractProgress") or {}
        result_urls = data.get("resultUrl") or {}
        return ParseJobStatus(
            state=str(data["state"]),
            total_pages=int(progress.get("totalPages") or 0),
            processed_pages=int(progress.get("extractedPages") or 0),
            result_url=result_urls.get("jsonUrl"),
            error_message=data.get("errorMsg"),
        )

    def iter_pages(self, result_url: str) -> Iterator[RemotePage]:
        response = self._client.get(result_url)
        response.raise_for_status()
        page_number = 0
        for line in response.text.splitlines():
            if not line.strip():
                continue
            result = json.loads(line)["result"]
            for page_result in result.get("layoutParsingResults", []):
                page_number += 1
                markdown = page_result.get("markdown") or {}
                images = [
                    RemoteFile(index=index, source_name=str(name), url=str(url))
                    for index, (name, url) in enumerate(
                        (markdown.get("images") or {}).items(), start=1
                    )
                ]
                output_images = [
                    RemoteFile(index=index, source_name=str(name), url=str(url))
                    for index, (name, url) in enumerate(
                        (page_result.get("outputImages") or {}).items(), start=1
                    )
                ]
                yield RemotePage(
                    page_number=page_number,
                    structure=page_result,
                    markdown=str(markdown.get("text") or ""),
                    images=images,
                    output_images=output_images,
                )

    def download(self, url: str) -> tuple[bytes, str]:
        response = self._client.get(url)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "application/octet-stream")
        return response.content, mime_type.split(";", 1)[0].strip()
