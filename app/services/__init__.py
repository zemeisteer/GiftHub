from app.services.fulfillment.service import FulfillmentService, fulfillment_service
from app.services.notifications.service import NotificationService, notification_service
from app.services.orders.service import OrderService, order_service
from app.services.payments import (
    autopaycard_provider,
    click_provider,
    payme_provider,
    payment_service,
)
from app.services.pricing.service import PricingService, pricing_service
from app.services.promotions.service import PromotionService, promotion_service
from app.services.referrals.service import ReferralService, referral_service
from app.services.support.service import SupportService, support_service
from app.services.wallet.service import WalletService, wallet_service

__all__ = [
    "FulfillmentService",
    "NotificationService",
    "OrderService",
    "PricingService",
    "PromotionService",
    "ReferralService",
    "SupportService",
    "WalletService",
    "autopaycard_provider",
    "click_provider",
    "fulfillment_service",
    "notification_service",
    "order_service",
    "payme_provider",
    "payment_service",
    "pricing_service",
    "promotion_service",
    "referral_service",
    "support_service",
    "wallet_service",
]
