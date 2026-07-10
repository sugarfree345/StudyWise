from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="STUDYWISE_")

    data_dir: Path = BASE_DIR / "data"
    # 5173 = Vite dev server，1420 = Tauri dev
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:1420"]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'studywise.db'}"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
