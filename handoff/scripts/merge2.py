import json,glob,collections as C
R=[json.load(open(f)) for f in sorted(glob.glob('out2/*.json'))]
c=C.defaultdict(C.Counter); s=C.defaultdict(set)
for r in R:
    for k,v in r['c'].items():
        for a,b in v.items(): c[k][a]+=b
    for k,v in r['sets'].items(): s[k]|=set(v)
def top(k,n=14): print('==',k,sum(c[k].values()),c[k].most_common(n))
for k in ['s402','crawl_verified','mcp_fam_status','mcp404_path','mcp_path','api_mcp','agent_token_status','log_status','log5xx_path','log5xx_ua','log_fam','tool_host','md_path|nonbrowser','md_path|browser','ai_ref_src','ai_ref_landing','ai_ref_path','api_asn_401','api_asn_429','api_fam_401_dom','api_fam_429_dom','log_origin_ms']:
    if k in c: top(k, 20 if k in('mcp_fam_status','crawl_verified') else 12)
print('== distinct sets'); 
for k in sorted(s): 
    if not k.startswith('mcp_ip'): print(k,len(s[k]))
print('MCP IP funnel by family')
fams=sorted({k.split('|')[1] for k in s if k.startswith('mcp_ip_all')},key=lambda f:-len(s['mcp_ip_all|'+f]))
for f in fams[:10]:
    a=s['mcp_ip_all|'+f]; u=s.get('mcp_ip|%s|401'%f,set()); o=s.get('mcp_ip|%s|ok'%f,set())
    print(f,'ips',len(a),'saw401',len(u),'reached_ok',len(o),'401_never_ok',len(u-o))
for key in ['api_ip_401_dom','api_ip_429_dom','api_ip_401_other','api_ip_429_other']:
    ips=c[key]; tot=sum(ips.values()); v=sorted(ips.values(),reverse=True)
    print(key,'total',tot,'distinct',len(v),'top1',v[0]/tot if v else 0,'top10',sum(v[:10])/tot if v else 0,'top100',sum(v[:100])/tot if v else 0)
