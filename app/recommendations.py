from .storage import DataError
from . import synthesis

KINDS=('promote','evidence_pilot')


def propose(store,journal,payload):
    region=store.find('regions',region=payload['region'])
    studies=sorted(set(payload['studies']))
    for study in studies:
        store.find('studies',study=study)
    assessment=synthesis.assess(store,studies,payload['scope'])
    requested=payload.get('kind')
    if requested is not None and requested not in KINDS:
        raise DataError('unknown recommendation kind: '+str(requested))
    kind=requested or assessment['supported_kind']
    if kind=='promote' and assessment['supported_kind']!='promote':
        raise DataError('evidence does not support full promotion for this scope; '
                        'only an evidence-gathering pilot can be proposed')
    row=dict(recommendation=payload['recommendation'],region=region['region'],studies=studies,
             scope=payload['scope'],kind=kind,evidence_basis=assessment['basis'],status='proposed')
    with journal.transaction():
        return journal.put('recommendation',row['recommendation'],row)
