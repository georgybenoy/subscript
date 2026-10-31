from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User
from . import services


class RegistrationForm(forms.ModelForm):
    """
    Public customer registration form.
    Role is strictly forced to CUSTOMER on the server.
    """

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Create a strong password"}),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Repeat password"}),
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@example.com"}),
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")

        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "Passwords do not match.")
            else:
                email = cleaned_data.get("email")
                temp_user = User(email=email) if email else None
                validate_password(p1, user=temp_user)

        return cleaned_data

    def save(self, commit=True):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password1"]
        first_name = self.cleaned_data.get("first_name", "")
        last_name = self.cleaned_data.get("last_name", "")

        return services.register_customer(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )


class EmailAuthenticationForm(forms.Form):
    """
    Authentication form using email address.
    """

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@example.com", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Enter your password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        password = self.cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(self.request, username=email, password=password)
            if self.user_cache is None:
                # Check whether account exists but is deactivated
                existing_user = User.objects.filter(email__iexact=email).first()
                if existing_user and existing_user.check_password(password) and not existing_user.is_active:
                    raise ValidationError("This account is inactive. Please contact support.")
                raise ValidationError("Invalid email address or password.")
            elif not self.user_cache.is_active:
                raise ValidationError("This account is inactive. Please contact support.")

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class StaffCreationForm(forms.ModelForm):
    """
    Form for administrators to provision new staff members.
    Forces role to STAFF.
    """

    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Assign staff password"}),
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "staff@subscript.local"}),
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        if password:
            email = cleaned_data.get("email")
            temp_user = User(email=email) if email else None
            validate_password(password, user=temp_user)
        return cleaned_data

    def save(self, acting_admin: User):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password"]
        first_name = self.cleaned_data.get("first_name", "")
        last_name = self.cleaned_data.get("last_name", "")

        return services.create_staff_user(
            acting_admin=acting_admin,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )


class ProfileForm(forms.ModelForm):
    """
    Profile update form for users to manage their personal details.
    Email and role are immutable here.
    """

    class Meta:
        model = User
        fields = ("first_name", "last_name")
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
        }

    def save(self, user: User):
        return services.update_user_profile(
            user=user,
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
        )
