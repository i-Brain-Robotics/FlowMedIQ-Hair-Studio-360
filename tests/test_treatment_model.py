import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from treatment_model import calculate, PROTOCOLS

COUNTS = {'area2': {'moderate': 1000}, 'area4': {'moderate': 900}}
NAMES = {'area2': 'Hairline', 'area4': 'Mid-scalp'}

def scenario():
    return {'protocol': 'ultrasound', 'horizon': 'mature', 'zones': [
        {'area': 'area2', 'area_cm2': 50, 'baseline_density': 100,
         'baseline_diameter_um': 50, 'grafts': 2000}]}

class TreatmentModelTests(unittest.TestCase):
    def test_count_density_and_grafts_are_consistent(self):
        r=calculate(scenario(), COUNTS, NAMES)['totals']
        self.assertEqual(r['baseline_hairs'], 5000)
        self.assertEqual(r['added_hairs'], 1550)
        self.assertEqual(r['nonsurgical_density'], 131)
        self.assertEqual(r['combined_grafts'], 1139)
        self.assertEqual(r['grafts_saved'], 861)
        self.assertGreaterEqual(r['combined_hairs'], r['transplant_hairs'])
        self.assertLess(r['combined_hairs']-r['transplant_hairs'], 1.8)

    def test_laser_is_absolute_combined_is_not_compounded(self):
        p=scenario();p['protocol']='laser'
        self.assertEqual(calculate(p,COUNTS,NAMES)['totals']['added_hairs'],700)
        p['protocol']='combined'
        self.assertEqual(calculate(p,COUNTS,NAMES)['totals']['added_hairs'],1875)

    def test_thickness_cannot_create_graft_savings(self):
        p=scenario();p['density_change']=0;p['diameter_gain_um']=50
        r=calculate(p,COUNTS,NAMES)['totals']
        self.assertEqual(r['grafts_saved'],0)
        self.assertEqual(r['nonsurgical_diameter_um'],100)

    def test_gain_cannot_move_between_regions(self):
        p=scenario();p['zones'][0]['grafts']=10
        p['zones'].append({'area':'area4','area_cm2':50,'baseline_density':0,'baseline_diameter_um':50,'grafts':900})
        r=calculate(p,COUNTS,NAMES)
        self.assertEqual(r['zones'][1]['combined_grafts'],900)
        self.assertEqual(r['totals']['grafts_saved'],10)

    def test_bald_or_nonresponsive_zone_has_no_automatic_gain(self):
        for k,v in [('baseline_density',0),('responsive_percent',0)]:
            p=scenario();p['protocol']='laser';p['zones'][0][k]=v
            self.assertEqual(calculate(p,COUNTS,NAMES)['totals']['added_hairs'],0)

    def test_six_month_horizon_applies_to_both_surgery_paths(self):
        p=scenario();p.update(horizon='six_months',visible_growth_percent=60)
        r=calculate(p,COUNTS,NAMES)
        self.assertAlmostEqual(r['effective_hairs_per_graft'],1.08)
        self.assertGreaterEqual(r['totals']['combined_hairs'],r['totals']['transplant_hairs'])

    def test_invalid_or_duplicate_inputs_rejected(self):
        p=scenario();p['zones'].append(copy.deepcopy(p['zones'][0]))
        with self.assertRaises(ValueError):calculate(p,COUNTS,NAMES)
        for value in [None,True,'31',float('nan'),float('inf'),-1]:
            p=scenario();p['density_change']=value
            with self.assertRaises(ValueError):calculate(p,COUNTS,NAMES)

    def test_bounds_and_rounding_across_response_range(self):
        for growth in [0,13,14,15,31,35,37.5,40,100,200]:
            p=scenario();p['density_change']=growth
            r=calculate(p,COUNTS,NAMES)['totals']
            self.assertTrue(0<=r['combined_grafts']<=2000)
            self.assertGreaterEqual(r['combined_hairs']+1e-8,r['transplant_hairs'])

    def test_supplied_thickness_defaults_and_alternative_units(self):
        self.assertEqual(PROTOCOLS['laser']['diameter_default_um'],6.5)
        self.assertEqual(PROTOCOLS['ultrasound']['diameter_default_um'],12.5)
        self.assertEqual(PROTOCOLS['combined']['diameter_default_um'],21.5)
        p=scenario();p.update(diameter_mode='percent',diameter_change=30)
        self.assertEqual(calculate(p,COUNTS,NAMES)['totals']['nonsurgical_diameter_um'],65)
        p['diameter_mode']='absolute'
        self.assertEqual(calculate(p,COUNTS,NAMES)['totals']['nonsurgical_diameter_um'],80)

if __name__=='__main__':unittest.main()
