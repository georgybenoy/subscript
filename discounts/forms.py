from decimal import Decimal
from django import forms
from django.utils import timezone
from .models import Discount, DiscountType


class DiscountForm(forms.ModelForm):
    max_redemptions = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control-subscript", "placeholder": "Unlimited"}
        ),
        label="Maximum Total Redemptions",
    )
    valid_from = forms.DateField(
        required=True,
        widget=forms.DateInput(
            attrs={"class": "form-control-subscript", "type": "date"}
        ),
        label="Valid From Date",
        initial=timezone.localdate,
    )
    valid_until = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"class": "form-control-subscript", "type": "date"}
        ),
        label="Valid Until (Expiry)",
    )

    class Meta:
        model = Discount
        fields = ["code", "discount_type", "amount"]
        widgets = {
            "code": forms.TextInput(
                attrs={"class": "form-control-subscript font-monospace", "placeholder": "e.g. SUMMER25"}
            ),
            "discount_type": forms.Select(
                attrs={"class": "form-control-subscript"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": "form-control-subscript", "step": "0.01", "min": "0.01"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["valid_from"].initial = self.instance.start_date
            self.fields["valid_until"].initial = self.instance.end_date
            self.fields["max_redemptions"].initial = self.instance.usage_limit

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().upper()
        if not code:
            raise forms.ValidationError("Coupon code cannot be empty.")
        qs = Discount.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Discount code '{code}' already exists.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount")
        discount_type = cleaned_data.get("discount_type")
        valid_from = cleaned_data.get("valid_from")
        valid_until = cleaned_data.get("valid_until")

        if discount_type == DiscountType.PERCENTAGE:
            if amount is not None and (amount <= Decimal("0.00") or amount > Decimal("100.00")):
                self.add_error("amount", "Percentage discount must be between 0.01 and 100.00%.")
        elif discount_type == DiscountType.FIXED:
            if amount is not None and amount <= Decimal("0.00"):
                self.add_error("amount", "Fixed discount amount must be greater than 0.")

        if valid_from and valid_until and valid_until < valid_from:
            self.add_error("valid_until", "Valid until date cannot be earlier than valid from date.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.start_date = self.cleaned_data.get("valid_from")
        instance.end_date = self.cleaned_data.get("valid_until")
        instance.usage_limit = self.cleaned_data.get("max_redemptions")
        if commit:
            instance.save()
        return instance


class DiscountFilterForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={"placeholder": "Search code..."}))
    discount_type = forms.ChoiceField(
        required=False,
        choices=[("", "All Types"), (DiscountType.PERCENTAGE, "Percentage"), (DiscountType.FIXED, "Fixed Amount")],
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All Statuses"), ("active", "Active"), ("expired", "Expired")],
    )
