from __future__ import annotations

from math import ceil
import random
import re

from django.conf import settings
from studio.enums import ContentNiche
from studio.models import EventLog, ViralTopic
from .utils import stable_hash


def _topic(
    title: str,
    hook: str,
    beats: list[str],
    cta: str,
    hashtags: list[str],
    source_notes: list[str],
) -> dict:
    return {
        "title": title,
        "hook": hook,
        "beats": beats,
        "cta": cta,
        "hashtags": hashtags,
        "source_notes": source_notes,
    }


TOPIC_LIBRARY = {
    ContentNiche.FACTS: [
        _topic(
            "Science Facts That Break Your Brain",
            "Wait... these science facts sound fake, but they're real.",
            [
                "Bananas are slightly radioactive because potassium-40 naturally exists inside them, but the dose is far too small to hurt you.",
                "Octopuses have three hearts, and two of them stop beating when the octopus swims.",
                "The smell after rain is called petrichor, and part of it comes from soil bacteria releasing a compound named geosmin.",
                "Your brain can recognize an image in about 13 milliseconds, which is faster than most people blink.",
                "Space is quiet because sound needs particles to travel, and a vacuum has almost none.",
            ],
            "Follow DarkBrainScroll for more facts that feel impossible but are true.",
            ["#facts", "#science", "#didyouknow", "#shorts", "#viral"],
            ["curated-facts-pack"],
        ),
        _topic(
            "History Facts People Never Learned In School",
            "History gets way stranger than textbooks admit.",
            [
                "Oxford University is older than the Aztec Empire by centuries.",
                "Cleopatra lived closer to the first moon landing than to the building of the Great Pyramid of Giza.",
                "The shortest war in recorded history lasted less than one hour between Britain and Zanzibar in 1896.",
                "Ancient Romans used crushed snail shells and ash in some beauty treatments.",
                "Napoleon was once attacked by a swarm of rabbits during a hunting event arranged for him.",
            ],
            "Follow DarkBrainScroll if you want the weird side of history.",
            ["#history", "#facts", "#shorts", "#didyouknow", "#viral"],
            ["curated-history-pack"],
        ),
        _topic(
            "Facts That Sound Fake But Are True",
            "These facts sound invented, but every one of them is real.",
            [
                "Honey can stay edible for years because its low moisture and high acidity make it hard for bacteria to grow.",
                "Wombat poop is cube-shaped, which helps it stay in place when marking territory.",
                "A day on Venus is longer than a year on Venus because it spins so slowly on its axis.",
                "Sharks existed before trees, which means they were already in the ocean long before forests covered Earth.",
                "There are more possible chess games than there are atoms in the observable universe.",
            ],
            "Follow DarkBrainScroll for more facts people argue about in the comments.",
            ["#facts", "#mindblown", "#science", "#shorts", "#viral"],
            ["curated-truth-pack"],
        ),
    ],
    ContentNiche.HORROR: [
        _topic(
            "Scary Facts That Sound Made Up",
            "These creepy facts are real enough to ruin your night.",
            [
                "Some caves have remained sealed so long that entire ecosystems evolved in darkness.",
                "There are abandoned towns where the ground still smolders because underground fires never fully stopped.",
                "Sleep paralysis can make people feel a presence in the room even when nothing is there.",
                "Deep ocean sounds have been recorded that scientists still debate years later.",
                "Some ancient burial sites were built specifically to make intruders feel watched.",
            ],
            "Follow for safer creepy content without fake ghost claims.",
            ["#horror", "#creepy", "#facts", "#shorts", "#viral"],
            ["curated-horror-pack", "safer-creepy-facts"],
        ),
        _topic(
            "Unsolved Mysteries People Still Debate",
            "Some mysteries stay alive because the evidence never fully closes the case.",
            [
                "A few historic disappearances became famous because witnesses conflicted from day one.",
                "Some coded messages were found in real investigations and never publicly solved in full detail.",
                "There are missing-person cases where the timeline is clearer than the motive.",
                "A famous unidentified signal can still spark theories decades later.",
                "The strangest mysteries usually survive because every explanation leaves one piece missing.",
            ],
            "Follow for unexplained stories told carefully, not recklessly.",
            ["#mystery", "#unsolved", "#creepy", "#shorts", "#viral"],
            ["curated-mystery-pack", "careful-framing"],
        ),
    ],
    ContentNiche.SPACE: [
        _topic(
            "Black Hole Facts That Feel Illegal To Know",
            "Black holes get weird faster than science fiction does.",
            [
                "A black hole is not a cosmic vacuum cleaner because distance still matters.",
                "Time appears to slow dramatically near extreme gravity from an outside point of view.",
                "Some black holes were found by watching stars move around something invisible.",
                "Supermassive black holes can sit at the center of galaxies for billions of years.",
                "Scientists can study black holes indirectly from light, motion, and hot gas around them.",
            ],
            "Follow DarkBrainScroll for space topics that stay wild and grounded.",
            ["#space", "#blackhole", "#science", "#shorts", "#viral"],
            ["curated-space-pack"],
        ),
        _topic(
            "What If Earth Changed Overnight",
            "A few space what-if scenarios would rewrite life on Earth fast.",
            [
                "If Earth stopped spinning suddenly, the atmosphere would keep moving with huge destructive force.",
                "If the Moon vanished, tides and nighttime light would change in ways humans would notice quickly.",
                "If Earth moved slightly closer to the Sun, climate systems would shift hard over time.",
                "If the magnetic field weakened for long enough, more solar radiation could reach the upper atmosphere.",
                "Space what-ifs are popular because tiny cosmic changes can create giant consequences here.",
            ],
            "Follow for more universe scenarios that are dramatic without being fake.",
            ["#space", "#earth", "#whatif", "#shorts", "#viral"],
            ["curated-space-whatif-pack"],
        ),
    ],
    ContentNiche.PSYCHOLOGY: [
        _topic(
            "Psychology Tricks Your Brain Uses Every Day",
            "Your brain takes shortcuts constantly, and most people never notice.",
            [
                "First impressions can frame later details before you realize it.",
                "People remember unfinished tasks surprisingly well because open loops keep pulling attention.",
                "Your mood can shift how risky or safe a decision feels in the moment.",
                "Small social cues can change confidence even when no one says a word.",
                "Most mind hacks work better when you understand the pattern instead of chasing magic tricks.",
            ],
            "Follow for psychology content that helps without pretending to control people.",
            ["#psychology", "#mindhack", "#behavior", "#shorts", "#viral"],
            ["curated-psychology-pack", "safer-psychology"],
        ),
        _topic(
            "Body Language Signals People Overread",
            "Body language can be useful, but one gesture never tells the whole story.",
            [
                "Crossed arms can mean discomfort, cold temperature, or just habit.",
                "Eye contact changes across cultures, stress levels, and personality.",
                "Fidgeting is not automatically lying because anxiety and energy show up similarly.",
                "Tone, timing, and context usually matter more than a single pose.",
                "The safest way to read people is to look for patterns, not one dramatic clue.",
            ],
            "Follow for human behavior content without the fake expert act.",
            ["#bodylanguage", "#psychology", "#socialskills", "#shorts", "#viral"],
            ["curated-body-language-pack", "careful-framing"],
        ),
    ],
    ContentNiche.MONEY: [
        _topic(
            "Expensive Mistakes That Quietly Keep People Broke",
            "Some money mistakes do not look dramatic until years later.",
            [
                "High-interest debt compounds against you while feeling temporary.",
                "Lifestyle inflation can absorb every raise before you build savings.",
                "Buying luxury to signal status often creates pressure instead of freedom.",
                "Ignoring hidden fees makes average decisions far more expensive over time.",
                "The richest-looking move online is not always the smartest move offline.",
            ],
            "Follow for practical money content without fake get-rich promises.",
            ["#money", "#finance", "#wealth", "#shorts", "#viral"],
            ["curated-money-pack", "safer-money"],
        ),
        _topic(
            "How Huge Companies Actually Got Richer",
            "Big companies usually win through systems, not one magic moment.",
            [
                "Scale often beats brilliance because distribution can multiply ordinary products.",
                "Owning the platform can matter more than owning the trend.",
                "Recurring revenue changes how aggressively a company can grow.",
                "Brand trust lets some businesses charge more for nearly the same thing.",
                "The richest companies usually combine timing, capital, and ruthless execution.",
            ],
            "Follow for money and business breakdowns in under a minute.",
            ["#money", "#business", "#companies", "#shorts", "#viral"],
            ["curated-company-wealth-pack"],
        ),
    ],
    ContentNiche.AI: [
        _topic(
            "AI Tools That Make Old Workflows Look Ancient",
            "Some AI tools are not hype, they just remove boring work fast.",
            [
                "Summarization tools can turn long research into usable notes in minutes.",
                "Transcription tools save hours when audio would otherwise need manual typing.",
                "Image generation speeds up concept work before final design starts.",
                "Code assistants are most useful for drafts, tests, and repetitive edits.",
                "The biggest AI productivity gain often comes from cutting friction, not replacing people.",
            ],
            "Follow for AI content that is useful before it is flashy.",
            ["#ai", "#aitools", "#productivity", "#shorts", "#viral"],
            ["curated-ai-tools-pack"],
        ),
        _topic(
            "Future Tech Predictions That Might Arrive Sooner Than Expected",
            "A few future-tech ideas already exist in rough form right now.",
            [
                "Robots are improving fastest in repetitive environments with clear physical rules.",
                "Voice interfaces keep getting better because models now handle context more naturally.",
                "Personalized software agents may become normal before fully autonomous robots do.",
                "New inventions often feel slow for years and then suddenly feel everywhere.",
                "The real future shock is usually boring infrastructure becoming normal.",
            ],
            "Follow for future-tech videos without fake sci-fi promises.",
            ["#ai", "#futuretech", "#robots", "#shorts", "#viral"],
            ["curated-future-tech-pack"],
        ),
    ],
    ContentNiche.TECH: [
        _topic(
            "Tech Facts Most People Never Hear",
            "A few tech facts make modern devices feel even stranger.",
            [
                "Your phone can do billions of operations while fitting in your pocket.",
                "Internet speed problems often come from the local network, not the app you blame.",
                "Some data centers use climate and geography as part of their cooling strategy.",
                "Compression is one reason huge media libraries can stream so smoothly.",
                "The smartest tech feels simple only because the complexity is hidden well.",
            ],
            "Follow for tech facts without the usual recycled myths.",
            ["#tech", "#facts", "#innovation", "#shorts", "#viral"],
            ["curated-tech-pack"],
        ),
        _topic(
            "Crazy Inventions That Sound Fake",
            "Some inventions feel too strange to be real, but they solve real problems.",
            [
                "Engineers have built robots that inspect pipes where humans cannot fit safely.",
                "Special materials can change behavior dramatically under heat, pressure, or light.",
                "Some rescue tools are designed to work in smoke, darkness, or flooding.",
                "Inventors often combine old ideas in unusual ways instead of discovering magic.",
                "The wildest inventions usually start as niche tools before anyone calls them genius.",
            ],
            "Follow for more invention stories that are weird and real.",
            ["#tech", "#inventions", "#engineering", "#shorts", "#viral"],
            ["curated-inventions-pack"],
        ),
    ],
    ContentNiche.CRIME: [
        _topic(
            "Biggest Heists That Still Feel Unreal",
            "The wildest robberies worked because planning beat panic.",
            [
                "Some major heists succeeded by blending into normal routines instead of using force.",
                "Inside knowledge often matters more than movie-style action.",
                "A few robberies became famous because the escape was smarter than the theft.",
                "Criminal psychology often reveals overconfidence right before mistakes appear.",
                "The best true-crime stories are usually systems failures, not supervillains.",
            ],
            "Follow for crime stories told without glamorizing the criminals.",
            ["#crime", "#heist", "#mystery", "#shorts", "#viral"],
            ["curated-crime-pack", "non-glamorized"],
        ),
        _topic(
            "Prison Escapes That Changed Security Forever",
            "Some prison escape stories became legendary because they exposed impossible weaknesses.",
            [
                "Several famous escapes depended on routine being more predictable than the walls.",
                "Homemade tools and patience often mattered more than strength.",
                "A few cases still spark debate because no clear ending was ever confirmed publicly.",
                "Security systems usually change fastest after one embarrassment everyone remembers.",
                "The strangest escape stories are really stories about blind spots.",
            ],
            "Follow for more crime breakdowns with the hype stripped out.",
            ["#crime", "#prisonescape", "#stories", "#shorts", "#viral"],
            ["curated-prison-pack", "careful-framing"],
        ),
    ],
    ContentNiche.MYTHOLOGY: [
        _topic(
            "Greek Myths That Are Darker Than People Remember",
            "Classroom mythology leaves out how brutal some stories really are.",
            [
                "Many Greek myths were warnings about pride, obsession, and power.",
                "Monsters in myth often represented human fears more than random evil.",
                "Heroes were not always noble, and that is part of why the stories lasted.",
                "Different versions of the same myth changed across regions and centuries.",
                "Mythology survives because symbols stay powerful even when details change.",
            ],
            "Follow for mythology stories told like stories, not homework.",
            ["#mythology", "#greekmythology", "#legends", "#shorts", "#viral"],
            ["curated-mythology-pack"],
        ),
        _topic(
            "Legends About Demons And Monsters Around The World",
            "Nearly every culture built monsters out of its deepest fears.",
            [
                "Some monsters were created to explain danger before science could.",
                "River spirits, forest beings, and night creatures often reflect local hazards.",
                "Japanese legends, Norse stories, and South Asian folklore all treat the unknown differently.",
                "A monster becomes memorable when it also teaches a social rule.",
                "The oldest legends survive because fear and wonder never go out of style.",
            ],
            "Follow for world mythology and darker folklore.",
            ["#mythology", "#legends", "#monsters", "#shorts", "#viral"],
            ["curated-world-legends-pack"],
        ),
    ],
    ContentNiche.SURVIVAL: [
        _topic(
            "What If You Were Stuck In A Disaster Zone",
            "Most survival mistakes happen before people realize the situation is serious.",
            [
                "Panic burns time and energy faster than most people expect.",
                "Shelter, clean water, and communication usually beat dramatic hero moves.",
                "Weather and terrain become more dangerous when you are tired and improvising.",
                "Simple preparation often matters more than expensive survival gear.",
                "The best survival lesson is learning what not to do first.",
            ],
            "Follow for survival content that stays practical and watchable.",
            ["#survival", "#whatif", "#disaster", "#shorts", "#viral"],
            ["curated-survival-pack"],
        ),
        _topic(
            "Dangerous Places On Earth That Do Not Look Real",
            "Some places are stunning right up until you learn why they are dangerous.",
            [
                "Extreme weather zones can flip from calm to deadly with very little warning.",
                "Certain lakes, deserts, and mountains punish small mistakes immediately.",
                "Some locations are dangerous because rescue is harder than people assume.",
                "Heat, altitude, and isolation can become worse than obvious threats.",
                "The planet keeps teaching the same lesson: beautiful does not mean safe.",
            ],
            "Follow for more extreme-world and survival-style videos.",
            ["#survival", "#dangerousplaces", "#earth", "#shorts", "#viral"],
            ["curated-dangerous-places-pack"],
        ),
    ],
    ContentNiche.ANIMALS: [
        _topic(
            "Dangerous Animals That Do Not Look That Scary",
            "Some of the most dangerous animals win by looking harmless at first.",
            [
                "Small venomous creatures can be more dangerous than larger predators in the wrong setting.",
                "Territorial animals often become risky when humans misread distance and warning signs.",
                "Sea creatures can injure people because they are nearly invisible until too late.",
                "Animal danger is often about habitat, surprise, and human overconfidence.",
                "Nature does not always advertise its worst features.",
            ],
            "Follow for animal content that is wild without being fake.",
            ["#animals", "#dangerousanimals", "#nature", "#shorts", "#viral"],
            ["curated-animal-danger-pack"],
        ),
        _topic(
            "Weird Sea Creatures That Look Computer Generated",
            "The ocean keeps producing animals that look like design mistakes.",
            [
                "Some deep-sea creatures evolved transparent or glowing bodies to survive darkness.",
                "Pressure, cold, and lack of light create survival traits that look unreal.",
                "Certain fish use bioluminescence as bait, defense, or camouflage.",
                "A lot of sea life still surprises scientists because deep exploration is hard.",
                "Ocean creatures look alien mostly because their world is so different from ours.",
            ],
            "Follow for more strange animal discoveries from land and sea.",
            ["#animals", "#ocean", "#seacreatures", "#shorts", "#viral"],
            ["curated-sea-creatures-pack"],
        ),
    ],
    ContentNiche.BODY: [
        _topic(
            "Brain Facts That Make You Question Yourself",
            "Your brain is doing a lot more behind the scenes than you think.",
            [
                "Memory is reconstructed more than replayed, which is why confidence can be misleading.",
                "Your brain filters massive amounts of sensory input before you notice it consciously.",
                "Sleep affects attention, emotion, and memory more than most people admit.",
                "Habits save energy by letting the brain automate repeated behavior.",
                "A lot of what feels like personality is also pattern and chemistry.",
            ],
            "Follow for brain and body facts that stay grounded.",
            ["#brainfacts", "#humanbody", "#science", "#shorts", "#viral"],
            ["curated-brain-pack"],
        ),
        _topic(
            "Sleep Facts Most People Learn Too Late",
            "A surprising amount of your day is controlled by how you sleep at night.",
            [
                "Sleep debt can build quietly even when you feel functional.",
                "Light exposure helps tell your body when to feel alert or sleepy.",
                "Poor sleep can distort hunger, focus, and emotional control.",
                "Dreams are still debated, but sleep itself is non-negotiable for recovery.",
                "The easiest health upgrade for many people is still better sleep timing.",
            ],
            "Follow for more human body content without fake miracle claims.",
            ["#sleepfacts", "#health", "#humanbody", "#shorts", "#viral"],
            ["curated-sleep-pack", "safer-health"],
        ),
    ],
    ContentNiche.CELEBRITY: [
        _topic(
            "Old Hollywood Stories That Still Feel Unreal",
            "Old Hollywood built legends so polished that the strange parts got buried.",
            [
                "Studios once shaped public images with a level of control that feels shocking now.",
                "Some stars changed names, accents, or entire backstories to fit the brand.",
                "Mystery, scandal, and reinvention were part of the machine from the start.",
                "The most famous stories survived because they mixed glamour with something darker.",
                "Old celebrity culture was often less transparent and more carefully staged than today.",
            ],
            "Follow for celebrity history told as stories, not gossip spam.",
            ["#celebrity", "#oldhollywood", "#history", "#shorts", "#viral"],
            ["curated-celebrity-pack", "safer-celebrity"],
        ),
        _topic(
            "Famous Transformations People Still Talk About",
            "Some public reinventions work because the story changes before the audience notices.",
            [
                "Image shifts usually combine timing, discipline, and a new narrative.",
                "Celebrity transformations spread fast because people love before-and-after stories.",
                "The strongest reinventions feel inevitable only after they succeed.",
                "Public figures often change style first, then message, then audience.",
                "A transformation becomes iconic when it rewrites what people expect from the person.",
            ],
            "Follow for more fame, image, and mystery-driven stories.",
            ["#celebrity", "#transformation", "#stories", "#shorts", "#viral"],
            ["curated-celebrity-transformations-pack"],
        ),
    ],
    ContentNiche.MOTIVATION: [
        _topic(
            "Discipline Beats Motivation",
            "Motivation gets attention, but discipline changes results.",
            [
                "Motivation is emotional, so it disappears fast when you are tired, stressed, or distracted.",
                "Discipline works better because it turns action into routine instead of waiting for the perfect mood.",
                "Small repeatable habits usually beat giant one-day efforts that never become consistent.",
                "The best system removes friction, so starting takes less energy than making excuses.",
                "You do not need to feel ready every day. You need a process that still works on average days.",
            ],
            "Follow DarkBrainScroll for mindset content that actually helps you act.",
            ["#motivation", "#discipline", "#mindset", "#shorts", "#viral"],
            ["curated-motivation-pack"],
        ),
        _topic(
            "Success Edits People Actually Need To Hear",
            "Most people do not need more hype. They need a harder truth.",
            [
                "Consistency looks boring before it looks impressive.",
                "Distraction is expensive because it steals momentum in tiny pieces.",
                "Confidence often comes after action, not before it.",
                "A strong routine beats a strong mood almost every time.",
                "Most success advice gets better when it becomes simpler and harder to dodge.",
            ],
            "Follow for motivation content with more action and less noise.",
            ["#motivation", "#success", "#sigma", "#shorts", "#viral"],
            ["curated-success-pack"],
        ),
    ],
    ContentNiche.GYM: [
        _topic(
            "Gym Motivation That Actually Helps",
            "Training gets easier when you stop expecting every day to feel epic.",
            [
                "Progress is usually hidden in months of ordinary work.",
                "Missing one day matters less than letting one day become a pattern.",
                "The best workout plan is the one you can repeat when life gets messy.",
                "Strength builds confidence because effort leaves evidence.",
                "Most people quit too early to meet the version of themselves they were building.",
            ],
            "Follow for gym motivation that respects reality.",
            ["#gym", "#motivation", "#discipline", "#shorts", "#viral"],
            ["curated-gym-pack"],
        ),
    ],
    ContentNiche.QUOTES: [
        _topic(
            "Stoic Quotes That Hit Harder With Age",
            "Some stoic lines sound simple until life forces you to understand them.",
            [
                "Control what you can and stop negotiating with what you cannot.",
                "Peace often comes from lowering chaos inside before fighting chaos outside.",
                "Discomfort stops feeling personal when you treat it like training.",
                "Attention is power because your focus shapes your days.",
                "A lot of modern stress is old human nature wearing new clothes.",
            ],
            "Follow for quote-based shorts that still say something real.",
            ["#stoic", "#quotes", "#mindset", "#shorts", "#viral"],
            ["curated-stoic-pack"],
        ),
    ],
    ContentNiche.THEORY: [
        _topic(
            "Internet Theories People Cannot Stop Talking About",
            "Some theories survive because they are emotionally satisfying, not because they are proven.",
            [
                "People trust theories faster when they explain confusing events with one clean story.",
                "Online communities can strengthen belief by repeating the same clues back to each other.",
                "Unexplained events invite pattern-seeking even when evidence is thin.",
                "A theory can feel persuasive long before it becomes credible.",
                "The safest way to cover internet theories is to separate fascination from fact.",
            ],
            "Follow for unexplained and theory-style content framed carefully.",
            ["#theories", "#internetmystery", "#unexplained", "#shorts", "#viral"],
            ["curated-theory-pack", "careful-framing"],
        ),
        _topic(
            "Unexplained Events People Still Debate",
            "Some stories stay alive because nobody can prove the neat version.",
            [
                "Witness memory, missing records, and dramatic retellings can all distort a real event.",
                "Famous unexplained stories often grow larger as details get repeated online.",
                "People tend to remember the eerie parts and forget the uncertain parts.",
                "That uncertainty is exactly why these events keep resurfacing.",
                "Interesting does not always mean verified, and that line matters.",
            ],
            "Follow for mystery content with labels instead of fake certainty.",
            ["#unexplained", "#mystery", "#theories", "#shorts", "#viral"],
            ["curated-unexplained-pack", "safer-misinformation"],
        ),
    ],
    ContentNiche.BUSINESS: [
        _topic(
            "Business Lessons Hidden Inside Viral Brands",
            "A lot of viral brands are really distribution stories in disguise.",
            [
                "Memorable branding reduces friction before the product even speaks.",
                "Fast feedback loops let small brands learn quicker than slower giants.",
                "Attention matters, but repeat customers matter more.",
                "Some brands grow because they know exactly who they are not for.",
                "Business gets clearer when you study why people buy, not just what they buy.",
            ],
            "Follow for sharper business breakdowns in short form.",
            ["#business", "#branding", "#marketing", "#shorts", "#viral"],
            ["curated-business-pack"],
        ),
    ],
    ContentNiche.REDDIT: [
        _topic(
            "Stories From The Internet That Escalated Fast",
            "Some internet stories go viral because every update makes them worse.",
            [
                "A believable first detail is often what hooks people before the wild part appears.",
                "Comment sections turn ordinary stories into community events.",
                "The best retellings keep the tension moving instead of overexplaining.",
                "Not every internet story is verifiable, which is why framing matters.",
                "People love stories that feel personal, chaotic, and slightly unbelievable.",
            ],
            "Follow for internet-story style content without pretending every post is gospel.",
            ["#stories", "#internet", "#redditstyle", "#shorts", "#viral"],
            ["curated-internet-story-pack", "careful-framing"],
        ),
    ],
    ContentNiche.DID_YOU_KNOW: [
        _topic(
            "Did You Know Facts That Sound Edited",
            "A few did-you-know facts are almost too weird for short-form video.",
            [
                "Some lakes can look pink because of algae and salt-loving microorganisms.",
                "There are deserts that can bloom dramatically after rare rainfall.",
                "A group of flamingos is called a flamboyance, which sounds invented but is real.",
                "Some metals can remember shapes under the right conditions.",
                "Nature and science are full of facts that already sound clickbait without help.",
            ],
            "Follow for more did-you-know content with less filler.",
            ["#didyouknow", "#facts", "#shorts", "#viral"],
            ["curated-didyouknow-pack"],
        ),
    ],
}


