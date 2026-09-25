"""
GiftHub Core Domain Exceptions
"""

class GiftHubException(Exception):
    """Base domain exception for GiftHub platform."""
    def __init__(self, message: str, code: str = "ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class InsufficientBalanceError(GiftHubException):
    def __init__(self, message: str = "Balansingizda mablag' yetarli emas!"):
        super().__init__(message, code="INSUFFICIENT_BALANCE", status_code=400)


class InvalidOrderStateError(GiftHubException):
    def __init__(self, message: str = "Buyurtma holati ushbu operatsiyani bajarishga mos kelmaydi."):
        super().__init__(message, code="INVALID_ORDER_STATE", status_code=400)


class PaymentAlreadyProcessedError(GiftHubException):
    def __init__(self, message: str = "Ushbu to'lov allaqachon amalga oshirilgan."):
        super().__init__(message, code="PAYMENT_ALREADY_PROCESSED", status_code=409)


class PaymentVerificationError(GiftHubException):
    def __init__(self, message: str = "To'lov imzosi yoki ma'lumotlari tasdiqlanmadi."):
        super().__init__(message, code="PAYMENT_VERIFICATION_FAILED", status_code=400)


class PromoCodeExpiredError(GiftHubException):
    def __init__(self, message: str = "Promo-kodning amal qilish muddati tugagan."):
        super().__init__(message, code="PROMO_CODE_EXPIRED", status_code=400)


class PromoCodeLimitReachedError(GiftHubException):
    def __init__(self, message: str = "Promo-koddan foydalanish limiti tugagan."):
        super().__init__(message, code="PROMO_CODE_LIMIT_REACHED", status_code=400)


class PromoCodeAlreadyUsedError(PromoCodeLimitReachedError):
    def __init__(self, message: str = "Siz ushbu promo-koddan allaqachon foydalangansiz."):
        super().__init__(message)


class PermissionDeniedError(GiftHubException):
    def __init__(self, message: str = "Ushbu amalni bajarish uchun sizda yetarli ruxsat yo'q."):
        super().__init__(message, code="PERMISSION_DENIED", status_code=403)


class PriceExpiredError(GiftHubException):
    def __init__(self, message: str = "Narx qulflangan vaqt muddati tugadi. Iltimos, qaytadan hisoblang."):
        super().__init__(message, code="PRICE_EXPIRED", status_code=400)


class FulfillmentFailedError(GiftHubException):
    def __init__(self, message: str = "Buyurtmani yetkazib berishda xatolik yuz berdi."):
        super().__init__(message, code="FULFILLMENT_FAILED", status_code=500)


class UserNotFoundError(GiftHubException):
    def __init__(self, message: str = "Foydalanuvchi topilmadi."):
        super().__init__(message, code="USER_NOT_FOUND", status_code=404)


class OrderNotFoundError(GiftHubException):
    def __init__(self, message: str = "Buyurtma topilmadi."):
        super().__init__(message, code="ORDER_NOT_FOUND", status_code=404)
