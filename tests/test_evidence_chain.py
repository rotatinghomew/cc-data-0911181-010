import json
from pathlib import Path
import shutil
import tempfile
import unittest

from app import pilot_agreements, pilot_funds, recommendations
from app.journal import Journal
from app.storage import DataError, Store
from app.workflow import OPERATIONS

DATA = Path(__file__).parents[1] / 'data'
ALL_STUDIES = ['S%d' % i for i in range(12)]
INSTITUTE0_STUDIES = {'S0', 'S5', 'S10'}


class EvidenceChainTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(DATA)
        self.journal = Journal()

    def tearDown(self):
        self.journal.close()

    def without_institute0(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        target = Path(directory) / 'data'
        shutil.copytree(DATA, target)
        for name in ('studies', 'arms', 'effects', 'publications'):
            path = target / (name + '.json')
            rows = json.loads(path.read_text())
            path.write_text(json.dumps([r for r in rows if r['study'] not in INSTITUTE0_STUDIES]))
        schools = json.loads((target / 'pilot_schools.json').read_text())
        schools.append({'school': 'village-school-2', 'region': 'rural'})
        (target / 'pilot_schools.json').write_text(json.dumps(schools))
        return Store(target)

    def test_promote_chain_with_strong_evidence(self):
        proposal = recommendations.propose(self.store, self.journal, dict(
            recommendation='promote-1', region='rural', studies=ALL_STUDIES,
            scope='support', kind='promote'))
        self.assertEqual(proposal['kind'], 'promote')
        self.assertEqual(proposal['evidence_basis']['fingerprint'], self.store.fingerprint())
        grant = pilot_funds.approve(self.store, self.journal, dict(recommendation='promote-1', amount=20000))
        self.assertEqual(grant['kind'], 'promote')
        self.assertFalse(grant['applicability']['region_matched_studies'])
        agreement = pilot_agreements.sign(self.store, self.journal,
                                          dict(recommendation='promote-1', school='village-school'))
        self.assertEqual(agreement['status'], 'signed')
        state = pilot_agreements.audit(self.store, self.journal, {})
        self.assertTrue(all(row['basis_current'] for row in state['pilot_agreements']))

    def test_weak_evidence_cannot_be_packaged_as_promotion(self):
        with self.assertRaises(DataError):
            recommendations.propose(self.store, self.journal, dict(
                recommendation='over-claim', region='rural', studies=['S0', 'S1'],
                scope='support', kind='promote'))
        proposal = recommendations.propose(self.store, self.journal, dict(
            recommendation='pilot-1', region='rural', studies=['S0', 'S1'], scope='support'))
        self.assertEqual(proposal['kind'], 'evidence_pilot')
        pilot_funds.approve(self.store, self.journal, dict(recommendation='pilot-1', amount=5000))
        agreement = pilot_agreements.sign(self.store, self.journal,
                                          dict(recommendation='pilot-1', school='village-school'))
        self.assertEqual(agreement['kind'], 'evidence_pilot')

    def test_unknown_kind_rejected(self):
        with self.assertRaises(DataError):
            recommendations.propose(self.store, self.journal, dict(
                recommendation='bad-kind', region='rural', studies=ALL_STUDIES,
                scope='support', kind='guaranteed'))

    def test_stale_basis_blocks_new_commitments_but_keeps_signed(self):
        recommendations.propose(self.store, self.journal, dict(
            recommendation='chain', region='rural', studies=ALL_STUDIES,
            scope='support', kind='promote'))
        pilot_funds.approve(self.store, self.journal, dict(recommendation='chain', amount=20000))
        signed = pilot_agreements.sign(self.store, self.journal,
                                       dict(recommendation='chain', school='village-school'))
        reduced = self.without_institute0()
        # signed agreements are historical records: retained and returned as-is
        self.assertEqual(pilot_agreements.sign(reduced, self.journal,
                                               dict(recommendation='chain', school='village-school')), signed)
        # unsigned pilots cannot rely on the old basis after the institution removal
        with self.assertRaises(DataError):
            pilot_agreements.sign(reduced, self.journal,
                                  dict(recommendation='chain', school='village-school-2'))
        # re-approval on the stale proposal is refused as well
        with self.assertRaises(DataError):
            pilot_funds.approve(reduced, self.journal, dict(recommendation='chain', amount=5000))
        # audit keeps the signed agreement visible and flags the stale basis
        state = pilot_agreements.audit(reduced, self.journal, {})
        self.assertEqual(len(state['pilot_agreements']), 1)
        self.assertFalse(state['pilot_agreements'][0]['basis_current'])
        self.assertFalse(state['pilot_funds'][0]['basis_current'])
        self.assertIn('never removed', state['pilot_agreements'][0]['retention'])
        # a fresh proposal on the reduced evidence re-establishes the chain
        remaining = [s for s in ALL_STUDIES if s not in INSTITUTE0_STUDIES]
        proposal = recommendations.propose(reduced, self.journal, dict(
            recommendation='chain', region='rural', studies=remaining,
            scope='support', kind='promote'))
        self.assertEqual(proposal['kind'], 'promote')
        pilot_funds.approve(reduced, self.journal, dict(recommendation='chain', amount=20000))
        again = pilot_agreements.sign(reduced, self.journal,
                                      dict(recommendation='chain', school='village-school-2'))
        self.assertEqual(again['status'], 'signed')
        state = pilot_agreements.audit(reduced, self.journal, {})
        self.assertEqual(len(state['pilot_agreements']), 2)
        stale = [a for a in state['pilot_agreements'] if not a['basis_current']]
        self.assertEqual([a['school'] for a in stale], ['village-school'])

    def test_legacy_records_receive_current_basis(self):
        self.journal.put('recommendation', 'legacy', dict(
            recommendation='legacy', region='rural', studies=['S0', 'S1'],
            scope='support', status='proposed'))
        grant = pilot_funds.approve(self.store, self.journal, dict(recommendation='legacy', amount=5000))
        self.assertEqual(grant['kind'], 'evidence_pilot')
        self.assertEqual(grant['evidence_basis']['fingerprint'], self.store.fingerprint())

    def test_audit_operation_registered(self):
        self.assertIn('pilot_agreements.audit', OPERATIONS)
        out = OPERATIONS['pilot_agreements.audit'](self.store, self.journal, {})
        self.assertEqual(out['pilot_agreements'], [])
        self.assertEqual(out['dataset_fingerprint'], self.store.fingerprint())
