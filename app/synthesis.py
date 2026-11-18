"""Evidence synthesis across studies for promotion decisions.

The catalog stores individual effects; this module combines them under
explicit rules so committee decisions rest on independent evidence:

* independent populations, shared control arms and repeated measurements of
  the same population are distinguished and never averaged as if independent;
* effects are pooled only inside semantically compatible strata (same
  service, construct, scale and follow-up time) after harmonising direction
  so that positive always means benefit; results that cannot be converted
  are retained and listed, never forced into a pooled total;
* unreported correlations are explored over a sensitivity grid instead of
  being silently treated as zero;
* small samples, attrition and institution concentration are reported as
  confidence factors, and observational evidence never gains causal meaning
  by being pooled.
"""

from statistics import NormalDist

from .storage import DataError

METHOD = 'synthesis-v1'
Z95 = NormalDist().inv_cdf(0.975)
DEFAULT_CORRELATION_GRID = (0.0, 0.25, 0.5, 0.75, 0.9)
ATTRITION_FLAG_RATE = 0.10
SMALL_ARM_OBSERVED = 20

METHOD_NOTES = {
    'id': METHOD,
    'unit': 'independent population; repeated measurements and shared-control comparisons are never counted as independent',
    'stratification': 'service x construct x scale x followup_weeks; only same-scale effects are pooled',
    'direction': 'estimates are harmonised so positive benefit means improvement before pooling',
    'pooling': 'inverse-variance fixed-effect and DerSimonian-Laird random-effects per stratum',
    'correlation': 'unreported correlations are explored over a sensitivity grid, never silently assumed zero',
    'causality': 'observational studies are pooled separately and never gain causal meaning from synthesis',
}


def enrich_effect(store, effect):
    """Join one effect with scale/study/arm context and harmonise direction."""
    scale = store.find('scales', scale=effect['scale'])
    study = store.find('studies', study=effect['study'])
    control = store.find('arms', arm=effect['control'])
    treatment = store.find('arms', arm=effect['treatment'])
    enrolled = control['enrolled'] + treatment['enrolled']
    observed = control['observed'] + treatment['observed']
    direction = 1.0 if scale['higher'] == 'better' else -1.0
    return {
        'effect': effect['effect'], 'study': effect['study'], 'population': effect['population'],
        'institution': study['institution'], 'design': study['design'],
        'control': effect['control'], 'treatment': effect['treatment'], 'service': treatment['kind'],
        'outcome': effect['outcome'], 'construct': scale['construct'], 'scale': effect['scale'],
        'followup_weeks': effect['followup_weeks'],
        'estimate': effect['estimate'], 'standard_error': effect['standard_error'],
        'benefit': direction * effect['estimate'],
        'correlation_reported': effect.get('correlation') is not None,
        'enrolled': enrolled, 'observed': observed,
        'attrition': 1.0 - observed / enrolled if enrolled else None,
        'smallest_arm_observed': min(control['observed'], treatment['observed']),
    }


def resolve_service(store, scope):
    """Map a decision/recommendation scope to a measured arm kind, if any."""
    kinds = {arm['kind'] for arm in store.table('arms')}
    if scope in kinds:
        return scope
    for suffix in ('_services', '_service', 's'):
        if scope.endswith(suffix) and scope[:-len(suffix)] in kinds:
            return scope[:-len(suffix)]
    return None


def _ci(estimate, se):
    return [estimate - Z95 * se, estimate + Z95 * se]


def _classify(estimate, se):
    lo, hi = _ci(estimate, se)
    if lo > 0:
        return 'benefit'
    if hi < 0:
        return 'harm'
    return 'uncertain'


