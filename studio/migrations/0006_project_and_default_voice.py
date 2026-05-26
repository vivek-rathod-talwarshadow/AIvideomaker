from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0005_videoproject_signatures"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationstate",
            name="default_voice_name",
            field=models.CharField(default="en-US-ChristopherNeural", max_length=80),
        ),
        migrations.AddField(
            model_name="videoproject",
            name="voice_name",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
