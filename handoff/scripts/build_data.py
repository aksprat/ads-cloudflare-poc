import json,glob,re,os,collections as C
R=[json.load(open(f)) for f in sorted(glob.glob('out/*.json'))]
R2=[json.load(open(f)) for f in sorted(glob.glob('out2/*.json'))]
def key(r):
    m=re.match(r'(\d{8})T(\d{2})(\d{2})(\d{2})Z_(\d{8})T(\d{2})(\d{2})(\d{2})Z',r['file']); return m.group(1)+m.group(2)+m.group(3)
R.sort(key=key)
T=C.defaultdict(C.Counter)
for r in R:
    for k,v in r['c'].items():
        for a,b in v.items(): T[k][a]+=b
T2=C.defaultdict(C.Counter); S=C.defaultdict(set)
for r in R2:
    for k,v in r['c'].items():
        for a,b in v.items(): T2[k][a]+=b
    for k,v in r['sets'].items(): S[k]|=set(v)
W=lambda name,rows:json.dump(rows,open('data/%s.json'%name,'w'),separators=(',',':'))
N=sum(r['n'] for r in R); nt=sum(T['class'].values()); ot=sum(T['otlp_region'].values())
pct=lambda a,b:round(100*a/b,1)
# hourly
rows=[]
for r in R:
    c=r['c']; m=re.match(r'\d{8}T(\d{2})(\d{2})\d{2}Z_\d{8}T(\d{2})',r['file']); 
    rows.append({'slice':'%s:%s'%(m.group(1),m.group(2)),'requests':r['n'],'telemetry':sum(c['otlp_region'].values()),'browser':c['class'].get('browser',0),
      'sdk_infra':c['class'].get('sdk_infra',0),'http_lib':c['class'].get('http_lib',0),'ai_client':c['class'].get('ai_client',0),'crawler':c['class'].get('crawler',0),
      'api_401':c.get('api_status',{}).get('401',0),'api_429':c.get('api_status',{}).get('429',0),'api_total':c.get('api_total',{}).get('n',0),
      'logging_5xx':c.get('5xx_host',{}).get('logging.digitalocean.com',0)})
W('hourly',rows)
# client classes
lab={'browser':'Browsers','sdk_infra':'SDKs, IaC and infra agents','http_lib':'HTTP libraries','other':'Other (webhooks, scanners, apps)','crawler':'Crawlers and monitors','empty':'Empty user agent','ai_client':'AI and MCP clients'}
W('client_classes',[{'client_type':lab[k],'requests':v,'share_pct':pct(v,nt)} for k,v in T['class'].most_common()])
# mcp clients
fam=C.defaultdict(lambda:C.Counter())
for k,v in T2['mcp_fam_status'].items():
    f,meth,kind,oc=k.split('|'); fam[f]['total']+=v
    fam[f][('ok' if oc=='ok' else oc if oc in('401','wk404') else 'other')]+=v
mrows=[]
for f in sorted(fam,key=lambda f:-fam[f]['total'])[:9]:
    a=S['mcp_ip_all|'+f]; u=S.get('mcp_ip|%s|401'%f,set()); o=S.get('mcp_ip|%s|ok'%f,set())
    mrows.append({'client':f,'requests':fam[f]['total'],'ok':fam[f]['ok'],'challenge_401':fam[f]['401'],'discovery_404':fam[f]['wk404'],'distinct_ips':len(a),'ips_reached_ok':len(o),'ips_stuck_at_401':len(u-o),'completion_pct':pct(len(o),len(a))})
W('mcp_clients',mrows)
# agent activity
W('agent_activity',[{'metric':'Agent IDs refreshing tokens','value':len(S['agent_token_ids']),'note':'distinct /gen-ai/auth/agents/{id}/token'},
 {'metric':'Agent sessions','value':len(S['agent_sessions']),'note':'distinct /v2/agents/sessions/{id}'},
 {'metric':'Knowledge bases used','value':len(S['kb_ids']),'note':'distinct /v2/gen-ai/knowledge_bases/{id}'},
 {'metric':'Client IPs on agent APIs','value':len(S['agent_api_ips']),'note':'/v2/agents and /v2/gen-ai'},
 {'metric':'Token refresh requests','value':sum(T2['agent_token_status'].values()),'note':'all statuses'},
 {'metric':'MCP server requests','value':sum(T['mcp_hosts'].values()),'note':'mcp.digitalocean.com'}])
# api endpoints
ep=C.defaultdict(lambda:C.Counter())
for k,v in T['api_err'].items():
    st,rest=k.split('|',1); ep[rest][st]+=v
