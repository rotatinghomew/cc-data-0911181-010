from pathlib import Path
import tempfile
import unittest
from app.journal import Journal
from app.storage import DataError,Store

DATA=Path(__file__).parents[1]/'data'


class BusinessChainTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(DATA)
        self.journal=Journal()

    def tearDown(self):
        self.journal.close()

    def test_business_chain(self):
        self.exercise(self.store,self.journal)

    def test_rollback_on_failure(self):
        with self.assertRaises(DataError):
            with self.journal.transaction():
                self.journal.put('test','a',{'value':1})
                raise DataError('aborted')
        self.assertEqual(self.journal.all('test'),[])

    def test_restart_retains_business_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'workflow.sqlite3'
            journal=Journal(path)
            try:
                self.exercise(self.store,journal)
                before={kind[0] for kind in journal.connection.execute('SELECT DISTINCT kind FROM documents')}
                snapshot={kind:journal.all(kind) for kind in before}
            finally:
                journal.close()
            reopened=Journal(path)
            try:
                self.assertEqual(snapshot,{kind:reopened.all(kind) for kind in before})
            finally:
                reopened.close()

    def exercise(self,store,journal):
        from app import recommendations,pilot_funds,pilot_agreements
        recommendations.propose(store,journal,dict(recommendation='r1',region='rural',studies=['S0','S1'],scope='support'))
        pilot_funds.approve(store,journal,dict(recommendation='r1',amount=10000))
        agreement=pilot_agreements.sign(store,journal,dict(recommendation='r1',school='village-school'))
        self.assertEqual(agreement['status'],'signed')
        with self.assertRaises(DataError):
            pilot_agreements.sign(store,journal,dict(recommendation='r1',school='city-school'))
        self.assertEqual(pilot_agreements.sign(store,journal,dict(recommendation='r1',school='village-school')),agreement)
