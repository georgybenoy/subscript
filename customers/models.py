from django.conf import settings
from django.db import models


class Customer(models.Model):
    """
    Customer entity for Subscript platform.
    Represents an organization or individual subscriber.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        help_text="Associated user account for login access.",
    )
    name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(max_length=255, db_index=True)
    phone = models.CharField(max_length=50, blank=True)
    billing_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, default="IN")
    tax_id = models.CharField(max_length=100, blank=True, help_text="GSTIN / VAT / Tax ID")
    is_active = models.BooleanField(default=True, help_text="Customer status")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def __str__(self):
        if self.company_name and self.name:
            return f"{self.name} ({self.company_name})"
        return self.name or self.company_name or self.email
