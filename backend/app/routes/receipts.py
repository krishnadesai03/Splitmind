from fastapi import APIRouter, UploadFile, File, HTTPException
from ..models.schemas import ParseReceiptResponse
from ..services.ocr import parse_receipt_image

router = APIRouter(prefix="/receipts", tags=["receipts"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/parse", response_model=ParseReceiptResponse)
async def parse_receipt(file: UploadFile = File(...)):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Use JPEG, PNG, or WebP.",
        )

    image_bytes = await file.read()

    if len(image_bytes) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large. Max size is 10 MB.")

    try:
        receipt = parse_receipt_image(image_bytes, media_type=file.content_type)
        return ParseReceiptResponse(success=True, receipt=receipt)
    except Exception as e:
        return ParseReceiptResponse(success=False, error=str(e))
