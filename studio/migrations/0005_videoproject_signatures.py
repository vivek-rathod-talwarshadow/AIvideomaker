from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0004_expand_content_niches"),
    ]

    operations = [
        migrations.AddField(
            model_name="videoproject",
            name="content_signature",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="output_fingerprint",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
