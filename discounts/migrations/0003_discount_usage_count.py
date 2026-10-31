from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("discounts", "0002_remove_discount_discounts_d_code_3a970a_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="discount",
            name="usage_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
