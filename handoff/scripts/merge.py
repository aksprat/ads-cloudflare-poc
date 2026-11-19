import json,glob,re,collections as C
fs=sorted(glob.glob('out/*.json'))
R=[json.load(open(f)) for f in fs]
def hour(fn):
    m=re.match(r'(\d{8})T(\d{2})(\d{2})(\d{2})Z_(\d{8})T(\d{2})(\d{2})',fn); return int(m.group(6)) if m else -1
tot=C.defaultdict(C.Counter); hourly=[]
allkeys=set()
for r in R:
    allkeys|=set(r['keys'] or [])
    for k,v in r['c'].items():
        for a,b in v.items(): tot[k][a]+=b
    c=r['c']; nt=sum(c.get('nt_host',{}).values()); ot=sum(c.get('otlp_region',{}).values())
    pv=c.get('pv_kind',{}); crawl=sum(v for a,v in pv.items() if a.endswith('|crawler')); allpv=sum(pv.values())
    hourly.append(dict(file=r['file'],h=hour(r['file']),n=r['n'],otlp=ot,nt=nt,api=c.get('api_total',{}).get('n',0),
      ai=sum(v for a,v in c.get('class',{}).items() if a=='ai_client'),crawler_cls=c.get('class',{}).get('crawler',0),
      pv=allpv,pv_crawler=crawl,s429=c.get('api_status',{}).get('429',0),s401=c.get('api_status',{}).get('401',0),
      mcp=sum(c.get('mcp_hosts',{}).values())))
hourly.sort(key=lambda x:(x['file'][:8],x['file'][16:]))
json.dump({'tot':{k:dict(v) for k,v in tot.items()},'hourly':hourly,'keys':sorted(allkeys),'files':len(R)},open('merged.json','w'))
print('files',len(R),'requests',sum(r['n'] for r in R))
print('new keys vs first-sample (JA4/verified/etc):',[k for k in sorted(allkeys) if re.search('ja4|verified|bot|ai|signal',k,re.I)])
print('field count',len(allkeys))
for h in hourly: print(h)
def top(k,n=15): print('==',k,sum(tot[k].values()),tot[k].most_common(n))
for k in ['class','status_all','nt_host','api_status','sec_action','leak','botsrc','mcp_hosts','mcp','mcp_referer','pv_kind','pv_cache','pv_crawler_op','pv_crawler_sec','pv_human_sec','pv_crawler_path','bot_tags','bot_score_crawler','bot_ids','special_path','utm_source','ai_ref|crawler','ai_ref|human','ai_ref|ai_client','ai_ref|other','ref_sec','ai_ua','agent_ep','api_err','api429_ua','api401_ua','api_ua_class','5xx_host','otlp_ua','otlp_non200','otlp_region','sec','other_ua','crawler_all_host','attack_lowscore_host','country','colo']:
    if k in tot: top(k)
for k in tot:
    if k.startswith('ref_host|') or k.startswith('ttfb|'): pass
