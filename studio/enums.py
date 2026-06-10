from django.db import models


class ContentNiche(models.TextChoices):
    DARK_CURIOSITY = "dark-curiosity", "Dark Curiosity"
    CARS = "cars", "Cars"
    TOP_10_CARS = "top-10-cars", "Top 10 Cars"
    LUXURY_CARS = "luxury-cars", "Luxury Cars"
    SUPERCARS = "supercars", "Supercars"
    CAR_FACTS = "car-facts", "Car Facts"
    CAR_NEWS = "car-news", "Car Launches & News"
    CELEBRITY_GOSSIP = "celebrity-gossip", "Celebrity Gossip"
    FACTS = "facts", "Facts"
    MOTIVATION = "motivation", "Motivation"
    TECH = "tech", "Tech Facts"
    BUSINESS = "business", "Business Tips"
    HORROR = "horror", "Horror Stories"
    REDDIT = "reddit", "Reddit Stories"
    AI = "ai", "AI Facts"
    MONEY = "money", "Money Tips"
    GYM = "gym", "Gym Motivation"
    QUOTES = "quotes", "Quotes"
    SPACE = "space", "Space & Universe"
    PSYCHOLOGY = "psychology", "Psychology"
    CRIME = "crime", "Crime Stories"
    MYTHOLOGY = "mythology", "Mythology"
    SURVIVAL = "survival", "Survival"
    CUTE_ANIMALS = "cute-animals", "Cute Animals"
    ANIMALS = "animals", "Animal Facts"
    ANIMAL_FACTS = "animal-facts", "Wild Animal Facts"
    BODY = "body", "Human Body"
    CELEBRITY = "celebrity", "Celebrity Stories"
    CELEBRITY_FACTS = "celebrity-facts", "Celebrity Facts"
    GLAM = "glam", "Glam & Dance"
    DANCE = "dance", "Dance Trends"
    STORY = "story", "Storytelling"
    MEME = "meme", "Meme Content"
    THEORY = "theory", "Internet Theories"
    DID_YOU_KNOW = "did-you-know", "Did You Know"


class JobStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    QUEUED = "queued", "Queued"
    GENERATING = "generating", "Generating"
    READY = "ready", "Ready"
    POSTING = "posting", "Posting"
    POSTED = "posted", "Posted"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class PlatformType(models.TextChoices):
    YOUTUBE = "youtube", "YouTube Shorts"
    INSTAGRAM = "instagram", "Instagram Reels"
    PINTEREST = "pinterest", "Pinterest Idea Pins"


class AssetType(models.TextChoices):
    IMAGE = "image", "Image"
    AUDIO = "audio", "Audio"
    VIDEO = "video", "Video"
    SUBTITLE = "subtitle", "Subtitle"
    MUSIC = "music", "Music"
