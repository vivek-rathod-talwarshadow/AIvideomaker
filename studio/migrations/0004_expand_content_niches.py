from django.db import migrations, models


CONTENT_NICHE_CHOICES = [
    ("facts", "Facts"),
    ("motivation", "Motivation"),
    ("tech", "Tech Facts"),
    ("business", "Business Tips"),
    ("horror", "Horror Stories"),
    ("reddit", "Reddit Stories"),
    ("ai", "AI Facts"),
    ("money", "Money Tips"),
    ("gym", "Gym Motivation"),
    ("quotes", "Quotes"),
    ("space", "Space & Universe"),
    ("psychology", "Psychology"),
    ("crime", "Crime Stories"),
    ("mythology", "Mythology"),
    ("survival", "Survival"),
    ("animals", "Animal Facts"),
    ("body", "Human Body"),
    ("celebrity", "Celebrity Stories"),
    ("theory", "Internet Theories"),
    ("did-you-know", "Did You Know"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("studio", "0003_automationstate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contenttemplate",
            name="niche",
            field=models.CharField(choices=CONTENT_NICHE_CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name="videoproject",
            name="niche",
            field=models.CharField(choices=CONTENT_NICHE_CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name="viraltopic",
            name="niche",
            field=models.CharField(choices=CONTENT_NICHE_CHOICES, max_length=40),
        ),
    ]
