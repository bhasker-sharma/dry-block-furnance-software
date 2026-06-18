from typing import List, Optional


def interpolate_cmc(cmc_points: List[dict], temperature: float) -> Optional[float]:
    """
    Linearly interpolate the CMC value for a given temperature between the
    two nearest configured CMC points (entered at multiples of 100).
    Returns None if no CMC points are configured.
    """
    if not cmc_points:
        return None
    pts = sorted(cmc_points, key=lambda p: p['temperature'])
    if temperature <= pts[0]['temperature']:
        return pts[0]['cmc']
    if temperature >= pts[-1]['temperature']:
        return pts[-1]['cmc']
    for a, b in zip(pts, pts[1:]):
        if a['temperature'] <= temperature <= b['temperature']:
            span = b['temperature'] - a['temperature']
            if span == 0:
                return a['cmc']
            frac = (temperature - a['temperature']) / span
            return round(a['cmc'] + frac * (b['cmc'] - a['cmc']), 3)
    return pts[-1]['cmc']
