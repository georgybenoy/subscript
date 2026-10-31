import sys
from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "subscriptions"

    def ready(self):
        super().ready()
        # Insulate teammate modules (billing, analytics, payments) that import from billing.integrations
        bi = sys.modules.get("billing.integrations")
        if bi is not None:
            from django.apps import apps
            try:
                sub_model = apps.get_model("subscriptions", "Subscription")
                subitem_model = apps.get_model("subscriptions", "SubscriptionItem")
                setattr(bi, "Subscription", sub_model)
                setattr(bi, "SubscriptionItem", subitem_model)
            except Exception:
                pass

            # Fallback for dynamic module resolution via PEP 562
            orig_getattr = getattr(bi, "__getattr__", None)

            def _bi_getattr(name):
                if name == "Subscription":
                    return apps.get_model("subscriptions", "Subscription")
                elif name == "SubscriptionItem":
                    return apps.get_model("subscriptions", "SubscriptionItem")
                elif name == "Discount":
                    return apps.get_model("discounts", "Discount")
                elif name == "Product":
                    return apps.get_model("products", "Product")
                elif name == "Plan":
                    return apps.get_model("products", "Plan")
                if orig_getattr:
                    return orig_getattr(name)
                raise AttributeError(f"module 'billing.integrations' has no attribute '{name}'")

            bi.__getattr__ = _bi_getattr
