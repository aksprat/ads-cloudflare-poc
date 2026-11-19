import json,sys,re,gzip,os,hashlib,collections as C
from urllib.parse import urlparse,parse_qs
from multiprocessing import Pool
HERE=os.path.dirname(os.path.abspath(__file__))
IN=os.environ.get('LOGS_DIR',os.path.join(HERE,'..','..'))
OUT=os.path.join(HERE,'..','results','out2')
os.makedirs(OUT,exist_ok=True)
H=lambda s:hashlib.md5(s.encode()).hexdigest()[:8]
norm=lambda p:re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27}|\b\d{3,}\b|[0-9a-f]{24,}','{id}',p)
CL=re.compile(r'(GPTBot|OAI-SearchBot|ChatGPT-User|ClaudeBot|Claude-User|Claude-SearchBot|PerplexityBot|Perplexity-User|Googlebot|Google-Extended|bingbot|Bytespider|Amazonbot|Applebot|meta-externalagent|CCBot|YandexBot|facebookexternalhit)',re.I)
AIREF=re.compile(r'chatgpt|openai|perplexity|claude|gemini|copilot|you\.com|phind|kagi|poe\.com|mistral|grok|deepseek',re.I)
AIUTM=re.compile(r'chatgpt|openai|perplexity|claude|gemini|copilot|phind|kagi|poe|mistral|grok|deepseek',re.I)
UAF=lambda ua:re.sub(r'[/ ].*','',ua)[:28] or 'empty'
def run(fn):
    c=C.defaultdict(C.Counter); sets=C.defaultdict(set); n=0
    op=gzip.open if fn.endswith('.gz') else open
    for line in op(os.path.join(IN,fn),'rt',errors='replace'):
        d=json.loads(line); n+=1
        h=d['ClientRequestHost'].split(':')[0]; ua=d['ClientRequestUserAgent']; st=d['EdgeResponseStatus']; p=d['ClientRequestPath']
        if st==402: c['s402'][h]+=1
        if h.startswith('otlp-'): continue
        ip=H(d['ClientIP'])
        bt=d['BotTags']; ver=('verifiedBot' in bt) or d['BotScoreSrc']=='Verified Bot'
        m=CL.search(ua)
        if m:
            c['crawl_verified'][m.group(1).lower()+'|'+('verified' if ver else 'unverified')]+=1
            c['crawl_asn'][m.group(1).lower()+'|'+str(d['ClientASN'])]+=1
        if h=='mcp.digitalocean.com':
            f=UAF(ua); oc='401' if st==401 else ('ok' if st in(200,202,204) else ('wk404' if st==404 else str(st)))
            c['mcp_fam_status'][f+'|'+d['ClientRequestMethod']+'|'+('wellknown' if 'well-known' in p else 'mcp')+'|'+oc]+=1
            sets['mcp_ip|'+f+'|'+oc].add(ip)
            sets['mcp_ip_all|'+f].add(ip)
            if st==404: c['mcp404_path'][p[:80]]+=1
            c['mcp_path'][p[:60]]+=1
        if h=='api.digitalocean.com' and p.startswith('/mcp'): c['api_mcp'][d['ClientRequestMethod']+' '+p[:20]+' '+str(st)+' '+UAF(ua)]+=1
        if h=='cloud.digitalocean.com':
            mm=re.match(r'/gen-ai/auth/agents/([^/]+)/token',p)
            if mm: sets['agent_token_ids'].add(H(mm.group(1))); c['agent_token_status'][str(st)]+=1
        if h=='api.digitalocean.com':
            mm=re.match(r'/v2/agents/sessions/([^/]+)',p)
            if mm: sets['agent_sessions'].add(H(mm.group(1)))
            mm=re.match(r'/v2/gen-ai/knowledge_bases/([^/]+)',p)
            if mm: sets['kb_ids'].add(H(mm.group(1)))
            if p.startswith('/v2/agents') or p.startswith('/v2/gen-ai'): sets['agent_api_ips'].add(ip)
            if st in(401,429):
                k='dom' if '/domains/' in p else 'other'
                c['api_ip_%d_%s'%(st,k)][ip]+=1
                c['api_asn_%d'%st][str(d['ClientASN'])]+=1
                c['api_fam_%d_%s'%(st,k)][UAF(ua)]+=1
            if st==200: sets['api_ok_ips'].add(ip)
        if h=='logging.digitalocean.com':
            c['log_status'][str(st)]+=1
            if st>=500: c['log5xx_path'][re.sub(r'/[^/]+$','/{x}',p)[:50]+'|'+str(st)]+=1; c['log5xx_ua'][UAF(ua)]+=1
            c['log_fam'][UAF(ua)]+=1
            c['log_origin_ms'][str(min(d['OriginResponseDurationMs']//500*500,10000))]+=1
        if 'TruffleHog' in ua or 'Fuzz Faster' in ua or 'vanta.com' in ua or 'GitHub-Hookshot' in ua:
            c['tool_host'][UAF(ua)+'|'+h+'|'+str(st)]+=1
        if h in('www.digitalocean.com','docs.digitalocean.com') and d['ClientRequestMethod']=='GET' and (p.endswith('.md') or 'llms' in p):
            kind='browser' if ua.startswith('Mozilla') and not CL.search(ua) else 'nonbrowser'
            c['md_path|'+kind][h.split('.')[0]+norm(p)[:60]]+=1
        uri=d['ClientRequestURI']; ref=d['ClientRequestReferer']
        aiu=None
        if 'utm_source' in uri:
            q=parse_qs(urlparse(uri).query); s=(q.get('utm_source') or [''])[0]
            if AIUTM.search(s): aiu='utm:'+s[:20]
        if not aiu and ref and AIREF.search(urlparse(ref).netloc if '://' in ref else ref): aiu='ref:'+(urlparse(ref).netloc if '://' in ref else ref)[:30]
        if aiu and d['ClientRequestMethod']=='GET' and h in('www.digitalocean.com','docs.digitalocean.com','cloud.digitalocean.com','marketplace.digitalocean.com'):
            c['ai_ref_src'][aiu]+=1
            sec=('/'+p.strip('/').split('/')[0]) if p!='/' else '/'
            c['ai_ref_landing'][h.split('.')[0]+'|'+sec]+=1
            c['ai_ref_path'][h.split('.')[0]+norm(p)[:70]]+=1
    res={'n':n,'c':{k:{a:b for a,b in v.items()} for k,v in c.items()},'sets':{k:sorted(v) for k,v in sets.items()}}
    json.dump(res,open(os.path.join(OUT,fn.replace('.gz','')+'.json'),'w'))
    return fn,n
if __name__=='__main__':
    fs=sorted(f for f in os.listdir(IN) if f.endswith('.log.gz')); fs.append('20261110T143829Z_20261110T143930Z_bb2c8e23')
    with Pool(int(sys.argv[1])) as p:
        for fn,n in p.imap_unordered(run,fs): print(fn,n,flush=True)