erows=[{'endpoint':e,'status_401':ep[e]['401'],'status_429':ep[e]['429'],'status_404':ep[e]['404']} for e in sorted(ep,key=lambda e:-(ep[e]['401']+ep[e]['429']))[:9]]
W('api_endpoints',erows)
cl=C.defaultdict(lambda:C.Counter())
for st in('401','429'):
    for k in('dom',):
        for f,v in T2['api_fam_%s_%s'%(st,k)].items(): cl[f]['s'+st]+=v
    for f,v in T['api%s_ua'%st].items(): pass
W('api_clients',[{'client':f.replace('cert-manager-challenges','cert-manager (DNS-01)'),'status_401':cl[f]['s401'],'status_429':cl[f]['s429']} for f in sorted(cl,key=lambda f:-(cl[f]['s401']+cl[f]['s429']))[:6]])
cons=[]
for key,name in [('api_ip_401_dom','401 on domain records'),('api_ip_429_dom','429 on domain records'),('api_ip_401_other','401 on other endpoints'),('api_ip_429_other','429 on other endpoints')]:
    v=sorted(T2[key].values(),reverse=True); tot=sum(v)
    cons.append({'segment':name,'requests':tot,'distinct_ips':len(v),'top10_share_pct':pct(sum(v[:10]),tot),'top100_share_pct':pct(sum(v[:100]),tot)})
W('api_concentration',cons)
# api summary
api=sum(T['api_total'].values())
# latency percentiles
def pc(cnt,q):
    tot=sum(cnt.values()); acc=0
    for t in sorted(int(x) for x in cnt):
        acc+=cnt[str(t)]
        if acc>=q*tot: return t
lat=[]
for g,nm in [('otlp','OTLP ingest'),('api','api.digitalocean.com'),('cloud','cloud.digitalocean.com'),('www','www.digitalocean.com'),('docs','docs.digitalocean.com'),('mcp','mcp.digitalocean.com')]:
    c=T['ttfb|'+g]; lat.append({'host':nm,'requests':sum(c.values()),'p50_ms':pc(c,.5),'p95_ms':pc(c,.95),'p99_ms':pc(c,.99)})
W('latency',lat)
# regions
reg=[]
for dim,k,n in [('Country','country',10),('Edge location','colo',10),('OTLP region','otlp_region',12)]:
    for a,b in T[k].most_common(n): reg.append({'dimension':dim,'name':a.upper() if dim!='OTLP region' else a,'requests':b})
W('regions',reg)
# crawlers (all hosts, verified flag)
cv=C.defaultdict(lambda:C.Counter())
for k,v in T2['crawl_verified'].items(): b,s=k.split('|'); cv[b][s]+=v
purpose={'gptbot':'Training','oai-searchbot':'Search index','chatgpt-user':'User-triggered','claudebot':'Training','claude-user':'User-triggered','perplexitybot':'Search index','googlebot':'Search index','bingbot':'Search index','bytespider':'Training','amazonbot':'Search index','applebot':'Search index','meta-externalagent':'Training','yandexbot':'Search index','facebookexternalhit':'Link preview'}
W('crawlers',[{'operator':b,'purpose':purpose.get(b,'Other'),'verified':cv[b]['verified'],'unverified':cv[b]['unverified'],'total':cv[b]['verified']+cv[b]['unverified'],'unverified_pct':pct(cv[b]['unverified'],cv[b]['verified']+cv[b]['unverified'])} for b in sorted(cv,key=lambda b:-(sum(cv[b].values())))[:14]])
# page views
pk=C.defaultdict(int)
for k,v in T['pv_kind'].items(): pk[k.split('|')[1]]+=v
pvt=sum(pk.values()); pcache=C.defaultdict(lambda:C.Counter())
for k,v in T['pv_cache'].items(): a,b=k.split('|'); pcache[a][b]+=v
lab2={'human':'Browsers','crawler':'Crawlers and monitors','other':'Other clients','ai_client':'AI clients'}
W('page_views',[{'client_type':lab2[k],'page_views':pk[k],'share_pct':pct(pk[k],pvt),'cache_bypass_pct':pct(pcache[k]['bypass'],sum(pcache[k].values())),'cache_hit_pct':pct(pcache[k]['hit'],sum(pcache[k].values()))} for k in ['human','crawler','other','ai_client']])
# crawl sections
secs=T['pv_crawler_sec'].most_common(6); hs=T['pv_human_sec']
W('crawl_sections',[{'section':s,'crawler_views':v,'browser_views':hs.get(s,0),'crawler_to_browser':round(v/max(hs.get(s,1),1),2)} for s,v in secs])
# ai referrals
W('ai_referrals',[{'source':k,'visits':v} for k,v in T2['ai_ref_src'].most_common(6)])
W('ai_landing',[{'page':re.sub(r'^(www|docs|cloud)','\\1 ',k),'visits':v} for k,v in T2['ai_ref_path'].most_common(6)])
# fleet
ver=C.Counter()
for k,v in T['otlp_ua'].items(): ver[k]+=v
tot=sum(ver.values())
W('collectors',[{'collector':k.replace('OpenTelemetry Collector','OTel Collector'),'requests':v,'share_pct':pct(v,tot)} for k,v in ver.most_common(7)])
# security
W('security',[{'rule':re.sub(r'^[^|]*\|','',k).replace('|',': ')[:60],'events':v} for k,v in T['sec'].most_common(8)])
W('signals',[{'signal':'Token scanner (TruffleHog) calls','events':sum(v for k,v in T2['tool_host'].items() if k.startswith('TruffleHog')),'detail':'401 rejected: 4,846; 200 accepted: 3'},
 {'signal':'Directory fuzzing (ffuf)','events':sum(v for k,v in T2['tool_host'].items() if k.startswith('Fuzz')),'detail':'all 404'},
 {'signal':'logging.digitalocean.com HTTP 500','events':T2['log_status']['500'],'detail':'12% of 55,002 requests; path /applications/{id}'},
 {'signal':'GitHub webhooks to App Platform','events':sum(v for k,v in T2['tool_host'].items() if k.startswith('GitHub-Hookshot')),'detail':'apps-inbound.digitalocean.com'}])
