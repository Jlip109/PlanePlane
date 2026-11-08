"""A shared real-world location and a frozen local-time weather snapshot per race."""
from datetime import datetime
import json
import math
import random
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LOCATIONS = [('Karachi, Pakistan',24.8607,67.0011,'Asia/Karachi'),
             ('Saratoga Springs, NY',43.0831,-73.7851,'America/New_York'),
             ('Los Angeles, CA',34.0522,-118.2437,'America/Los_Angeles'),
             ('Nuuk, Greenland',64.1835,-51.7216,'America/Nuuk'),
             ('Tokyo, Japan',35.6762,139.6503,'Asia/Tokyo'),
             ('Stockholm, Sweden',59.3293,18.0686,'Europe/Stockholm'),
             ('Cairo, Egypt',30.0444,31.2357,'Africa/Cairo'),
             ('Darwin, Australia',-12.4634,130.8456,'Australia/Darwin'),
             ('Honolulu, Hawaii',21.3099,-157.8581,'Pacific/Honolulu')]


def race_environment(seed, location=None):
    place = next((p for p in LOCATIONS if p[0]==location),None) if location else random.Random(seed).choice(LOCATIONS)
    if place is None:
        raise ValueError('Unknown race location')
    label,lat,lon,zone = place
    now = datetime.now(ZoneInfo(zone))
    result = dict(label=label,latitude=lat,longitude=lon,timezone=zone,
                  hour=now.hour+now.minute/60,local_time=now.strftime('%H:%M'),
                  cover=.35,wind=0,wind_angle=0,precipitation=0,storm=0,live=False,condition='Unavailable')
    query = urllib.parse.urlencode(dict(latitude=lat,longitude=lon,timezone='auto',wind_speed_unit='ms',
        current='cloud_cover,wind_speed_10m,wind_direction_10m,precipitation,weather_code,temperature_2m,surface_pressure'))
    try:
        request = urllib.request.Request('https://api.open-meteo.com/v1/forecast?'+query,headers={'User-Agent':'PlanePlane/2'})
        with urllib.request.urlopen(request,timeout=8) as response:
            body = response.read(262145)
        if len(body)>262144:
            raise ValueError('Weather response too large')
        data = json.loads(body)['current']
        def value(key,low,high):
            v=data[key]
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v):
                raise ValueError('Bad weather value')
            return max(low,min(high,v))
        code=value('weather_code',0,99)
        result.update(cover=value('cloud_cover',0,100)/100,wind=value('wind_speed_10m',0,45),
            wind_angle=math.radians(value('wind_direction_10m',0,360)+180),
            precipitation=min(1,value('precipitation',0,100)/4),storm=float(code>=95),
            temperature_f=value('temperature_2m',-100,100)*1.8+32,
            pressure_inhg=value('surface_pressure',500,1200)*.029529983,live=True)
        result['condition']='Thunderstorm' if code>=95 else 'Snow' if 71<=code<=77 or code in (85,86) else 'Rain' if code>=51 or result['precipitation']>0 else 'Cloudy' if result['cover']>.3 else 'Clear'
    except (OSError,ValueError,KeyError,TypeError) as error:
        result['error']=str(error)[:120]
    return result
