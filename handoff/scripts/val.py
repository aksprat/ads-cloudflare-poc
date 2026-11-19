import json,glob,collections as C,re
R3=[json.load(open(f)) for f in sorted(glob.glob('out3/*.json'))]
R2=[json.load(open(f)) for f in sorted(glob.glob('out2/*.json'))]
T=C.defaultdict(C.Counter); S=C.defaultdict(set)
for r in R3:
    for k,v in r['c'].items():
        for a,b in v.items(): T[k][a]+=b
    for k,v in r['sets'].items(): S[k]|=set(v)
print('headers non-empty rows:',sum(r['hdr'] for r in R3),'of',sum(r['n'] for r in R3), C.Counter({k:v for r in R3 for k,v in r['hdrkeys'].items()}).most_common(5))
# JA3
fam=C.defaultdict(C.Counter)
for k,v in T['ja3_fam'].items(): f,j=k.split('|'); fam[f][j]+=v
named=['Cursor','codex-mcp-client','Claude-User','claude-code','opencode']
generic=['node','undici','python-httpx2','python-httpx','Bun','Go-http-client','curl','axios','python-requests']
for f in named+generic:
    if f in fam:
        t=sum(fam[f].values()); top=fam[f].most_common(1)[0][1]
        print('JA3',f,'reqs',t,'distinct',len(fam[f]),'top1share',round(top/t,2))
nj={j for f in named if f in fam for j in fam[f]}
for f in generic:
    if f in fam:
        t=sum(fam[f].values()); sh=sum(v for j,v in fam[f].items() if j in nj)
        print('generic',f,'requests whose JA3 also used by a named agent:',round(sh/t,3))
for f in named:
    if f in fam:
        others={g for g in generic if g in fam}
        ov=sum(v for j,v in fam[f].items() if any(j in fam[g] for g in others))
        print('named',f,'share of its requests with JA3 also seen under generic UA:',round(ov/sum(fam[f].values()),3))
# docs/www status
ps=C.defaultdict(C.Counter)
for k,v in T['pv_status'].items(): h,kind,sc=k.split('|'); ps[(h,kind)][sc]+=v
for k,v in sorted(ps.items()):
    t=sum(v.values()); print('PV',k,t,{a:round(b/t*100,1) for a,b in v.items()})
print('top 404 www/docs',T['p404'].most_common(8)); print('top 3xx',T['p3xx'].most_common(6))
# p95 by colo
def pc(cnt,q):
    t=sum(cnt.values()); acc=0
    for b in sorted(cnt):
        acc+=cnt[b]
        if acc>=q*t: return b
col=C.defaultdict(lambda:C.defaultdict(C.Counter))
for k,v in T['ttfb_ctl'].items(): g,co,b=k.split('|'); col[g][co][int(b)]+=v
for g in ['api','cloud']:
    print('p95 TTFB by colo',g,[(co,sum(c.values()),pc(c,.5),pc(c,.95)) for co,c in sorted(col[g].items(),key=lambda x:-sum(x[1].values()))[:8]])
oc=C.defaultdict(C.Counter)
for k,v in T['ttfb_otlp'].items(): co,b=k.split('|'); oc[co][int(b)]+=v
print('otlp colo p50/p95',[(co,sum(c.values()),pc(c,.5),pc(c,.95)) for co,c in sorted(oc.items(),key=lambda x:-sum(x[1].values()))[:8]])
# cohorts
for a,b in [('mcp_ips','cloud_browser_ips'),('mcp_ips','api_sdk_ips'),('api_sdk_ips','cloud_browser_ips')]:
    A,B=S[a],S[b]; print('cohort overlap',a,len(A),b,len(B),'overlap',len(A&B),round(len(A&B)/max(len(A),1),3))
# persistence from out2 (per file counters)
for key in ['api_ip_401_dom','api_ip_429_dom','api_ip_401_other','api_ip_429_other']:
    pres=C.Counter(); vol=C.Counter()
    for r in R2:
        for ip,v in r['c'].get(key,{}).items(): pres[ip]+=1; vol[ip]+=v
    n=len(pres); tv=sum(vol.values())
    for thr in (1,3,8):
        ips=[ip for ip,k in pres.items() if k>=thr]
        print(key,'IPs in >=%d slices'%thr,len(ips),'of',n,'volume share',round(sum(vol[i] for i in ips)/tv,3))
# retry success: ips with 429/401 that also have 200 in same slice
for key in ['api_ip_401_dom','api_ip_429_dom']:
    both=tot=0
    for r in R2:
        ips=set(r['c'].get(key,{})); ok=set(r['sets'].get('api_ok_ips',[]))
        tot+=len(ips); both+=len(ips&ok)
    print(key,'IP-slices with the error',tot,'also saw a 200 same slice',both,round(both/tot,3))
# MCP repeat use
pres=C.Counter()
for r in R2:
    for k,v in r['sets'].items():
        if k.startswith('mcp_ip_all|'):
            for ip in v: pres[(k.split('|')[1],ip)]+=1
fams=C.defaultdict(list)
for (f,ip),k in pres.items(): fams[f].append(k)
for f,v in sorted(fams.items(),key=lambda x:-len(x[1]))[:6]: print('MCP repeat',f,'IPs',len(v),'seen in >=2 slices',sum(1 for k in v if k>=2),'>=6',sum(1 for k in v if k>=6))
# named vs generic in MCP
m=C.Counter()
for r in R2:
    for k,v in r['c'].get('mcp_fam_status',{}).items(): m[k.split('|')[0]]+=v
nm=sum(m[f] for f in ['Cursor','codex-mcp-client','Claude-User','claude-code','opencode','VPN-Fleet-MCP']); tot=sum(m.values())
print('MCP named agents share',round(nm/tot,3),'generic libs',round(sum(m[f] for f in ['python-httpx2','undici','node','Bun','python-httpx'])/tot,3),dict(m.most_common(12)))