# sizing
sz=[os.path.getsize('/Users/pramir/MyWork/ads_cloudeflare/'+f) for f in os.listdir('/Users/pramir/MyWork/ads_cloudeflare') if f.endswith('.log.gz')]
avg_rows=N/len(R); files_month=30*86400/65
W('sizing',[{'metric':'Rows per minute file','sample':round(avg_rows),'month_estimate':round(avg_rows*files_month)},
 {'metric':'Telemetry rows (OTLP)','sample':round(ot/len(R)),'month_estimate':round(ot/len(R)*files_month)},
 {'metric':'Rows excluding telemetry','sample':round(nt/len(R)),'month_estimate':round(nt/len(R)*files_month)},
 {'metric':'Compressed GB','sample':round(sum(sz)/len(sz)/1e9,3),'month_estimate':round(sum(sz)/len(sz)/1e9*files_month)}])
# summary
cs=T['class']; sa=T['api_status']
summ=[('requests',N,'Requests in 25 one-minute files'),('telemetry_share',pct(ot,N),'OTLP ingest, percent of requests'),('non_telemetry',nt,'Requests outside OTLP'),
 ('browser_share',pct(cs['browser'],nt),'Browsers, percent of non-telemetry'),('api_401',pct(sa['401'],api),'api.digitalocean.com 401 rate, percent'),('api_429',pct(sa['429'],api),'api.digitalocean.com 429 rate, percent'),
 ('crawler_pv',pct(pk['crawler'],pvt),'Crawler share of www and docs page views, percent'),('crawler_bypass',pct(pcache['crawler']['bypass'],sum(pcache['crawler'].values())),'Crawler cache bypass, percent'),
 ('gptbot_unverified',pct(cv['gptbot']['unverified'],sum(cv['gptbot'].values())),'GPTBot user agents without verified-bot flag, percent'),
 ('agents',len(S['agent_token_ids']),'Distinct agent IDs refreshing tokens'),('ai_referrals',sum(T2['ai_ref_src'].values()),'Visits from AI assistants'),
 ('logging_500',pct(T2['log_status']['500'],sum(T2['log_status'].values())),'logging.digitalocean.com 500 rate, percent'),('otlp_err',round(100*sum(T['otlp_non200'].values())/ot,4),'OTLP non-200 rate, percent')]
W('summary',[{'metric':a,'value':b,'note':c} for a,b,c in summ])
for f in sorted(glob.glob('data/*.json')): 
    print(os.path.basename(f),os.path.getsize(f)); 
print(json.dumps({r['metric']:r['value'] for r in json.load(open('data/summary.json'))}))
for n in ['mcp_clients','api_endpoints','api_clients','api_concentration','latency','crawlers','page_views','crawl_sections','sizing','collectors','security']:
    print('--',n); [print(r) for r in json.load(open('data/%s.json'%n))]
