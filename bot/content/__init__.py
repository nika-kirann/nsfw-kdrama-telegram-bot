"""Content pools. All characters are fictional, consenting adults (25+). Add lines freely."""
import random
from . import scenes, characters, episodes, dirty_talk

MODES = {
    "scene": ("🔥 Spicy Scene", scenes.SCENES),
    "episode": ("🎬 Episode Drop", episodes.EPISODES),
    "dirty": ("💋 Dirty Talk Drama", dirty_talk.LINES),
}


def random_from(mode: str) -> str:
    return random.choice(MODES[mode][1])
