from __future__ import annotations

from math import ceil
import random

from studio.enums import ContentNiche
from studio.models import ViralTopic


TOPIC_LIBRARY = {
    ContentNiche.FACTS: [
        {
            "title": "Science Facts That Break Your Brain",
            "hook": "Wait... these science facts sound fake, but they're real.",
            "beats": [
                "Bananas are slightly radioactive because potassium-40 naturally exists inside them, but the dose is far too small to hurt you.",
                "Octopuses have three hearts, and two of them stop beating when the octopus swims.",
                "The smell after rain is called petrichor, and part of it comes from soil bacteria releasing a compound named geosmin.",
                "Your brain can recognize an image in about 13 milliseconds, which is faster than most people blink.",
                "Space is so quiet because sound needs particles to travel, and a vacuum has almost none.",
            ],
            "cta": "Follow DarkBrainScroll for more facts that feel impossible but are true.",
            "hashtags": ["#facts", "#science", "#didyouknow", "#shorts", "#viral"],
            "source_notes": ["curated-facts-pack"],
        },
        {
            "title": "History Facts People Never Learned In School",
            "hook": "History gets way stranger than textbooks admit.",
            "beats": [
                "Oxford University is older than the Aztec Empire by centuries.",
                "Cleopatra lived closer to the first moon landing than to the building of the Great Pyramid of Giza.",
                "The shortest war in recorded history lasted less than one hour between Britain and Zanzibar in 1896.",
                "Ancient Romans used crushed snail shells and ash in some beauty treatments.",
                "Napoleon was once attacked by a swarm of rabbits during a hunting event arranged for him.",
            ],
            "cta": "Follow DarkBrainScroll if you want the weird side of history.",
            "hashtags": ["#history", "#facts", "#shorts", "#didyouknow", "#viral"],
            "source_notes": ["curated-history-pack"],
        },
        {
            "title": "Facts That Sound Fake But Are True",
            "hook": "These facts sound invented, but every one of them is real.",
            "beats": [
                "Honey can stay edible for years because its low moisture and high acidity make it hard for bacteria to grow.",
                "Wombat poop is cube-shaped, which helps it stay in place when marking territory.",
                "A day on Venus is longer than a year on Venus because it spins so slowly on its axis.",
                "Sharks existed before trees, which means they were already in the ocean long before forests covered Earth.",
                "There are more possible chess games than there are atoms in the observable universe.",
            ],
            "cta": "Follow DarkBrainScroll for more facts people argue about in the comments.",
            "hashtags": ["#facts", "#mindblown", "#science", "#shorts", "#viral"],
            "source_notes": ["curated-truth-pack"],
        },
    ],
    ContentNiche.TECH: [
        {
            "title": "Tech Myths Everyone Still Believes",
            "hook": "A few popular tech myths refuse to die.",
            "beats": [
                "Closing background apps constantly can actually waste battery because your phone has to reopen them from scratch.",
                "More megapixels do not always mean a better camera, because sensor size and image processing matter just as much.",
                "Incognito mode hides your browsing from your local device history, but it does not make you invisible to websites or internet providers.",
                "Charging your phone overnight is usually fine because modern phones manage charging to protect the battery.",
                "A stronger Wi-Fi signal does not guarantee faster internet if your service plan is the real bottleneck.",
            ],
            "cta": "Follow DarkBrainScroll for tech advice without the myths.",
            "hashtags": ["#tech", "#myths", "#smartphone", "#shorts", "#viral"],
            "source_notes": ["curated-tech-pack"],
        },
    ],
    ContentNiche.MONEY: [
        {
            "title": "Money Mistakes In Your Twenties",
            "hook": "A few early money mistakes cost people years later.",
            "beats": [
                "Ignoring high-interest debt keeps money flowing backward even when your income starts rising.",
                "Lifestyle inflation quietly eats every raise when spending grows as fast as salary.",
                "Waiting too long to invest can be expensive because compounding needs time more than perfect timing.",
                "Buying on monthly payments makes expensive purchases feel small, even when the full cost is huge.",
                "Not tracking recurring subscriptions leaks money from your account with almost no effort.",
            ],
            "cta": "Follow DarkBrainScroll for practical money lessons in under a minute.",
            "hashtags": ["#money", "#finance", "#selfimprovement", "#shorts", "#viral"],
            "source_notes": ["curated-money-pack"],
        },
    ],
    ContentNiche.MOTIVATION: [
        {
            "title": "Discipline Beats Motivation",
            "hook": "Motivation gets attention, but discipline changes results.",
            "beats": [
                "Motivation is emotional, so it disappears fast when you are tired, stressed, or distracted.",
                "Discipline works better because it turns action into routine instead of waiting for the perfect mood.",
                "Small repeatable habits usually beat giant one-day efforts that never become consistent.",
                "The best system removes friction, so starting takes less energy than making excuses.",
                "You do not need to feel ready every day. You need a process that still works on average days.",
            ],
            "cta": "Follow DarkBrainScroll for mindset content that actually helps you act.",
            "hashtags": ["#motivation", "#discipline", "#mindset", "#shorts", "#viral"],
            "source_notes": ["curated-motivation-pack"],
        },
    ],
}


def _topic_candidates(niche: str) -> list[dict]:
    return TOPIC_LIBRARY.get(niche, TOPIC_LIBRARY[ContentNiche.FACTS])


def estimate_duration_seconds(script: str, scene_plan: list[dict] | None = None) -> int:
    words = max(len(script.split()), 1)
    narration_seconds = ceil(words / 2.4)
    if scene_plan:
        scene_seconds = sum(max(int(scene.get("duration", 0) or 0), 3) for scene in scene_plan)
        narration_seconds = max(narration_seconds, scene_seconds)
    return max(20, min(narration_seconds + 2, 75))


def build_scene_plan(hook: str, beats: list[str], cta: str) -> list[dict]:
    segments = [hook, *beats, cta]
    scene_plan: list[dict] = []
    for index, text in enumerate(segments):
        word_count = len(text.split())
        duration = max(3, min(10, ceil(word_count / 2.8) + (1 if index == 0 else 0)))
        scene_plan.append({"text": text, "duration": duration})
    return scene_plan


def build_rule_based_topic(niche: str) -> ViralTopic:
    template = random.choice(_topic_candidates(niche))
    hook = template["hook"]
    beats = list(template["beats"])
    cta = template["cta"]
    title = template["title"]
    script_lines = [hook, *beats, cta]
    script = "\n".join(script_lines)
    scene_plan = build_scene_plan(hook, beats, cta)
    duration_seconds = estimate_duration_seconds(script, scene_plan)
    return ViralTopic.objects.create(
        niche=niche,
        title=title,
        hook=hook,
        script=script,
        scene_plan=scene_plan,
        seo_title=f"{title} | DarkBrainScroll",
        description=script,
        hashtags=template.get("hashtags", [f"#{niche}", "#shorts", "#viral"]),
        source_notes=[*template.get("source_notes", []), f"estimated-duration:{duration_seconds}"],
        is_trending=False,
    )