def _pool(benefits, ses):
    """Inverse-variance pooling of independent benefit estimates."""
    k = len(benefits)
    if k == 0:
        return None
    if any(se <= 0 for se in ses):
        raise DataError('standard_error must be positive')
    weights = [1.0 / se ** 2 for se in ses]
    total = sum(weights)
    fixed = sum(w * b for w, b in zip(weights, benefits)) / total
    fixed_se = (1.0 / total) ** 0.5
    q = sum(w * (b - fixed) ** 2 for w, b in zip(weights, benefits))
    df = k - 1
    c = total - sum(w ** 2 for w in weights) / total
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    rweights = [1.0 / (se ** 2 + tau2) for se in ses]
    rtotal = sum(rweights)
    random = sum(w * b for w, b in zip(rweights, benefits)) / rtotal
    random_se = (1.0 / rtotal) ** 0.5
    i2 = max(0.0, (q - df) / q) if q > 0 else 0.0
    return {
        'independent_effects': k,
        'fixed': {'benefit': fixed, 'standard_error': fixed_se, 'ci95': _ci(fixed, fixed_se)},
        'random': {'benefit': random, 'standard_error': random_se, 'ci95': _ci(random, random_se)},
        'heterogeneity': {'q': q, 'df': df, 'i2': i2, 'tau2': tau2},
    }


def _verdict(k, pooled):
    if k < 2 or pooled is None:
        return 'insufficient'
    return _classify(pooled['random']['benefit'], pooled['random']['standard_error'])


def _combine_correlated(benefits, ses, assumed_correlation):
    """Mean of estimates whose sampling errors correlate at the assumed level."""
    m = len(benefits)
    variance = sum(se ** 2 for se in ses)
    for i in range(m):
        for j in range(i + 1, m):
            variance += 2 * assumed_correlation * ses[i] * ses[j]
    variance /= m ** 2
    return {'benefit': sum(benefits) / m, 'standard_error': variance ** 0.5}


def _collapsed_row(rows, assumed_correlation):
    combined = _combine_correlated([row['benefit'] for row in rows],
                                   [row['standard_error'] for row in rows], assumed_correlation)
    return {'assumed_correlation': assumed_correlation,
            'combined_benefit': combined['benefit'],
            'standard_error': combined['standard_error'],
            'ci95': _ci(combined['benefit'], combined['standard_error']),
            'classification': _classify(combined['benefit'], combined['standard_error'])}


