"""Competitive podium rewards. Practice never awards podium bonuses or medals."""
PODIUM={
    1:dict(medal='gold',label='Gold',bonus=1000,color=(244,185,65)),
    2:dict(medal='silver',label='Silver',bonus=600,color=(192,207,222)),
    3:dict(medal='bronze',label='Bronze',bonus=300,color=(202,139,89)),
}


def podium_reward(place,practice=False):
    if practice or place not in PODIUM:
        return dict(medal=None,label='',bonus=0,color=(225,235,243))
    return dict(PODIUM[place])
