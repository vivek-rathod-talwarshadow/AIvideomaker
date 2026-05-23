from __future__ import annotations

import random

from studio.enums import ContentNiche
from studio.models import ViralTopic


NICHE_SEEDS = {
    ContentNiche.FACTS: [
        "facts that sound fake but are true",
        "history facts people never learned in school",
        "science facts that break your brain",
    ],
    ContentNiche.MOTIVATION: [
        "discipline beats motivation",
        "small habits that change your life",
        "morning mindset for winners",
    ],
    ContentNiche.TECH: [
        "tech myths everyone still believes",
        "AI tools students can use for free",
        "hidden smartphone tricks",
    ],
    ContentNiche.REDDIT: [
        "reddit confession story",
        "aita style moral dilemma",
        "creepy late-night thread",
    ],
    ContentNiche.MONEY: [
        "money mistakes in your twenties",
        "tiny savings habits that compound",
        "psychology of impulse spending",
    ],
}


def build_rule_based_topic(niche: str) -> ViralTopic:
    seed = random.choice(NICHE_SEEDS.get(niche, NICHE_SEEDS[ContentNiche.FACTS]))
    hook = f"Wait... {seed.capitalize()}?"
    title = hook.replace("Wait... ", "")
    script = (
        f"{hook}\n"
        "Here is the short version.\n"
        "Point one hits fast and feels surprising.\n"
        "Point two adds proof or context.\n"
        "Point three gives a takeaway people can share.\n"
        "Follow for more."
    )
    scene_plan = [
        {"text": hook, "duration": 4},
        {"text": "Quick context with a strong visual.", "duration": 7},
        {"text": "Proof, twist, or lesson.", "duration": 7},
        {"text": "Memorable ending and CTA.", "duration": 5},
    ]
    hashtags = [f"#{niche}", "#shorts", "#viral", "#reels", "#didyouknow"]
    return ViralTopic.objects.create(
        niche=niche,
        title=title,
        hook=hook,
        script=script,
        scene_plan=scene_plan,
        seo_title=f"{title} | Viral Short",
        description=script,
        hashtags=hashtags,
        source_notes=["rule-based-template"],
        is_trending=False,
    )
