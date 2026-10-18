"""Bounded LLM interpretation layered over complete local source records.

The model returns declarative rules/facts, never executable code or model vectors.
A sample review is explicitly distinguished from exhaustive narrative reading.
"""
from __future__ import annotations
import copy,json,math,hashlib
from auto_import import FIELDS,RESOURCE_PROPERTIES,KINDS,heading,norm,cells,nested_cells,offline_facts,validate_facts,resolved_field

MAX_PLAN_BYTES=18000
MAX_RULES=24
CONTEXT_NAMES=['collection_centric','crafting_centric','trading_present','production_queue_present','inventory_capacity_present','upgrade_system_present','randomized_acquisition_present','pity_or_bad_luck_protection_present','duplicate_conversion_present','energy_or_lives_present','seasonal_or_event_economy_present','battle_pass_present','ranked_progression_present','cosmetic_economy_present','player_to_player_economy_present','construction_or_customization_present','short_session_orientation','long_term_progression_depth','open_ended_sandbox_orientation','exploration_reward_relevance','social_cooperation_relevance','competitive_pressure','time_gating_intensity','scarcity_intensity','randomness_intensity','monetization_intensity','paid_power_access','economy_transparency']

def encoded_size(value):return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())

def review_plan(parsed):
    total=sum(len(t['rows']) for t in parsed['tables'])
    if not total:return {'mode':'skip','reason':'Already-canonical input preserves its authored schema and constraints.','source_rows':0}
    # Small documents retain the full fact/relationship interpreter from v3.
    if total<=12 and encoded_size(parsed)<=12000:
        candidate=copy.deepcopy(parsed);candidate['canonical']=None;candidate['canonical_files']=[]
        return {'mode':'facts','parsed':candidate,'source_rows':total}
    plan={'mode':'semantic','source_rows':total,'tables':[],'sampled_rows':0,'omitted_tables':0,'omitted_columns':0,'truncated_cells':0,
          'coverage':'Bounded schema and representative-record review. Validated rules apply locally to all matching rows; unsampled prose is not exhaustively interpreted.'}
    for t in parsed['tables']:
        entry={'table_id':t['id'],'file':t['file_name'],'sheet':t['sheet'],'rows':len(t['rows']),'columns':[],'samples':[]}
        plan['tables'].append(entry)
        if encoded_size(plan)>MAX_PLAN_BYTES-2500:
            plan['tables'].pop();plan['omitted_tables']+=1;continue
        # Column meaning is reviewed even when a local alias already exists.
        # Known scalar meanings cannot be silently reassigned.
        for ci,h in enumerate(t['headers']):
            column={'column':ci,'header':str(h)[:160],'local_field':heading(h),'examples':[]}
            distinct=set()
            for ri,values in enumerate(t['values']):
                v=values[ci]
                if v is None or v=='':continue
                if isinstance(v,(dict,list)):v=json.dumps(v,ensure_ascii=False)
                v=str(v)
                if len(v)>240 or v in distinct:continue
                distinct.add(v);r,c=t['coordinates'][ri][ci]
                column['examples'].append({'source_id':f'{t["id"]}!R{r}C{c}','value':v})
                if len(column['examples'])==2:break
            entry['columns'].append(column)
            if encoded_size(plan)>MAX_PLAN_BYTES-4500:
                entry['columns'].pop();plan['omitted_columns']+=1
        # Spread narrative evidence across categories and the file rather than
        # sending every cell (or letting a huge first row consume the budget).
        selectors=[i for i,h in enumerate(t['headers']) if norm(h) in {'category','categories','entity_type','type','economy_types','source_categories'}]
        indices=[];seen=set()
        for ri,values in enumerate(t['values']):
            signature=tuple(str(values[ci])[:160] for ci in selectors)
            if signature not in seen:seen.add(signature);indices.append(ri)
            if len(indices)>=4:break
        indices=list(dict.fromkeys(indices+[0,len(t['rows'])//2,len(t['rows'])-1]))
        for ri in indices:
            sample={'record_id':f'{t["id"]}:record:{ri}','cells':[]}
            for ci,v in enumerate(t['values'][ri]):
                if v is None or v=='':continue
                h=t['headers'][ci];n=norm(h)
                if n in {'url','wiki_home','wiki_base','table_rows_json','extra_fields_json','economic_score','game_id'}:continue
                if isinstance(v,(dict,list)):v=json.dumps(v,ensure_ascii=False)
                v=str(v);r,c=t['coordinates'][ri][ci]
                # Full numeric scalar fields remain small. Narrative is labelled.
                limit=420 if n in {'description','plain_text_excerpt','effects','crafting'} else 160
                if n=='all_infobox_fields_json':continue
                cell={'source_id':f'{t["id"]}!R{r}C{c}','column':ci,'header':h,'value':v[:limit],'truncated':len(v)>limit}
                sample['cells'].append(cell)
            for cell in nested_cells(t,ri)[:10]:
                sample['cells'].append({'source_id':cell['source_id'],'header':cell['nested_header'],'value':str(cell['value'])[:160],'truncated':len(str(cell['value']))>160})
            entry['samples'].append(sample)
            if encoded_size(plan)>MAX_PLAN_BYTES-400:
                entry['samples'].pop();continue
            plan['sampled_rows']+=1;plan['truncated_cells']+=sum(c['truncated'] for c in sample['cells'])
    return plan

def evidence_index(plan):
    result={}
    for t in plan.get('tables',[]):
        for col in t['columns']:
            for e in col['examples']:result[e['source_id']]={**e,'table_id':t['table_id'],'column':col['column'],'truncated':False}
        for row in t['samples']:
            for e in row['cells']:result[e['source_id']]={**result.get(e['source_id'],{}),**e,'table_id':t['table_id'],'record_id':row['record_id']}
    return result

def observed_column_values(table,column):
    """Include complete representative cells, not only two column examples."""
    values={str(e['value']).casefold():e for e in column['examples']}
    for row in table.get('samples',[]):
        for cell in row['cells']:
            if cell.get('truncated') or '#/' in cell['source_id']:continue
            matches=cell.get('column')==column['column'] if 'column' in cell else cell.get('header')==column['header']
            if matches:values.setdefault(str(cell['value']).casefold(),cell)
    return list(values.values())

def selector_catalogue(plan):
    """Short IDs let the API select literal source values without rewriting them."""
    options=[]
    def add(table,column,value):
        fields={'table_id':table['table_id'],'match_column':column,'match_value':value}
        sid='scope_'+hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
        candidate={'selector_id':sid,**fields}
        if len(options)<80 and encoded_size(options+[candidate])<=6000:options.append(candidate)
    for table in plan['tables']:add(table,None,None)
    ranked=[]
    for table in plan['tables']:
        for column in table['columns']:
            priority=0 if norm(column['header']) in {'category','categories','entity_type','type','kind','class','economy_types','source_categories'} else 1
            ranked.append((priority,table,column))
    for _,table,column in sorted(ranked,key=lambda x:x[0]):
        if column.get('local_field') not in {None,'category','kind','name','currency','merchant','inventory'}:continue
        for cell in observed_column_values(table,column):
            value=str(cell['value'])
            if value.strip() and len(value)<=160:add(table,column['column'],value)
    return options

def resolve_selectors(document,options):
    resolved=copy.deepcopy(document);index={s['selector_id']:s for s in options}
    for rule in resolved.get('semantic_rules',[]):
        if 'selector_id' not in rule:continue # Older saved/replayed responses.
        chosen=index.get(rule['selector_id'])
        if chosen:rule.update({k:chosen[k] for k in ['table_id','match_column','match_value']})
        else:rule.update(table_id=None,match_column=None,match_value=None)
    return resolved

def retain_valid_review(document,plan):
    """A rejected component cannot discard unrelated, validated interpretations."""
    valid={k:[] for k in ['column_mappings','semantic_rules','facts','context_hints']};valid['notes']=list(document.get('notes',[]));issues=[]
    for key in ['column_mappings','semantic_rules','facts','context_hints']:
        for i,item in enumerate(document.get(key,[])):
            try:
                if key=='semantic_rules' and len(valid[key])>=MAX_RULES:raise ValueError('Semantic rule count exceeds the action limit.')
                validate_review({key:[item]},plan)
                valid[key].append(item)
            except (ValueError,KeyError,TypeError) as exc:issues.append(f'{key}[{i}]: {str(exc)[:300]}')
    return valid,issues

def validate_review(document,plan):
    tables={t['table_id']:t for t in plan['tables']};source=evidence_index(plan)
    allowed_fields=set(FIELDS)|set(RESOURCE_PROPERTIES)|{'functional_roles','ignore'}
    def refs(ids,table=None):
        if not ids or any(s not in source or (table is not None and source[s]['table_id']!=table) for s in ids):raise ValueError('Semantic interpretation cites missing evidence.')
    for m in document.get('column_mappings',[]):
        t=tables.get(m.get('table_id'));col=next((c for c in t['columns'] if c['column']==m.get('column')),None) if t else None
        if not col or m.get('field') not in allowed_fields:raise ValueError('Invalid semantic column mapping.')
        if norm(col['header']) in {'game_id','url','wiki_base','wiki_home','economic_score','review_score','px_score','sentiment','fairness_perception','perceived_value','progression_satisfaction','competence_support','autonomy_support','ownership_support','identity_status_support','pressure_risk','fatigue_risk','pay_to_win_perception','frustration_risk','archetype_specific_satisfaction'} and m['field']!='ignore':raise ValueError('Identifiers, review labels and outcome scores cannot become economy inputs.')
        if col['local_field'] and m['field']!=col['local_field']:raise ValueError('LLM may not overwrite a recognized source field.')
    rules=document.get('semantic_rules',[])
    if len(rules)>MAX_RULES:raise ValueError('Too many semantic rules for a bounded review.')
    for rule in rules:
        t=tables.get(rule.get('table_id'))
        if not t:raise ValueError('Semantic rule refers to an unsupplied table.')
        refs(rule.get('source_ids'),t['table_id'])
        ci=rule.get('match_column');value=rule.get('match_value')
        if ci is not None:
            col=next((c for c in t['columns'] if c['column']==ci),None)
            if isinstance(ci,bool) or not col or value is None or not any(str(e['value']).casefold()==str(value).casefold() for e in observed_column_values(t,col)):raise ValueError('A semantic selector must exactly match a supplied categorical value.')
        elif value is not None:raise ValueError('A table-wide rule cannot have a row selector value.')
        if rule.get('kind') is not None and rule['kind'] not in KINDS:raise ValueError('Invalid economy kind.')
        for prop in rule.get('properties',[]):
            v=prop.get('value')
            if prop.get('name') not in RESOURCE_PROPERTIES or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('Invalid semantic resource property.')
    for fact in document.get('facts',[]):
        refs(fact.get('source_ids'))
        allrefs=list(fact['source_ids'])+[a['source_id'] for a in fact['attributes']]
        allrefs += [s for key in ['recipes','properties','connections'] for part in fact.get(key,[]) for s in part['source_ids']]
        refs(allrefs)
    for h in document.get('context_hints',[]):
        refs(h.get('source_ids'));v=h.get('value')
        if h.get('name') not in CONTEXT_NAMES or (v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1)):raise ValueError('Invalid game-context interpretation.')
        if h['name']=='crafting_centric':
            meanings={next((c['local_field'] for c in tables[source[s]['table_id']]['columns'] if c['column']==source[s].get('column')),None) for s in h['source_ids']}
            if meanings=={'upgrade_material'}:raise ValueError('Upgrade materials alone do not establish crafting-centric context.')
    return document

def merge_facts(local,additional,parsed,source=None):
    """Enrich one evidenced row, retaining its stable identity and explicit fields."""
    source=cells(parsed) if source is None else source
    by_row={};tables={t['id']:t for t in parsed['tables']}
    for f in local['facts']:
        for sid in f['source_ids']:
            c=source[sid];by_row[(c['table_id'],c['record_index'])]=f
    changed=0
    for fact in additional:
        validate_facts({'facts':[fact]},parsed,source)
        rows={(source[s]['table_id'],source[s]['record_index']) for s in fact['source_ids']}
        targets={id(by_row[r]):by_row[r] for r in rows if r in by_row}
        if len(targets)!=1:raise ValueError('A semantic fact must identify one existing source record.')
        current=next(iter(targets.values()));oldname=current['name']
        rowkey=next(r for r in rows if by_row.get(r) is current);table=tables[rowkey[0]];values=table['values'][rowkey[1]]
        explicit={resolved_field(table,ci) for ci,h in enumerate(table['headers']) if values[ci] not in [None,'']}
        for key in ['name','merchant','inventory']:
            if key=='name' and 'name' in explicit:continue
            if fact.get(key) and (key=='name' or not current.get(key)):current[key]=fact[key]
        if current.get('resource')==oldname:current['resource']=current['name']
        if 'currency' not in explicit and fact.get('resource') and fact['resource']!=fact['name']:current['resource']=fact['resource']
        if current['kind']=='resource':current['kind']=fact['kind']
        for key in ['categories','functional_roles','source_ids','notes']:current[key]=list(dict.fromkeys(current.get(key,[])+fact.get(key,[])))
        attrs={a['field']:a for a in current['attributes']}
        for a in fact['attributes']:
            if a['field'] not in attrs or attrs[a['field']]['value'] is None:attrs[a['field']]=a
        current['attributes']=list(attrs.values())
        props={p['name']:p for p in current.get('properties',[])}
        for p in fact.get('properties',[]):
            if p['name'] not in props or props[p['name']]['value'] is None:props[p['name']]=p
        current['properties']=list(props.values())
        # An LLM may clarify an unknown recipe, while exact local quantities
        # remain authoritative. Stable source evidence prevents duplicate offers.
        for recipe in fact.get('recipes',[]):
            matching=[r for r in current['recipes'] if set(r['source_ids'])==set(recipe['source_ids'])]
            if not matching:current['recipes'].append(recipe)
            elif any(x['quantity'] is None for r in matching for side in ['inputs','outputs'] for x in r[side]):
                current['recipes']=[r for r in current['recipes'] if r not in matching]+[recipe]
        current['connections']+=fact.get('connections',[]);changed+=1
    return changed

def apply_review(parsed,document):
    plan=review_plan(parsed)
    validate_review(document,plan)
    mapped=copy.deepcopy(parsed);tables={t['id']:t for t in mapped['tables']}
    for m in document.get('column_mappings',[]):
        if m['field']=='ignore':continue
        t=tables[m['table_id']];ci=m['column']
        if not heading(t['headers'][ci]):t.setdefault('column_mapping',{})[str(ci)]=m['field']
    facts=offline_facts(mapped);index={f['record_id']:f for f in facts['facts']};affected=set()
    for rule in document.get('semantic_rules',[]):
        t=tables[rule['table_id']];ci=rule['match_column']
        for ri,row in enumerate(t['values']):
            if ci is not None and str(row[ci]).casefold()!=str(rule['match_value']).casefold():continue
            f=index.get(f'{t["id"]}:record:{ri}')
            if f is None:continue
            if f['kind']=='resource' and rule.get('kind'):f['kind']=rule['kind']
            for key in ['categories','functional_roles']:f[key]=list(dict.fromkeys(f[key]+rule.get(key,[])))
            present={p['name'] for p in f['properties'] if p['value'] is not None}
            for prop in rule.get('properties',[]):
                if prop['name'] not in present:f['properties'].append({**prop,'source_ids':rule['source_ids'],'reason':rule['reason']+' (LLM interpretation applied by an explicit table/row rule.)'})
            f['notes'].append(rule['reason']);affected.add(f['record_id'])
    enriched=0;fact_issues=[];source=None
    for f in document.get('facts',[]):
        if source is None:source=cells(mapped)
        try:enriched+=merge_facts(facts,[f],mapped,source)
        except (ValueError,KeyError,TypeError) as exc:fact_issues.append('Rejected exceptional fact: '+str(exc)[:300])
    prior=document.get('import_diagnostics',{})
    accepted=len(document.get('column_mappings',[]))+len(document.get('semantic_rules',[]))+enriched+len(document.get('context_hints',[]))
    rejected=prior.get('rejected_components',0)+len(fact_issues)
    state='partial' if accepted and rejected else 'applied' if accepted else 'rejected' if rejected else 'reviewed_no_changes'
    facts.update(method='offline_rules_v2' if state=='rejected' else 'llm_semantic_v41',model=document.get('model'),context_hints=[h for h in document.get('context_hints',[]) if h.get('value') is not None],api_usage=document.get('api_usage',{}))
    facts['notes']+=document.get('notes',[])+fact_issues+[plan['coverage']]
    facts['import_diagnostics']={**prior,'llm_application':state,'accepted_components':accepted,'rejected_components':rejected,'validation_issues':prior.get('validation_issues',[])+fact_issues,'source_rows':plan['source_rows'],'sampled_rows':plan['sampled_rows'],'rule_applied_rows':len(affected),'llm_records':enriched,'local_fallback_records':len(facts['facts'])-enriched,'restored_numeric_fields':0,'coverage':plan['coverage'],'omitted_tables':plan['omitted_tables'],'omitted_columns':plan['omitted_columns'],'truncated_cells':plan['truncated_cells']}
    return mapped,facts
