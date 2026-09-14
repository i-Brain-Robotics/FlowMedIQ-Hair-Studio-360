"""Hair Studio 360: deterministic, region-matched planning arithmetic.

Density defaults are the owner's requested scenarios, not efficacy guarantees.
Count and density are the SAME endpoint over a fixed measured area. They must
never be added or multiplied as independent gains. Diameter is not converted
into graft savings. All graft comparisons use the same horizon and yield.
"""
from copy import deepcopy
from math import ceil, isfinite

LASER_SOURCE = 'https://doi.org/10.1111/jocd.16173'
TED_SOURCE = 'https://almainc.com/product/alma-ted/'
PROTOCOLS = {
    'laser': {
        'label': '1565 nm Er:glass laser', 'density_mode': 'absolute',
        'density_default': 14, 'density_range': [13, 15],
        'diameter_default_um': 6.5, 'diameter_range_um': [5, 8],
        'diameter_default_percent': 18.5, 'diameter_range_percent': [15, 22],
        'density_note': 'Owner-supplied six-month scenario: +13–15 terminal hairs/cm².',
        'diameter_note': 'Owner-supplied six-month scenario: +5–8 μm OR +15–22%. These ranges are alternative models, not equivalent for every baseline. Direct 1565 nm reference: Qu et al. (2024), +2.38 μm at week 10; related 1550 nm Lee et al. study: 58 → 75 μm over 5 months. Neither validates this exact six-month preset for 1565 nm.',
        'sources': [LASER_SOURCE],
    },
    'ultrasound': {
        'label': '40 kHz ultrasound + serum', 'density_mode': 'percent',
        'density_default': 31, 'density_range': [31, 31],
        'diameter_default_um': 12.5, 'diameter_range_um': [10, 15],
        'diameter_default_percent': 37, 'diameter_range_percent': [30, 44],
        'density_note': 'Owner-supplied scenario: +31% at month 6. Alma reports +23% at month 1 and +31% at month 6 for its specific TED/serum protocol (N=31; data on file). Applying it to another device or serum is an assumption.',
        'diameter_note': 'Owner-supplied six-month scenario: +10–15 μm OR +30–44%. These numerical thickness ranges were not verified in a primary study for the exact device/serum; use as assumptions, not established efficacy.',
        'sources': [TED_SOURCE],
    },
    'combined': {
        'label': 'Laser + ultrasound + serum', 'density_mode': 'percent',
        'density_default': 37.5, 'density_range': [35, 40],
        'diameter_default_um': 21.5, 'diameter_range_um': [18, 25],
        'diameter_default_percent': 52.5, 'diameter_range_percent': [45, 60],
        'density_note': 'Owner-supplied six-month scenario: +35–40% relative to baseline density. Default 37.5% is the midpoint, not a study mean. This replaces the standalone gains; they are not compounded.',
        'diameter_note': 'Owner-supplied six-month scenario: +18–25 μm OR +45–60%. The plus signs in the supplied ranges do not define an upper bound; this preset uses 25 μm / 60% as editable scenario endpoints. No combined-protocol primary study verifies these ranges. Do not add the standalone gains.',
        'sources': [LASER_SOURCE, TED_SOURCE],
    },
}


def number(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number.')
    if not isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f'{name} must be between {minimum:g} and {maximum:g}.')
    return float(value)


