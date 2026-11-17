from .domain import effect_record
from .storage import single


def catalog(store,query):
    institution=single(query,'institution')
    studies=[row for row in store.table('studies')
             if institution is None or row['institution']==institution]
    return {'studies':[dict(row,effects=[effect_record(store,effect) for effect in
                                         store.select('effects',study=row['study'])]) for row in studies]}


def evidence(store,query):
    return {'effects':[effect_record(store,row) for row in store.table('effects')],
            'publications':store.table('publications'),'decisions':store.table('decisions'),
            'synthesis':'not_performed'}


ROUTES={'/api/catalog':catalog,'/api/evidence':evidence}
