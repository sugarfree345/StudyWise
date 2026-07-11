from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="STUDYWISE_")

    data_dir: Path = BASE_DIR / "data"
    paddleocr_api_token: str = ""
    paddleocr_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_model: str = "PaddleOCR-VL-1.6"
    paddleocr_poll_interval_seconds: float = 5.0
    paddleocr_timeout_seconds: float = 120.0
    paddleocr_use_doc_orientation_classify: bool = False
    paddleocr_use_doc_unwarping: bool = False
    paddleocr_use_chart_recognition: bool = False
    paddleocr_prettify_markdown: bool = False

    openai_api_key: str = ""
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""

    # 图片有用性启发式：未被 Markdown 引用且小于此字节数的图，判为装饰（校徽/图标）。
    image_decoration_max_bytes: int = 10 * 1024

    # 5173 = Vite dev server，1420 = Tauri dev
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:1420"]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def parsed_dir(self) -> Path:
        return self.data_dir / "parsed"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'studywise.db'}"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.parsed_dir.mkdir(parents=True, exist_ok=True)