def calculate(payload, graft_counts, area_names):
    if not isinstance(payload, dict):
        raise ValueError('Send a scenario object.')
    protocol_key = payload.get('protocol', 'combined')
    if not isinstance(protocol_key, str) or protocol_key not in PROTOCOLS:
        raise ValueError('Choose laser, ultrasound, or combined.')
    protocol = deepcopy(PROTOCOLS[protocol_key])
    growth = number(payload.get('density_change', protocol['density_default']), 'Density change', 0, 200)
    diameter_mode = payload.get('diameter_mode', 'absolute')
    if diameter_mode not in ('absolute', 'percent'):
        raise ValueError('Choose absolute or percent diameter change.')
    diameter_default = protocol['diameter_default_um'] if diameter_mode == 'absolute' else protocol['diameter_default_percent']
    diameter_change = number(payload.get('diameter_change', payload.get('diameter_gain_um', diameter_default)), 'Diameter change', 0, 200)
    hpg = number(payload.get('hairs_per_graft', 2), 'Hairs per graft', 1, 4)
    survival = number(payload.get('graft_survival_percent', 90), 'Graft survival', 1, 100) / 100
    horizon = payload.get('horizon', 'six_months')
    if horizon not in ('six_months', 'mature'):
        raise ValueError('Choose six_months or mature comparison.')
    visible = number(payload.get('visible_growth_percent', 60), 'Visible graft growth', 1, 100) / 100 if horizon == 'six_months' else 1
    effective_hairs = hpg * survival * visible
    raw_zones = payload.get('zones')
    if not isinstance(raw_zones, list) or not 1 <= len(raw_zones) <= len(graft_counts):
        raise ValueError('Select at least one valid treatment zone.')
    zones = []
    seen = set()
    for raw in raw_zones:
        if not isinstance(raw, dict):
            raise ValueError('Each zone must be an object.')
        key = raw.get('area')
        level = raw.get('density', 'moderate')
        if not isinstance(key, str) or not isinstance(level, str) or key not in graft_counts or key in seen or level not in graft_counts[key]:
            raise ValueError('Invalid or duplicate zone/density selection.')
        seen.add(key)
        area = number(raw.get('area_cm2'), 'Measured zone area (cm²)', .1, 200)
        density = number(raw.get('baseline_density'), 'Baseline terminal hair density', 0, 400)
        diameter = number(raw.get('baseline_diameter_um'), 'Baseline terminal hair diameter', 10, 200)
        eligible = number(raw.get('responsive_percent', 100), 'Responsive portion of zone', 0, 100) / 100
        grafts = number(raw.get('grafts', graft_counts[key][level]), 'Transplant grafts', 0, 10000)
        if grafts != int(grafts):
            raise ValueError('Transplant grafts must be a whole number.')
        grafts = int(grafts)
        # No automatic regrowth in a zone with no measured terminal hair.
        responsive = eligible if density > 0 else 0
        delta_density = (growth if protocol['density_mode'] == 'absolute' else density * growth / 100) * responsive
        baseline_hairs = area * density
        added_hairs = area * delta_density
        diameter_gain = diameter_change if diameter_mode == 'absolute' else diameter * diameter_change / 100
        new_diameter = diameter + diameter_gain * responsive if baseline_hairs else None
        surgical_hairs = grafts * effective_hairs
        # Round UP within each region; crown gains cannot replace hairline grafts.
        combined_grafts = max(0, min(grafts, ceil((surgical_hairs - added_hairs) / effective_hairs - 1e-10)))
        combined_hairs = baseline_hairs + added_hairs + combined_grafts * effective_hairs
        zones.append({
            'area': key, 'label': area_names[key], 'density': level, 'area_cm2': area,
            'responsive_percent': responsive * 100, 'baseline_hairs': baseline_hairs,
            'baseline_density': density, 'baseline_diameter_um': diameter if baseline_hairs else None,
            'added_hairs': added_hairs, 'density_gain': delta_density,
            'nonsurgical_hairs': baseline_hairs + added_hairs,
            'nonsurgical_density': density + delta_density, 'nonsurgical_diameter_um': new_diameter,
            'transplant_grafts': grafts, 'transplant_added_hairs': surgical_hairs,
            'transplant_hairs': baseline_hairs + surgical_hairs,
            'transplant_density': density + surgical_hairs / area,
            'combined_grafts': combined_grafts, 'grafts_saved': grafts - combined_grafts,
            'combined_hairs': combined_hairs, 'combined_density': combined_hairs / area,
            'target_excess_hairs': combined_hairs - (baseline_hairs + surgical_hairs),
        })
    area = sum(z['area_cm2'] for z in zones)
    if area > 600:
        raise ValueError('Total measured treatment area must not exceed 600 cm².')
    totals = {k: sum(z[k] for z in zones) for k in (
        'baseline_hairs', 'added_hairs', 'nonsurgical_hairs', 'transplant_grafts',
        'transplant_added_hairs', 'transplant_hairs', 'combined_grafts', 'grafts_saved', 'combined_hairs')}
    totals['area_cm2'] = area
    for kind in ('baseline', 'nonsurgical', 'transplant', 'combined'):
        totals[kind + '_density'] = totals[kind + '_hairs'] / area
    for kind in ('baseline', 'nonsurgical'):
        total_hairs = totals[kind + '_hairs']
        totals[kind + '_diameter_um'] = (sum((z[kind + '_diameter_um'] or 0) * z[kind + '_hairs'] for z in zones) / total_hairs) if total_hairs else None
    totals['nonsurgical_grafts'] = 0
    totals['grafts_saved_percent'] = totals['grafts_saved'] / totals['transplant_grafts'] * 100 if totals['transplant_grafts'] else 0
    return {
        'protocol': protocol_key, 'protocol_info': protocol, 'horizon': horizon,
        'density_change': growth, 'diameter_mode': diameter_mode, 'diameter_change': diameter_change,
        'hairs_per_graft': hpg, 'graft_survival_percent': survival * 100,
        'visible_growth_percent': visible * 100, 'effective_hairs_per_graft': effective_hairs,
        'zones': zones, 'totals': totals,
        'notes': [
            'Illustrative planning scenario, not a patient-specific prediction or treatment recommendation.',
            'Baseline measurements and treatment response are entered assumptions; they are not measured from the photograph.',
            'Graft savings meet or exceed the estimated terminal hair count target in the same regions and at the selected horizon. Equal cosmetic results are not established.',
            'Shaft thickening is reported separately and does not reduce graft requirements. Transplanted-hair diameter is not predicted.',
            'Six-month graft visibility and survival are editable assumptions, not established defaults for an individual.',
            'A zone with no baseline terminal hairs receives no automatic non-surgical gain in this model.',
        ],
    }
