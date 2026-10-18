"""Compact optional interpretation. All rows remain in the local economy."""
from __future__ import annotations
import copy,json,re
from auto_import import FIELDS,RESOURCE_PROPERTIES,JSON_COLUMNS,heading,norm,amount,offline_facts

MAX_PLAN_BYTES=18000
METADATA={'game_id','game_name','wiki_base','wiki_home','url','economy_types','economic_score','categories','source_categories','description','inventory_slot','rarity_category','required_level','suggested_level','level','base_price','base_price_min','base_price_max','currency_mentions','xp','xp_mentions','weight_num','durability','upgrade_slots','source','effects','crafting','charges','console_id','plain_text_excerpt','table_rows_json'}|JSON_COLUMNS
FIELDS_ALLOWED=set(FIELDS)|set(RESOURCE_PROPERTIES)|{'functional_roles','ignore'}

def plan(parsed,force=False):
    total=sum(len(t['rows']) for t in parsed['tables'])
    if not total:return {'mode':'skip','reason':'Canonical economy needs no language interpretation.','source_rows':0}
    # Preserve the richer fact adapter for explicitly requested small documents.
    if force and total<=12:
        candidate=copy.deepcopy(parsed)
        candidate['canonical']=None;candidate['canonical_files']=[]
        if len(json.dumps(candidate,ensure_ascii=False).encode())<=MAX_PLAN_BYTES:
            return {'mode':'facts','parsed':candidate,'source_rows':total}
    tables=[];omitted=0
    for t in parsed['tables']:
        unknown=[]
        for ci,h in enumerate(t['headers']):
            if heading(h) or norm(h) in METADATA or re.search(r'_(min|max|id|json)$',norm(h)):continue
            # A column meaning is inferred once, then applied to every local row.
            samples=[]
            for ri,row in enumerate(t['values']):
                v=row[ci]
                if v in [None,'']:continue
                if isinstance(v,(dict,list)) or len(str(v))>160:continue
                samples.append({'row':t['coordinates'][ri][ci][0],'value':v})
                if len(samples)==3:break
            if samples:unknown.append({'column':ci,'header':h,'examples':samples})
        if not unknown:continue
        for col in unknown:
            entry=next((x for x in tables if x['table_id']==t['id']),None)
            if entry is None:
                entry={'table_id':t['id'],'file':t['file_name'],'sheet':t['sheet'],'rows':len(t['rows']),'columns':[]};tables.append(entry)
            entry['columns'].append(col)
            if len(json.dumps(tables,ensure_ascii=False).encode())>MAX_PLAN_BYTES-1000:
                entry['columns'].pop();omitted+=1
        tables=[x for x in tables if x['columns']]
    if not tables:return {'mode':'skip','reason':'Known columns and embedded economy fields were processed locally; no API call was needed.','source_rows':total}
    return {'mode':'columns','tables':tables,'source_rows':total,'omitted_columns':omitted}

def apply_columns(parsed,document):
    """Accept only existing, previously unrecognized columns; never fabricated values."""
    mapped=copy.deepcopy(parsed);tables={t['id']:t for t in mapped['tables']}
    seen=set()
    for item in document.get('column_mappings',[]):
        t=tables.get(item.get('table_id'));ci=item.get('column');field=item.get('field')
        if t is None or isinstance(ci,bool) or not isinstance(ci,int) or not 0<=ci<len(t['headers']) or field not in FIELDS_ALLOWED:raise ValueError('Invalid language-model column mapping.')
        if (t['id'],ci) in seen:raise ValueError('Duplicate language-model column mapping.')
        seen.add((t['id'],ci))
        if heading(t['headers'][ci]) or norm(t['headers'][ci]) in METADATA:raise ValueError('A known or protected column cannot be reinterpreted.')
        if field!='ignore':t.setdefault('column_mapping',{})[str(ci)]=field
    facts=offline_facts(mapped);facts['method']='llm_columns_v4'
    facts['notes'].extend(document.get('notes',[]));facts['import_diagnostics']=document.get('import_diagnostics',{})
    facts['api_usage']=document.get('api_usage',{});facts['model']=document.get('model')
    return mapped,facts
