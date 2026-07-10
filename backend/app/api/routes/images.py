from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import get_session
from app.models import ImageAsset
from app.schemas.document import ImageAssetRead, ImageAssetUpdate

router = APIRouter(prefix="/images", tags=["images"])


def _get_image(image_id: int, session: Session) -> ImageAsset:
    image = session.get(ImageAsset, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    return image


@router.get("/{image_id}/metadata", response_model=ImageAssetRead)
def get_image_metadata(
    image_id: int, session: Session = Depends(get_session)
) -> ImageAssetRead:
    return ImageAssetRead.from_model(_get_image(image_id, session))


@router.patch("/{image_id}", response_model=ImageAssetRead)
def update_image(
    image_id: int,
    body: ImageAssetUpdate,
    session: Session = Depends(get_session),
) -> ImageAssetRead:
    image = _get_image(image_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(image, field, value)
    image.updated_at = datetime.now(timezone.utc)
    session.add(image)
    session.commit()
    session.refresh(image)
    return ImageAssetRead.from_model(image)


@router.get("/{image_id}")
def get_image_file(
    image_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    image = _get_image(image_id, session)
    if not Path(image.stored_path).exists():
        raise HTTPException(status_code=404, detail="图片文件不存在")
    image.retrieval_count += 1
    session.add(image)
    session.commit()
    return FileResponse(
        image.stored_path, media_type=image.mime_type, filename=image.filename
    )
