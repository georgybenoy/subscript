"""
Forms for Subscript Payments domain.
"""

from decimal import Decimal
from django import forms
from django.utils import timezone
from customers.models import Customer
from billing.models import Invoice, InvoiceStatus
from billing.money import quantize_money
from .models import Payment, PaymentMethod


class PaymentRecordForm(forms.Form):
    """
    Form to record incoming payment against an outstanding confirmed invoice.
    Matches field names expected by Member 2's templates/payments/form.html.
    """

    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.filter(status=InvoiceStatus.CONFIRMED).order_by("-issue_date"),
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Target Invoice",
        required=True,
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True).order_by("name"),
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Customer / Payer",
        required=False,
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control-subscript", "step": "0.01", "placeholder": "0.00"}),
        label="Payment Amount",
        required=True,
    )
    payment_method = forms.ChoiceField(
        choices=PaymentMethod.choices,
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Payment Method",
        initial=PaymentMethod.CARD,
        required=True,
    )
    transaction_reference = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control-subscript", "placeholder": "e.g. UTR-992104"}),
        label="Transaction Reference #",
    )
    status = forms.CharField(
        max_length=20,
        required=False,
        initial="SUCCESS",
        widget=forms.TextInput(attrs={"class": "form-control-subscript", "readonly": "readonly", "value": "SUCCESS"}),
        label="Settlement Status",
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control-subscript", "rows": 2}),
        required=False,
    )

    def clean_amount(self):
        amt = self.cleaned_data.get("amount")
        if amt is None or amt <= Decimal("0.00"):
            raise forms.ValidationError("Payment amount must be strictly greater than zero.")
        return quantize_money(amt)

    def clean(self):
        cleaned_data = super().clean()
        inv = cleaned_data.get("invoice")
        amt = cleaned_data.get("amount")

        if inv and amt:
            if inv.status != InvoiceStatus.CONFIRMED:
                raise forms.ValidationError(f"Payments can only be applied to CONFIRMED invoices (current: {inv.status}).")
            outstanding = inv.outstanding_balance
            if amt > outstanding:
                raise forms.ValidationError(
                    f"Amount (${amt}) exceeds outstanding invoice balance (${outstanding}). Overpayment rejected."
                )
        return cleaned_data
