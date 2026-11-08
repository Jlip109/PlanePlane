"""Tropospheric temperature anchored to a location's observed surface weather.

The 6.5 C/km standard lapse rate is a simplified atmosphere, not a forecast of
inversions. See NASA Glenn's Earth Atmosphere Equation (Metric).
Fuel adjustment is deliberately modest game balancing, not an engine model.
"""

LAPSE_C_PER_METRE = .0065
TROPOPAUSE_METRES = 11000.0


def at_altitude(surface_f, altitude_metres, reference_metres=0):
    if surface_f is None:
        return None
    height = min(max(altitude_metres,0),TROPOPAUSE_METRES)
    reference = min(max(reference_metres,0),TROPOPAUSE_METRES)
    return surface_f - (height-reference)*LAPSE_C_PER_METRE*1.8


def fuel_multiplier(air_temperature_f):
    if air_temperature_f is None:
        return 1.0
    return max(.94,min(1.12,1+(air_temperature_f-59)*.0015))
