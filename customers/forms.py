import re
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from .models import Customer


def validate_phone_number(value: str):
    """
    Validates phone number format:
    Permits optional leading '+', digits, spaces, and dashes.
    Enforces 7 to 15 digits total.
    """
    if not value:
        return value

    stripped = value.strip()
    if not re.match(r"^\+?[\d\s-]{7,25}$", stripped):
        raise ValidationError("Phone number can only contain digits, spaces, hyphens, and an optional leading '+'.")

    digits_only = re.sub(r"\D", "", stripped)
    if len(digits_only) < 7 or len(digits_only) > 15:
        raise ValidationError("Phone number must contain between 7 and 15 digits.")

    return stripped


class CustomerForm(forms.ModelForm):
    """
    Customer creation and update form.
    Strips whitespace and enforces role-aware field accessibility.
    """

    class Meta:
        model = Customer
        fields = (
            "name",
            "company_name",
            "email",
            "phone",
            "billing_address",
            "city",
            "state",
            "country",
            "tax_id",
            "is_active",
        )
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Full Name"}),
            "company_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Organization (Optional)"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "billing@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+91 98765 43210"}),
            "billing_address": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Street address"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control", "placeholder": "IN"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "GSTIN / VAT / Tax ID"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.request_user = user
        super().__init__(*args, **kwargs)

        # For customers editing their own profile, remove administrative fields
        if self.request_user and getattr(self.request_user, "is_customer_role", False):
            if "is_active" in self.fields:
                del self.fields["is_active"]

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        EmailValidator()(email)
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "")
        return validate_phone_number(phone)

    def clean(self):
        cleaned_data = super().clean()
        for field, value in cleaned_data.items():
            if isinstance(value, str):
                cleaned_data[field] = value.strip()
        return cleaned_data


class CustomerFilterForm(forms.Form):
    """
    Search and filter form for customer list view.
    Submitted via GET.
    """

    STATUS_CHOICES = (
        ("", "All Statuses"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    )

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Search name, company, email, phone, city, tax ID...",
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Filter by City"}),
    )
    state = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Filter by State"}),
    )
    country = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Filter by Country"}),
    )
