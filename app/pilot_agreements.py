from .storage import DataError


def sign(store,journal,payload):
    with journal.transaction():
        grant=journal.get('pilot_fund',payload['recommendation'])
        school=store.find('pilot_schools',school=payload['school'])
        if school['region']!=grant['region'] or grant['status']!='approved':
            raise DataError('school outside approved pilot')
        key=grant['recommendation']+':'+school['school']
        prior=[row for row in journal.all('pilot_agreement') if row['agreement']==key]
        if prior:
            return prior[0]
        basis=grant.get('evidence_basis')
        if basis is not None and basis['fingerprint']!=store.fingerprint():
            raise DataError('evidence basis changed since approval; '
                            'unsigned pilots cannot rely on the previous synthesis')
        return journal.put('pilot_agreement',key,dict(agreement=key,school=school['school'],
                           recommendation=grant['recommendation'],scope=grant['scope'],
                           kind=grant.get('kind','evidence_pilot'),amount=grant['amount'],
                           status='signed',evidence_fingerprint=store.fingerprint()))


def audit(store,journal,payload):
    fingerprint=store.fingerprint()

    def current(row):
        basis=row.get('evidence_basis') or {}
        return basis.get('fingerprint') in (None,fingerprint)

    grants=journal.all('pilot_fund')
    by_recommendation={row['recommendation']:row for row in grants}
    agreements=[]
    for row in journal.all('pilot_agreement'):
        stored=row.get('evidence_fingerprint')
        grant=by_recommendation.get(row['recommendation'],{})
        agreements.append(dict(row,
                               basis_current=stored in (None,fingerprint),
                               grant_kind=grant.get('kind'),
                               retention='signed agreements are historical records and are never removed by new synthesis'))
    return {'dataset_fingerprint':fingerprint,
            'recommendations':[dict(row,basis_current=current(row)) for row in journal.all('recommendation')],
            'pilot_funds':[dict(row,basis_current=current(row)) for row in grants],
            'pilot_agreements':agreements}
