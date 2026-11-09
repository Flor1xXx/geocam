"""Обратное геокодирование: Область, Город, Улица, дом N (дом — только в радиусе 20 м)."""
import math
import requests

UA = {"User-Agent": "GeoCamApp/1.0 (komarovartem963@gmail.com)"}  # впишите свой e-mail
HOUSE_RADIUS_M = 20


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_house(lat, lon):
    """(street|None, number) ближайшего дома в радиусе 20 м или None."""
    q = f"""[out:json][timeout:10];
    (node(around:{HOUSE_RADIUS_M},{lat},{lon})["addr:housenumber"];
     way(around:{HOUSE_RADIUS_M},{lat},{lon})["addr:housenumber"];);
    out center tags;"""
    try:
        r = requests.post("https://overpass-api.de/api/interpreter",
                          data={"data": q}, headers=UA, timeout=12)
        els = r.json().get("elements", [])
    except Exception:
        return None
    best, best_d = None, 1e9
    for el in els:
        c = el if el["type"] == "node" else el.get("center")
        if not c:
            continue
        d = haversine(lat, lon, c["lat"], c["lon"])
        if d <= HOUSE_RADIUS_M and d < best_d:
            best, best_d = el, d
    if not best:
        return None
    t = best["tags"]
    return t.get("addr:street"), t["addr:housenumber"]


def reverse_geocode(lat, lon):
    """Строка адреса или None, если не удалось получить вообще ничего (нет сети)."""
    parts, street, ok = [], None, False
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18,
                    "addressdetails": 1, "accept-language": "ru"},
            headers=UA, timeout=12)
        a = r.json().get("address", {})
        ok = True
        if a.get("state"):
            parts.append(a["state"])
        city = (a.get("city") or a.get("town") or a.get("village")
                or a.get("hamlet") or a.get("municipality"))
        if city:
            parts.append(city)
        street = a.get("road")
    except Exception:
        pass

    house = nearest_house(lat, lon)
    if house and house[0]:
        street = house[0]
    if street:
        parts.append(street)
    if house:
        parts.append(f"дом {house[1]}")
    if not ok and not house:
        return None
    return ", ".join(parts)