def _stratum(key, group, grid):
    service, construct, scale, followup = key
    group = sorted(group, key=lambda e: e['effect'])
    per_population = {}
    for effect in group:
        per_population.setdefault(effect['population'], []).append(effect)
    units = []
    combinations = []
    for population, rows in sorted(per_population.items()):
        first = rows[0]
        if len(rows) == 1:
            unit_benefit, unit_se = first['benefit'], first['standard_error']
        else:
            # repeated reports of one population inside a stratum are combined
            # at the most conservative grid correlation; sensitivity is shown
            combined = _combine_correlated([r['benefit'] for r in rows],
                                           [r['standard_error'] for r in rows], max(grid))
            unit_benefit, unit_se = combined['benefit'], combined['standard_error']
            combinations.append({'population': population,
                                 'effects': [r['effect'] for r in rows],
                                 'sensitivity': [_collapsed_row(rows, r) for r in grid],
                                 'used_assumed_correlation': max(grid)})
        units.append({'population': population, 'study': first['study'],
                      'institution': first['institution'], 'design': first['design'],
                      'effects': [r['effect'] for r in rows],
                      'benefit': unit_benefit, 'standard_error': unit_se,
                      'observed': first['observed'], 'enrolled': first['enrolled'],
                      'attrition': first['attrition'],
                      'smallest_arm_observed': first['smallest_arm_observed']})
    pooled = _pool([u['benefit'] for u in units], [u['standard_error'] for u in units])
    k = len(units)
    verdict = _verdict(k, pooled)
    total_weight = sum(1.0 / u['standard_error'] ** 2 for u in units)
    unit_weights = {u['population']: (1.0 / u['standard_error'] ** 2) / total_weight for u in units}
    institutions = sorted({u['institution'] for u in units})
    loio = []
    for institution in institutions:
        removed = sorted({u['study'] for u in units if u['institution'] == institution})
        remaining = [u for u in units if u['institution'] != institution]
        if not remaining:
            loio.append({'institution': institution, 'removed_studies': removed,
                         'remaining_populations': 0, 'pooled_benefit': None, 'ci95': None,
                         'verdict': 'not_computable', 'verdict_changed': True})
            continue
        sub = _pool([u['benefit'] for u in remaining], [u['standard_error'] for u in remaining])
        sub_verdict = _verdict(len(remaining), sub)
        loio.append({'institution': institution, 'removed_studies': removed,
                     'remaining_populations': len(remaining),
                     'pooled_benefit': sub['random']['benefit'], 'ci95': sub['random']['ci95'],
                     'verdict': sub_verdict, 'verdict_changed': sub_verdict != verdict})
    fragile = any(row['verdict_changed'] for row in loio)
    by_design = {}
    for design in ('randomized', 'observational'):
        subset = [u for u in units if u['design'] == design]
        if subset:
            sub = _pool([u['benefit'] for u in subset], [u['standard_error'] for u in subset])
            by_design[design] = {'populations': len(subset),
                                 'pooled_benefit': sub['random']['benefit'],
                                 'ci95': sub['random']['ci95'],
                                 'classification': _classify(sub['random']['benefit'],
                                                             sub['random']['standard_error'])}
        else:
            by_design[design] = None
    small = sorted({u['study'] for u in units if u['smallest_arm_observed'] < SMALL_ARM_OBSERVED})
    attrition_flagged = sorted({u['study'] for u in units
                                if u['attrition'] is not None and u['attrition'] > ATTRITION_FLAG_RATE})
    reasons = []
    limited = False
    if k < 3:
        reasons.append('fewer_than_3_independent_populations')
        limited = True
    if by_design['randomized'] is None:
        reasons.append('no_randomized_evidence')
        limited = True
    if fragile:
        reasons.append('verdict_fragile_to_single_institution_removal')
        limited = True
    if small:
        reasons.append('small_arms:' + ','.join(small))
    if attrition_flagged:
        reasons.append('attrition_above_10pct:' + ','.join(attrition_flagged))
    if k < 5:
        reasons.append('fewer_than_5_independent_populations')
    level = 'limited' if limited else ('moderate' if reasons else 'higher')
    return {
        'service': service, 'construct': construct, 'scale': scale, 'followup_weeks': followup,
        'direction': 'positive benefit means improvement (scale direction harmonised)',
        'effects': [{'effect': e['effect'], 'study': e['study'], 'institution': e['institution'],
                     'design': e['design'], 'population': e['population'],
                     'comparison': {'control': e['control'], 'treatment': e['treatment']},
                     'outcome': e['outcome'],
                     'estimate': e['estimate'], 'standard_error': e['standard_error'],
                     'benefit': e['benefit'], 'observed': e['observed'], 'enrolled': e['enrolled'],
                     'attrition': e['attrition'], 'correlation_reported': e['correlation_reported']}
                    for e in group],
        'pooling_units': units,
        'unit_weights': unit_weights,
        'within_stratum_combinations': combinations,
        'independent_populations': k,
        'studies': sorted({u['study'] for u in units}),
        'institutions': institutions,
        'pooled': pooled,
        'by_design': by_design,
        'causal_interpretation': ('randomized_subset_available' if by_design['randomized']
                                  else 'not_supported_observational_only'),
        'verdict': verdict,
        'leave_one_institution_out': loio,
        'fragile': fragile,
        'cautions': {'small_arm_studies': small, 'attrition_flagged_studies': attrition_flagged},
        'confidence': {'level': level, 'reasons': reasons},
    }


def _strata(effects, grid):
    groups = {}
    for effect in effects:
        key = (effect['service'], effect['construct'], effect['scale'], effect['followup_weeks'])
        groups.setdefault(key, []).append(effect)
    return [_stratum(key, groups[key], grid) for key in sorted(groups)]


def _dependency_panel(kind, rows, grid, shared):
    rows = sorted(rows, key=lambda r: r['effect'])
    constructs = sorted({r['construct'] for r in rows})
    scales = sorted({r['scale'] for r in rows})
    panel = {
        'type': kind,
        'study': rows[0]['study'],
        'population': rows[0]['population'],
        'effects': [r['effect'] for r in rows],
        'shared': shared,
        'correlation_reported': any(r['correlation_reported'] for r in rows),
        'counted_as_independent': False,
    }
    if len(constructs) == 1 and len(scales) == 1:
        sensitivity = [_collapsed_row(rows, r) for r in grid]
        panel['if_collapsed'] = {
            'sensitivity': sensitivity,
            'conclusion_stable': len({row['classification'] for row in sensitivity}) == 1,
            'note': 'illustrative only; the synthesis keeps these effects in separate strata',
        }
    else:
        panel['if_collapsed'] = None
        panel['not_collapsed_reason'] = ('effects measure different constructs or scales; '
                                         'they are retained separately and never forced into one total')
    return panel


