from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0007_add_glam_niche"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationstate",
            name="brainrot_mode",
            field=models.BooleanField(default=False),
        ),
    ]
