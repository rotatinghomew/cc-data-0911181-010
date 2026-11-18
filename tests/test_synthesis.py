from pathlib import Path
import unittest

from app import synthesis
from app.service import dispatch
from app.storage import DataError, Store

DATA = Path(__file__).parents[1] / 'data'
ALL_STUDIES = ['S%d' % i for i in range(12)]


class SynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(DATA)
        cls.result = synthesis.synthesize(cls.store)

    def stratum(self, service, construct, followup):
        for row in self.result['strata']:
            if (row['service'], row['construct'], row['followup_weeks']) == (service, construct, followup):
                return row
        self.fail('stratum not found: %s %s %s' % (service, construct, followup))

    def test_direction_harmonised_before_pooling(self):
        row = self.stratum('support', 'burden', 0)
        self.assertTrue(all(e['estimate'] < 0 for e in row['effects']))
        self.assertTrue(all(e['benefit'] > 0 for e in row['effects']))
        self.assertGreater(row['pooled']['random']['benefit'], 0)

    def test_constructs_are_never_merged_into_one_total(self):
        pairs = {(s['construct'], s['scale']) for s in self.result['strata']}
        self.assertIn(('burden', 'burden-20'), pairs)
        self.assertIn(('confidence', 'conf-10'), pairs)
        self.assertFalse(self.result['grand_total']['computed'])

    def test_followups_are_separate_strata_not_extra_studies(self):
        week0 = self.stratum('support', 'burden', 0)
        week12 = self.stratum('support', 'burden', 12)
        self.assertEqual(week0['independent_populations'], 6)
        self.assertEqual(week12['independent_populations'], 6)
        self.assertIn('E0-0', {e['effect'] for e in week0['effects']})
        self.assertIn('E0-12', {e['effect'] for e in week12['effects']})

    def test_repeated_measurements_not_counted_as_independent(self):
        week0 = self.stratum('support', 'burden', 0)
        populations = [e['population'] for e in week0['effects']]
        self.assertEqual(len(populations), len(set(populations)))
        panels = [p for p in self.result['dependencies']
                  if p['type'] == 'repeated_measurements' and p['study'] == 'S0']
        self.assertEqual(len(panels), 1)
        panel = panels[0]
        self.assertEqual(set(panel['effects']), {'E0-0', 'E0-12'})
        self.assertFalse(panel['correlation_reported'])
        self.assertFalse(panel['counted_as_independent'])
        ses = [row['standard_error'] for row in panel['if_collapsed']['sensitivity']]
        self.assertEqual(ses, sorted(ses))
        self.assertLess(ses[0], ses[-1])

    def test_shared_control_same_scale_gets_sensitivity(self):
        panels = [p for p in self.result['dependencies']
                  if p['type'] == 'shared_control' and p['study'] == 'S3']
        self.assertEqual(len(panels), 1)
        panel = panels[0]
        self.assertEqual(set(panel['effects']), {'E3-0', 'E3-peer'})
        self.assertIsNotNone(panel['if_collapsed'])
        self.assertIn('conclusion_stable', panel['if_collapsed'])

    def test_incompatible_pair_is_retained_but_not_collapsed(self):
        panels = [p for p in self.result['dependencies']
                  if p['type'] == 'shared_control' and p['study'] == 'S0']
        self.assertEqual(len(panels), 1)
        # S0-control is shared by the week-0, week-12 and peer comparisons;
        # burden and confidence constructs cannot be converted into one number
        self.assertEqual(set(panels[0]['effects']), {'E0-0', 'E0-12', 'E0-peer'})
        self.assertIsNone(panels[0]['if_collapsed'])
        self.assertIn('not_collapsed_reason', panels[0])

    def test_observational_only_stratum_gains_no_causal_meaning(self):
        row = self.stratum('peer', 'confidence', 0)
        self.assertEqual(row['verdict'], 'benefit')
        self.assertEqual(row['causal_interpretation'], 'not_supported_observational_only')
        self.assertIsNone(row['by_design']['randomized'])
        self.assertEqual(row['confidence']['level'], 'limited')

    def test_leave_one_institution_out_is_reported(self):
        row = self.stratum('support', 'burden', 0)
        institutions = {r['institution'] for r in row['leave_one_institution_out']}
        self.assertEqual(institutions, {'Institute0', 'Institute1', 'Institute2', 'Institute3', 'Institute4'})
        self.assertFalse(row['fragile'])
        self.assertTrue(all('verdict' in r for r in row['leave_one_institution_out']))

    def test_small_samples_and_attrition_flagged(self):
        row = self.stratum('support', 'confidence', 0)
        self.assertIn('S1', row['cautions']['small_arm_studies'])
        self.assertIn('S3', row['cautions']['attrition_flagged_studies'])
        self.assertEqual(row['confidence']['level'], 'moderate')

    def test_publications_show_added_information_not_weight(self):
        pubs = self.result['publications']
        self.assertEqual(pubs['total_publications'], 22)
        self.assertEqual(pubs['independent_populations'], 12)
        s0 = next(row for row in pubs['per_study'] if row['study'] == 'S0')
        self.assertEqual(s0['publication_count'], 3)
        self.assertEqual(s0['independent_comparisons'], 2)
        adds = {p['adds'] for p in s0['publications']}
        self.assertIn('new_independent_comparison', adds)
        self.assertIn('extended_followup_same_population', adds)
        self.assertIn('additional_arm_shared_control', adds)
        self.assertIn('weight', pubs['weight_note'])

    def test_synthesis_traces_back_to_comparisons_and_populations(self):
        row = self.stratum('support', 'burden', 0)
        first = row['effects'][0]
        self.assertIn('control', first['comparison'])
        self.assertIn('treatment', first['comparison'])
        self.assertTrue(first['population'])

    def test_pending_decision_is_assessed(self):
        decisions = self.result['decisions']
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['service'], 'support')
        self.assertEqual(decisions[0]['supported_kind'], 'promote')


class AssessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(DATA)

    def test_strong_evidence_supports_promote(self):
        result = synthesis.assess(self.store, ALL_STUDIES, 'support')
        self.assertEqual(result['supported_kind'], 'promote')
        self.assertEqual(result['basis']['fingerprint'], self.store.fingerprint())

    def test_two_small_studies_only_support_a_pilot(self):
        result = synthesis.assess(self.store, ['S0', 'S1'], 'support')
        self.assertEqual(result['supported_kind'], 'evidence_pilot')

    def test_observational_only_benefit_cannot_justify_promotion(self):
        result = synthesis.assess(self.store, ['S0', 'S3', 'S6', 'S9'], 'peer')
        self.assertEqual(result['supported_kind'], 'evidence_pilot')
        self.assertTrue(any('observational' in b for b in result['promote_blockers']))

    def test_single_institution_dependence_blocks_promotion(self):
        result = synthesis.assess(self.store, ['S1', 'S5'], 'support')
        self.assertEqual(result['supported_kind'], 'evidence_pilot')
        self.assertTrue(any('fragile' in b for b in result['promote_blockers']))

    def test_unknown_scope_has_no_applicable_evidence(self):
        result = synthesis.assess(self.store, ALL_STUDIES, 'unknown-service')
        self.assertEqual(result['supported_kind'], 'evidence_pilot')
        self.assertEqual(result['applicable_effects'], 0)


class SynthesisRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(DATA)

    def test_route_filters(self):
        out = dispatch(self.store, '/api/synthesis', {})
        self.assertIn('strata', out)
        peer = dispatch(self.store, '/api/synthesis', {'service': ['peer']})
        self.assertTrue(all(s['service'] == 'peer' for s in peer['strata']))
        excluded = dispatch(self.store, '/api/synthesis', {'exclude_institution': ['Institute0']})
        remaining = {i for s in excluded['strata'] for i in s['institutions']}
        self.assertNotIn('Institute0', remaining)
        self.assertNotIn('Institute0', {e['institution'] for s in excluded['strata'] for e in s['effects']})

    def test_route_rejects_bad_parameters(self):
        for query in [{'exclude_institution': ['Nowhere']},
                      {'service': ['unknown']},
                      {'correlation': ['1.5']},
                      {'correlation': ['abc']}]:
            with self.subTest(query=query), self.assertRaises(DataError):
                dispatch(self.store, '/api/synthesis', query)

    def test_custom_correlation_joins_grid(self):
        out = dispatch(self.store, '/api/synthesis', {'correlation': ['0.4']})
        self.assertIn(0.4, out['correlation_grid'])

    def test_evidence_route_embeds_synthesis(self):
        out = dispatch(self.store, '/api/evidence', {})
        self.assertNotEqual(out['synthesis'], 'not_performed')
        self.assertIn('strata', out['synthesis'])
