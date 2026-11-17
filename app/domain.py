def effect_record(store,effect):
    scale=store.find('scales',scale=effect['scale'])
    study=store.find('studies',study=effect['study'])
    control=store.find('arms',arm=effect['control'])
    treatment=store.find('arms',arm=effect['treatment'])
    return dict(effect,higher=scale['higher'],construct=scale['construct'],
                institution=study['institution'],design=study['design'],
                control_observed=control['observed'],treatment_observed=treatment['observed'])
