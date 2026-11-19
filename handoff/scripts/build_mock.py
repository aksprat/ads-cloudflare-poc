import json,glob,re,collections as C
R=[json.load(open(f)) for f in sorted(glob.glob('out/*.json'))]
def k(r):
    m=re.match(r'(\d{8})T(\d{2})(\d{2})(\d{2})Z_',r['file']); return m.group(1)+m.group(2)+m.group(3)+m.group(4)
R.sort(key=k)
H=[]
for r in R:
    c=r['c']; m=re.match(r'\d{8}T(\d{2})(\d{2})',r['file'])
    # label by window END time
    e=re.match(r'\d{8}T\d{6}Z_\d{8}T(\d{2})(\d{2})',r['file'])
    pk=C.Counter()
    for a,b in c.get('pv_kind',{}).items(): pk[a.split('|')[1]]+=b
    pur=C.Counter()
    for a,b in c.get('pv_crawler_op',{}).items(): pur[a.split('|')[2]]+=b
    reg=c.get('otlp_region',{})
    H.append({'t':'%s:%s'%e.groups(),'n':r['n'],'telemetry':sum(reg.values()),'browser':c['class'].get('browser',0),'sdk_infra':c['class'].get('sdk_infra',0),
     'http_lib':c['class'].get('http_lib',0),'ai_client':c['class'].get('ai_client',0),'crawler':c['class'].get('crawler',0),
     'api_total':c.get('api_total',{}).get('n',0),'api401':c.get('api_status',{}).get('401',0),'api429':c.get('api_status',{}).get('429',0),
     'logging5xx':c.get('5xx_host',{}).get('logging.digitalocean.com',0),'mcp':sum(c.get('mcp_hosts',{}).values()),
     'pv_human':pk['human'],'pv_crawler':pk['crawler'],'pv_other':pk['other'],
     'cr_training':pur['training'],'cr_search':pur['search'],'cr_user':pur['user'],'cr_monitor':pur['monitor'],'cr_other':sum(v for a,v in pur.items() if a not in('training','search','user','monitor')),
     'r_fra1':reg.get('fra1',0),'r_nyc3':reg.get('nyc3',0),'r_ams3':reg.get('ams3',0),'r_nbg1':reg.get('nbg1',0),'r_sgp1':reg.get('sgp1',0),'r_other':sum(reg.values())-sum(reg.get(x,0) for x in('fra1','nyc3','ams3','nbg1','sgp1'))})
T=C.defaultdict(C.Counter)
for r in R:
    for a,v in r['c'].items():
        for x,y in v.items(): T[a][x]+=y
pn=T['pv_n']; 
cost={q:{'views':pn[q],'kb_per_view':round(T['pv_bytes'][q]/pn[q]/1024,1),'origin_ms_per_view':round(T['pv_origin_ms'][q]/pn[q],0)} for q in ('human','crawler','other')}
print(cost)
cm={}
for key,nm in (('api401_ua','s401'),('api429_ua','s429')):
    for u,v in T[key].items():
        if u.startswith('cert-manager'): ver=re.search(r'v(\d+\.\d+)',u); 
        else: ver=None
        if ver: cm.setdefault('v'+ver.group(1),{'s401':0,'s429':0})[nm]+=v
cmrows=sorted(({'version':a,**b} for a,b in cm.items()),key=lambda x:-(x['s401']+x['s429']))[:8]
print(cmrows)
print('godo',T['api401_ua'].get('godo'),T['api429_ua'].get('godo'),'doctl',T['api401_ua'].get('doctl'),'truffle',T['api401_ua'].get('TruffleHog'))
json.dump({'hourly':H,'cost':cost,'cm':cmrows},open('../mock/mock_data.json','w'),separators=(',',':'))
# peaks
import statistics as st
for key in ['api429','api401','telemetry','browser','ai_client','logging5xx']:
    v=[h[key] for h in H]; print(key,min(v),max(v),round(st.mean(v)),round(max(v)/min(v),2))
print([h['t'] for h in H])