def _dependencies(effects, grid):
    """Surface repeated measurements and shared control arms with sensitivity."""
    panels = []
    by_comparison = {}
    for effect in effects:
        key = (effect['study'], effect['control'], effect['treatment'])
        by_comparison.setdefault(key, []).append(effect)
    for (study, control, treatment), rows in sorted(by_comparison.items()):
        if len(rows) > 1:
            followups = sorted({r['followup_weeks'] for r in rows})
            panels.append(_dependency_panel(
                'repeated_measurements', rows, grid,
                'population %s measured at %d follow-up times' % (rows[0]['population'], len(followups))))
    by_control = {}
    for effect in effects:
        by_control.setdefault((effect['study'], effect['control']), []).append(effect)
    for (study, control), rows in sorted(by_control.items()):
        treatments = sorted({r['treatment'] for r in rows})
        if len(treatments) > 1:
            panels.append(_dependency_panel(
                'shared_control', rows, grid,
                'control arm %s shared by comparisons against %s' % (control, ', '.join(treatments))))
    return panels


def _publications(store, effects):
    """Classify what each publication adds beyond the first independent report."""
    visible = {e['effect']: e for e in effects}
    per_study = {}
    outside = 0
    for pub in sorted(store.table('publications'), key=lambda p: (p['year'], p['publication'])):
        effect = visible.get(pub['effect'])
        if effect is None:
            outside += 1
            continue
        entry = per_study.setdefault(effect['study'], {
            'study': effect['study'], 'institution': effect['institution'],
            'population': effect['population'], 'publications': [],
            '_comparisons': set(), '_followups': set(), '_controls': set(), '_effects': set()})
        comparison = (effect['control'], effect['treatment'])
        if pub['effect'] in entry['_effects']:
            adds = 'duplicate_citation_no_new_data'
        elif comparison in entry['_comparisons']:
            if (comparison, effect['followup_weeks']) in entry['_followups']:
                adds = 'repeated_report_same_followup'
            else:
                adds = 'extended_followup_same_population'
            entry['_followups'].add((comparison, effect['followup_weeks']))
        elif effect['control'] in entry['_controls']:
            adds = 'additional_arm_shared_control'
            entry['_comparisons'].add(comparison)
            entry['_followups'].add((comparison, effect['followup_weeks']))
        else:
            adds = 'new_independent_comparison'
            entry['_comparisons'].add(comparison)
            entry['_followups'].add((comparison, effect['followup_weeks']))
            entry['_controls'].add(effect['control'])
        entry['_effects'].add(pub['effect'])
        entry['publications'].append({'publication': pub['publication'], 'year': pub['year'],
                                      'effect': pub['effect'], 'adds': adds})
    studies = [{'study': e['study'], 'institution': e['institution'], 'population': e['population'],
                'publication_count': len(e['publications']),
                'independent_comparisons': len(e['_comparisons']),
                'publications': e['publications']}
               for e in sorted(per_study.values(), key=lambda e: e['study'])]
    return {
        'total_publications': len(store.table('publications')),
        'outside_current_view': outside,
        'independent_populations': len({e['population'] for e in effects}),
        'independent_comparisons': len({(e['population'], e['control'], e['treatment']) for e in effects}),
        'per_study': studies,
        'weight_note': ('pooling weights derive from independent populations and standard errors; '
                        'publishing more materials about the same comparison does not add weight'),
    }