def _topic_candidates(niche: str) -> list[dict]:
    return TOPIC_LIBRARY.get(niche, TOPIC_LIBRARY[ContentNiche.FACTS])


def _extract_logged_title(log: EventLog) -> str:
    payload_title = (log.payload or {}).get("title", "").strip()
    if payload_title:
        return payload_title
    match = re.search(r"Project '(.+?)' was removed", log.message or "")
    if match:
        return match.group(1).strip()
    return ""


def _recently_used_titles(niche: str, limit: int = 40) -> list[str]:
    current_titles = list(ViralTopic.objects.filter(niche=niche).values_list("title", flat=True))
    log_titles: list[str] = []
    logs = EventLog.objects.filter(
        event_type__in=["project.created", "project.deleted", "publish.success"]
    ).order_by("-created_at")[:limit]
    for log in logs:
        title = _extract_logged_title(log)
        if title:
            log_titles.append(title)
    seen: list[str] = []
    for title in [*current_titles, *log_titles]:
        if title and title not in seen:
            seen.append(title)
    return seen


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
    candidates = _topic_candidates(niche)
    recent_titles = _recently_used_titles(niche)
    recently_used = set(recent_titles)
    latest_title = recent_titles[0] if recent_titles else ""
    unused_candidates = [candidate for candidate in candidates if candidate["title"] not in recently_used]
    if unused_candidates:
        preferred_pool = [candidate for candidate in unused_candidates if candidate["title"] != latest_title]
        template = random.choice(preferred_pool or unused_candidates)
    else:
        recency_index = {title: index for index, title in enumerate(recent_titles)}
        non_latest_candidates = [candidate for candidate in candidates if candidate["title"] != latest_title] or candidates
        template = max(non_latest_candidates, key=lambda candidate: recency_index.get(candidate["title"], len(candidates) + 100))
    hook = template["hook"]
    beats = list(template["beats"])
    max_scenes = max(3, int(getattr(settings, "MAX_SCENES_PER_VIDEO", 5)))
    max_beats = max(1, max_scenes - 2)
    beats = beats[:max_beats]
    cta = template["cta"]
    title = template["title"]
    script_lines = [hook, *beats, cta]
    script = "\n".join(script_lines)
    scene_plan = build_scene_plan(hook, beats, cta)
    duration_seconds = estimate_duration_seconds(script, scene_plan)
    content_signature = stable_hash([niche, title.strip().lower(), " ".join(script.lower().split())])
    return ViralTopic.objects.create(
        niche=niche,
        title=title,
        hook=hook,
        script=script,
        scene_plan=scene_plan,
        seo_title=f"{title} | DarkBrainScroll",
        description=script,
        hashtags=template.get("hashtags", [f"#{niche}", "#shorts", "#viral"]),
        source_notes=[*template.get("source_notes", []), f"estimated-duration:{duration_seconds}", f"content-signature:{content_signature}"],
        is_trending=False,
    )
