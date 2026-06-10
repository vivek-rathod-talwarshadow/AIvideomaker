from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("studio", "0009_add_dark_curiosity_niche"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationstate",
            name="selected_niches",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
