import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class SubscriptPasswordValidator:
    """
    Custom password validator for Subscript platform:
    - Minimum length > 8 (at least 9 characters)
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one special character
    """

    def __init__(self, min_length=9):
        self.min_length = min_length

    def validate(self, password, user=None):
        errors = []

        if len(password) < self.min_length:
            errors.append(
                ValidationError(
                    _(f"Password must be at least {self.min_length} characters long."),
                    code="password_too_short",
                )
            )

        if not re.search(r"[A-Z]", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one uppercase letter (A-Z)."),
                    code="password_no_upper",
                )
            )

        if not re.search(r"[a-z]", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one lowercase letter (a-z)."),
                    code="password_no_lower",
                )
            )

        if not re.search(r"[^A-Za-z0-9]", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one special character (e.g. !@#$%^&*)."),
                    code="password_no_special",
                )
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            f"Your password must be at least {self.min_length} characters long, "
            "and contain at least one uppercase letter, one lowercase letter, "
            "and one special character."
        )
