from decimal import Decimal
from django import forms
from .models import Product, ProductType, ProductVariant, Plan


class ProductForm(forms.ModelForm):
    # Field alias matching Member 2's form.html notes/description
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control-subscript", "rows": 3}),
        required=False,
        label="Internal Notes / Description",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "sales_price",
            "cost_price",
            "product_type",
            "is_active",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. Core SaaS Platform"}),
            "sales_price": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "cost_price": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "product_type": forms.Select(attrs={"class": "form-control-subscript"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "description": forms.Textarea(attrs={"class": "form-control-subscript", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["notes"].initial = self.instance.description

    def clean(self):
        cleaned_data = super().clean()
        notes = cleaned_data.get("notes")
        desc = cleaned_data.get("description")
        if notes and not desc:
            cleaned_data["description"] = notes
        return cleaned_data


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = [
            "product",
            "name",
            "sku",
            "value",
            "price",
            "price_adjustment",
            "is_active",
        ]
        widgets = {
            "product": forms.Select(attrs={"class": "form-control-subscript"}),
            "name": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. Enterprise Edition"}),
            "sku": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. SKU-ENT-01"}),
            "value": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. 50 Seats"}),
            "price": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "price_adjustment": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            "product",
            "name",
            "code",
            "billing_interval",
            "price",
            "base_price",
            "minimum_quantity",
            "currency",
            "trial_days",
            "is_active",
        ]
        widgets = {
            "product": forms.Select(attrs={"class": "form-control-subscript"}),
            "name": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. Pro Monthly"}),
            "code": forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. PRO-MONTHLY"}),
            "billing_interval": forms.Select(attrs={"class": "form-control-subscript"}),
            "price": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "base_price": forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01"}),
            "minimum_quantity": forms.NumberInput(attrs={"class": "form-control-subscript", "min": "1"}),
            "currency": forms.TextInput(attrs={"class": "form-control-subscript", "maxlength": "3"}),
            "trial_days": forms.NumberInput(attrs={"class": "form-control-subscript", "min": "0"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ProductFilterForm(forms.Form):
    q = forms.CharField(required=False)
    type = forms.ChoiceField(
        choices=[("", "All Product Types")] + list(ProductType.choices),
        required=False,
    )
    status = forms.ChoiceField(
        choices=[("", "Status"), ("active", "Active"), ("archived", "Archived")],
        required=False,
    )
