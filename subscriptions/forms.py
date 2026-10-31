from django import forms
from django.utils import timezone

from customers.models import Customer
from discounts.models import Discount
from products.models import Plan
from .models import Subscription, SubscriptionItem, SubscriptionStatus


class SubscriptionForm(forms.ModelForm):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Subscriber / Customer",
    )
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Plan Attached",
    )
    status = forms.ChoiceField(
        choices=[
            (SubscriptionStatus.DRAFT, "Draft"),
            (SubscriptionStatus.QUOTATION, "Quotation"),
            (SubscriptionStatus.ACTIVE, "Active"),
            (SubscriptionStatus.PAUSED, "Paused"),
            (SubscriptionStatus.CLOSED, "Closed"),
        ],
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        initial=SubscriptionStatus.DRAFT,
        label="Agreement State",
    )
    discount = forms.ModelChoiceField(
        queryset=Discount.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={"class": "form-control-subscript"}),
        label="Promotional Discount (Optional)",
    )
    current_period_start = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"class": "form-control-subscript", "type": "date"}),
        label="Billing Period Start",
        initial=timezone.localdate,
    )
    current_period_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control-subscript", "type": "date"}),
        label="Billing Period End / Expiry",
    )

    class Meta:
        model = Subscription
        fields = [
            "customer",
            "plan",
            "status",
            "discount",
            "current_period_start",
            "current_period_end",
        ]

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("current_period_start")
        end = cleaned_data.get("current_period_end")
        if start and end and end < start:
            self.add_error("current_period_end", "Billing period end cannot be earlier than start date.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.start_date = self.cleaned_data.get("current_period_start")
        instance.expiry_date = self.cleaned_data.get("current_period_end")
        if instance.status == SubscriptionStatus.ACTIVE and not instance.next_billing_date:
            instance.next_billing_date = instance.current_period_start
        if commit:
            instance.save()
        return instance


class SubscriptionFilterForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={"placeholder": "Search..."}))
    plan = forms.ModelChoiceField(queryset=Plan.objects.all(), required=False)
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All Statuses")] + list(SubscriptionStatus.choices),
    )
