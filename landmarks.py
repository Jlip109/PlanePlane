"""World landmarks: data shared by the world, renderer, game modes and HUD.

Districts are themed areas of the world (never shown to the player by a city name); each holds
one or two real-world landmarks at real scale. Positions are world metres: x east, z north.
"""

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Landmark:
    key: str
    name: str
    district: str
    x: float
    z: float
    height: float          # metres above its base, tallest point
    radius: float          # footprint radius in metres (proximity, rings, collisions)
    heading: float = 0.0   # rotation of the model about the vertical axis, radians
    facts: tuple = field(default=())


# Themed districts: key -> (centre x, centre z, radius). The world module builds them.
DISTRICTS = {
    'nyc': (0.0, 4200.0, 1700.0),
    'london': (6800.0, 7600.0, 1300.0),
    'paris': (11800.0, 1800.0, 1400.0),
    'giza': (7200.0, -6200.0, 1500.0),
    'dubai': (-6200.0, -4600.0, 1600.0),
}

LANDMARKS = [
    Landmark('liberty', 'Statue of Liberty', 'nyc', -1500.0, 2500.0, 93.0, 45.0, facts=(
        'Lady Liberty was a gift from France, dedicated in 1886.',
        'Her copper skin is only about 2.4 millimetres thick. The green is patina.',
        'Gustave Eiffel, of the Eiffel Tower, designed her iron skeleton.',
    )),
    Landmark('empire_state', 'Empire State Building', 'nyc', 0.0, 4300.0, 443.0, 70.0, facts=(
        'Opened in 1931 after only about 410 days of construction.',
        'It stands 443 metres to the tip of its antenna, with 102 floors.',
        'Its tower lights change colour to mark holidays and events.',
    )),
    Landmark('big_ben', 'Big Ben', 'london', 6500.0, 7500.0, 96.0, 12.0, facts=(
        'Big Ben is really the name of the great bell. The tower is the Elizabeth Tower.',
        'The tower is 96 metres tall and was completed in 1859.',
        'The great bell weighs about 13.7 tonnes.',
    )),
    Landmark('london_eye', 'London Eye', 'london', 7050.0, 7350.0, 135.0, 70.0, facts=(
        'The London Eye opened in 2000 and stands 135 metres tall.',
        'It has 32 capsules, one for each London borough.',
        'One full turn takes about 30 minutes.',
    )),
    Landmark('eiffel', 'Eiffel Tower', 'paris', 11800.0, 1700.0, 330.0, 65.0, facts=(
        'Built for the 1889 World’s Fair, it was the tallest structure on Earth until 1930.',
        'In summer heat the iron expands and the tower can grow about 15 centimetres.',
        'It is repainted roughly every seven years, using about 60 tonnes of paint.',
    )),
    Landmark('arc', 'Arc de Triomphe', 'paris', 12500.0, 2300.0, 50.0, 30.0, facts=(
        'Napoleon commissioned the arch in 1806. It was finished in 1836.',
        'Twelve avenues meet at the star-shaped plaza around it.',
        'The Tomb of the Unknown Soldier has lain beneath it since 1921.',
    )),
    Landmark('pyramids', 'Pyramids of Giza', 'giza', 7200.0, -6300.0, 139.0, 240.0, facts=(
        'The Great Pyramid was built for Pharaoh Khufu around 2560 BC.',
        'It was the tallest human-made structure for about 3,800 years.',
        'It is the only one of the Seven Wonders of the Ancient World still standing.',
    )),
    Landmark('sphinx', 'Great Sphinx', 'giza', 7650.0, -5850.0, 20.0, 40.0, facts=(
        'The Sphinx is about 73 metres long and 20 metres high.',
        'It was carved from a single mass of limestone bedrock.',
        'Most historians link it to Pharaoh Khafre, around 2500 BC.',
    )),
    Landmark('burj_khalifa', 'Burj Khalifa', 'dubai', -6200.0, -4500.0, 828.0, 60.0, facts=(
        'At 828 metres, the Burj Khalifa has been the world’s tallest building since 2010.',
        'On a clear day its spire can be seen from about 95 kilometres away.',
        'Its Y-shaped floor plan was inspired by the desert flower Hymenocallis.',
    )),
    Landmark('burj_al_arab', 'Burj Al Arab', 'dubai', -7400.0, -5600.0, 321.0, 50.0, facts=(
        'The Burj Al Arab stands on its own artificial island, built just offshore.',
        'Its shape was designed to look like the sail of a dhow.',
        'In 2005 two tennis legends played a match on its helipad, 211 metres up.',
    )),
]

BY_KEY = {landmark.key: landmark for landmark in LANDMARKS}


def nearest(x, z):
    """(landmark, horizontal distance in metres) closest to the point."""
    best = min(LANDMARKS, key=lambda landmark: (landmark.x - x) ** 2 + (landmark.z - z) ** 2)
    return best, math.hypot(best.x - x, best.z - z)


def district_at(x, z):
    """Key of the district containing the point, or None in open country."""
    for key, (cx, cz, radius) in DISTRICTS.items():
        if (x - cx) ** 2 + (z - cz) ** 2 < radius * radius:
            return key
    return None