def _eligibility(strata, service):
    """Decide whether the strata support full promotion or only a pilot."""
    blockers = []
    if service is None:
        blockers.append('scope does not match any measured service')
    if not strata:
        blockers.append('no applicable evidence for scope')
    harm = [s for s in strata if s['verdict'] == 'harm']
    for s in harm:
        blockers.append('harm signal in %s/%s week %s' % (s['service'], s['construct'], s['followup_weeks']))
    benefit = [s for s in strata if s['verdict'] == 'benefit']
    robust = [s for s in benefit
              if s['causal_interpretation'] == 'randomized_subset_available' and not s['fragile']]
    if not robust:
        if not benefit:
            blockers.append('no stratum shows a pooled benefit')
        else:
            if all(s['fragile'] for s in benefit):
                blockers.append('benefit verdict fragile to single-institution removal')
            if all(s['causal_interpretation'] != 'randomized_subset_available' for s in benefit):
                blockers.append('benefit rests on observational evidence only')
    eligible = bool(robust) and not harm and service is not None
    return eligible, blockers


def _decisions(store, effects, grid):
    rows = []
    for decision in store.table('decisions'):
        service = resolve_service(store, decision['scope'])
        applicable = [e for e in effects if service is not None and e['service'] == service]
        strata = _strata(applicable, grid)
        eligible, blockers = _eligibility(strata, service)
        rows.append({'decision': decision['decision'], 'scope': decision['scope'],
                     'status': decision['status'], 'service': service,
                     'applicable_effects': len(applicable),
                     'supported_kind': 'promote' if eligible else 'evidence_pilot',
                     'promote_blockers': blockers})
    return rows


def assess(store, studies, scope, grid=None):
    """Evidence basis for one recommendation: what the cited studies support."""
    grid = tuple(grid) if grid else DEFAULT_CORRELATION_GRID
    service = resolve_service(store, scope)
    enriched = []
    for study in studies:
        for effect in store.select('effects', study=study):
            row = enrich_effect(store, effect)
            enriched.append(row)
    # an unresolvable scope matches no measured service, hence no evidence
    enriched = [row for row in enriched if service is not None and row['service'] == service]
    strata = _strata(enriched, grid)
    eligible, blockers = _eligibility(strata, service)
    supported = 'promote' if eligible else 'evidence_pilot'
    return {
        'scope': scope, 'service': service, 'studies': sorted(studies),
        'applicable_effects': len(enriched),
        'strata': strata,
        'supported_kind': supported,
        'promote_blockers': blockers,
        'basis': {
            'method': METHOD,
            'fingerprint': store.fingerprint(),
            'supported_kind': supported,
            'strata': [{'service': s['service'], 'construct': s['construct'], 'scale': s['scale'],
                        'followup_weeks': s['followup_weeks'], 'verdict': s['verdict'],
                        'independent_populations': s['independent_populations'],
                        'confidence': s['confidence']['level']} for s in strata],
        },
    }


def synthesize(store, service=None, exclude_institution=None, grid=None):
    """Full synthesis view over the catalog, honouring optional filters."""
    grid = tuple(grid) if grid else DEFAULT_CORRELATION_GRID
    for assumed in grid:
        if not 0 <= assumed < 1:
            raise DataError('correlation grid values must be in [0, 1)')
    institutions = sorted({s['institution'] for s in store.table('studies')})
    if exclude_institution is not None and exclude_institution not in institutions:
        raise DataError('unknown institution: ' + str(exclude_institution))
    kinds = sorted({a['kind'] for a in store.table('arms')})
    if service is not None and service not in kinds:
        raise DataError('unknown service: ' + str(service))
    effects = [enrich_effect(store, e) for e in store.table('effects')]
    if exclude_institution is not None:
        effects = [e for e in effects if e['institution'] != exclude_institution]
    if service is not None:
        effects = [e for e in effects if e['service'] == service]
    return {
        'method': METHOD_NOTES,
        'filters': {'service': service, 'exclude_institution': exclude_institution},
        'correlation_grid': list(grid),
        'effects_in_view': len(effects),
        'strata': _strata(effects, grid),
        'grand_total': {'computed': False,
                        'reason': ('strata measure different constructs, scales or follow-up times; '
                                   'pooled results are reported per stratum only, never as one total')},
        'dependencies': _dependencies(effects, grid),
        'publications': _publications(store, effects),
        'decisions': _decisions(store, effects, grid),
        'dataset_fingerprint': store.fingerprint(),
    }
