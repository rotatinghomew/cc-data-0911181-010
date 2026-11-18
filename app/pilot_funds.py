from .storage import DataError
from . import synthesis


def approve(store,journal,payload):
    with journal.transaction():
        recommendation=journal.get('recommendation',payload['recommendation'])
        region=store.find('regions',region=recommendation['region'])
        basis=recommendation.get('evidence_basis')
        if basis is None:
            # legacy proposals carry no basis; stamp the current synthesis instead of blocking
            basis=synthesis.assess(store,recommendation['studies'],recommendation['scope'])['basis']
            kind='evidence_pilot'
        else:
            if basis['fingerprint']!=store.fingerprint():
                raise DataError('evidence basis changed since proposal; submit a new proposal before approval')
            kind=recommendation.get('kind','evidence_pilot')
        amount=float(payload['amount'])
        prior=[row for row in journal.all('pilot_fund') if row['recommendation']!=recommendation['recommendation']
               and row['region']==region['region']]
        if amount<=0 or amount+sum(row['amount'] for row in prior)>region['budget']:
            raise DataError('pilot funding limit exceeded')
        schools=store.select('pilot_schools',region=region['region'])
        if not schools:
            raise DataError('no pilot schools registered in region')
        applicability=dict(
            region_matched_studies=False,
            note='studies are not tagged by region; applicability to this region is not directly established',
            evidence_institutions=sorted({row['institution'] for row in store.table('studies')
                                          if row['study'] in recommendation['studies']}),
            pilot_schools_in_region=[row['school'] for row in schools],
            cautions=['%s %s week %s: %s confidence' % (s['service'],s['construct'],s['followup_weeks'],s['confidence'])
                      for s in basis['strata']])
        row=dict(recommendation=recommendation['recommendation'],region=region['region'],scope=recommendation['scope'],
                 kind=kind,amount=amount,status='approved',evidence_basis=basis,applicability=applicability)
        return journal.put('pilot_fund',row['recommendation'],row)
