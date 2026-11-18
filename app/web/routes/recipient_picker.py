from fastapi import APIRouter, Depends, HTTPException

from app.core.logging import get_logger
from app.models import User
from app.services import recipient_picker
from app.web.auth import get_current_user
from app.web.state import get_bot

logger = get_logger(__name__)

router = APIRouter(tags=["Recipient picker"])


@router.post("/api/recipients/picker")
async def create_picker_request(user: User = Depends(get_current_user)):
    """Prepares Telegram's native 'choose a user' button for the caller (opened with WebApp.requestChat)."""
    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot hozircha ulanmagan. Birozdan so'ng qayta urinib ko'ring.")
    try:
        return await recipient_picker.create_request(bot, user.id)
    except recipient_picker.PickerCooldown:
        raise HTTPException(status_code=429, detail="Biroz kuting va qayta urinib ko'ring.")
    except Exception as e:
        logger.warning(f"Recipient picker: Telegram refused to prepare the button for {user.id}: {e}")
        raise HTTPException(status_code=502, detail="Telegram tanlash oynasini tayyorlay olmadi. Qo'lda yozing.")


@router.get("/api/recipients/picker/{request_id}")
async def read_picker_request(request_id: int, user: User = Depends(get_current_user)):
    """Returns {"status": "pending"} or the chosen user; only for the user who created the request."""
    data = await recipient_picker.get_pick(user.id, request_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Tanlov topilmadi yoki muddati o'tgan.")
    return data
