import json,sys,re,gzip,os,collections as C
from urllib.parse import urlparse,parse_qs
from multiprocessing import Pool
HERE=os.path.dirname(os.path.abspath(__file__))
IN=os.environ.get('LOGS_DIR',os.path.join(HERE,'..','..'))
OUT=os.path.join(HERE,'..','results','out')
os.makedirs(OUT,exist_ok=True)
norm=lambda p:re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27}|\b\d{3,}\b|[0-9a-f]{24,}','{id}',p)
def normapi(p):
    p=re.sub(r'^/v2/domains/[^/]+','/v2/domains/{zone}',p)
    return norm(p)[:70]
CRAWL=[('GPTBot','OpenAI','training'),('OAI-SearchBot','OpenAI','search'),('ChatGPT-User','OpenAI','user'),('ClaudeBot','Anthropic','training'),
 ('Claude-SearchBot','Anthropic','search'),('Claude-User','Anthropic','user'),('anthropic-ai','Anthropic','training'),('PerplexityBot','Perplexity','search'),
 ('Perplexity-User','Perplexity','user'),('Google-Extended','Google','training'),('Googlebot','Google','search'),('Google-InspectionTool','Google','search'),
 ('GoogleOther','Google','training'),('bingbot','Microsoft','search'),('Applebot','Apple','search'),('Bytespider','ByteDance','training'),('CCBot','CommonCrawl','training'),
 ('Amazonbot','Amazon','search'),('meta-externalagent','Meta','training'),('FacebookBot','Meta','training'),('facebookexternalhit','Meta','preview'),('cohere','Cohere','training'),
 ('Diffbot','Diffbot','training'),('YouBot','You.com','search'),('DuckAssistBot','DuckDuckGo','user'),('MistralAI','Mistral','user'),('Timpibot','Timpi','training'),
 ('ImagesiftBot','Imagesift','training'),('PetalBot','Huawei','search'),('Sogou','Sogou','search'),('YisouSpider','Yisou','search'),('YandexBot','Yandex','search'),
 ('Baiduspider','Baidu','search'),('SemrushBot','Semrush','seo'),('AhrefsBot','Ahrefs','seo'),('MJ12bot','Majestic','seo'),('DotBot','Moz','seo'),('Screaming Frog','ScreamingFrog','seo'),
 ('CorsairBot','Corsair','unknown'),('yacybot','YaCy','search'),('Slackbot','Slack','preview'),('Twitterbot','X','preview'),('LinkedInBot','LinkedIn','preview'),
 ('Discordbot','Discord','preview'),('TelegramBot','Telegram','preview'),('WhatsApp','Meta','preview'),('SeznamBot','Seznam','search'),('Barkrowler','Babbar','seo'),
 ('Uptime','Monitor','monitor'),('Blackbox Exporter','Monitor','monitor'),('Pingdom','Monitor','monitor'),('UptimeRobot','Monitor','monitor'),('StatusCake','Monitor','monitor'),('upti.my','Monitor','monitor'),('YoPingMe','Monitor','monitor')]
CRL=[(re.compile(re.escape(n),re.I),n,o,p) for n,o,p in CRAWL]
GENERIC=re.compile(r'bot|spider|crawl|scrape|fetch',re.I)
AIUA=re.compile(r'claude|anthropic|openai|chatgpt|codex|copilot|mcp|windsurf|cline|gemini|cursor|perplexity|langchain|llama|agent',re.I)
SDK=re.compile(r'godo|doctl|terraform|pulumi|ansible|do-agent|cert-manager|containerd|kubectl|helm|argo|crossplane|external-dns|csi-digitalocean',re.I)
LIB=re.compile(r'^node|go-http|python|axios|httpx|curl|^bun|okhttp|java|ruby|aiohttp|urllib|wget|undici|deno|libwww|php|rust|reqwest',re.I)
AIREF=re.compile(r'chatgpt|openai|perplexity|claude|gemini|copilot|you\.com|phind|kagi|poe\.com|mistral|grok|deepseek',re.I)
def classify(ua):
    if not ua: return ('empty',None)
    for rx,n,o,p in CRL:
        if rx.search(ua): return ('crawler',(n,o,p))
    if ua.startswith('Mozilla'):
        if GENERIC.search(ua): return ('crawler',('generic-bot','?','unknown'))
        return ('browser',None)
    if AIUA.search(ua) and not re.search(r'do-agent|mongo-agent|ha-agent',ua,re.I): return ('ai_client',None)
    if SDK.search(ua): return ('sdk_infra',None)
    if LIB.search(ua): return ('http_lib',None)
    if GENERIC.search(ua): return ('crawler',('generic-bot','?','unknown'))
    return ('other',None)
def grp(h):
    if h.startswith('otlp-'):return 'otlp'
    if h in('api.digitalocean.com','cloud.digitalocean.com','www.digitalocean.com','docs.digitalocean.com','mcp.digitalocean.com'):return h.split('.')[0]
    return None
SPECIAL=re.compile(r'(robots\.txt|llms(-full)?\.txt|sitemap[^/]*\.xml|\.md$|/\.well-known/[^/]*|/openapi[^/]*\.(json|yaml)|\.mdx$)',re.I)
def run(fn):
    c=C.defaultdict(C.Counter);n=0;keys=None
    op=gzip.open if fn.endswith('.gz') else open
    for line in op(os.path.join(IN,fn),'rt',errors='replace'):
        try:d=json.loads(line)
        except: c['meta']['bad']+=1;continue
        if keys is None: keys=sorted(d.keys())
        n+=1
        h=d['ClientRequestHost'].split(':')[0]; ua=d['ClientRequestUserAgent']; st=d['EdgeResponseStatus']; g=grp(h)
        c['status_all'][st]+=1
        c['country'][d['ClientCountry']]+=1; c['colo'][d['EdgeColoCode']]+=1
        c['leak'][d['LeakedCredentialCheckResult']]+=1
        c['botsrc'][d['BotScoreSrc']]+=1
        if d['EdgeResponseStatus']>=500: c['5xx_host'][h]+=1
        if g:
            t=d['EdgeTimeToFirstByteMs']; c['ttfb|'+g][min(t,5000)]+=1
        if h.startswith('otlp-'):
            c['otlp_region'][h.split('.')[0][5:]]+=1
            c['otlp_ua'][re.sub(r'\(.*','',ua)[:60].strip()]+=1
            if st!=200:c['otlp_non200'][st]+=1
            c['otlp_path'][d['ClientRequestPath']]+=1
            continue
        c['nt_host'][h]+=1
        c['nt_host_status'][h+'|'+str(st)]+=1
        k,info=classify(ua); c['class'][k]+=1
        if k=='other': c['other_ua'][ua[:50]]+=1
        if k=='crawler': c['crawler_all_host'][info[0]+'|'+h]+=1
        if k in('ai_client',) or AIUA.search(ua):
            if not re.search(r'do-agent|mongo-agent|ha-agent',ua,re.I): c['ai_ua'][ua[:60]+'|'+h+'|'+str(st)]+=1
        if h=='mcp.digitalocean.com':
            c['mcp'][ua[:45]+'|'+d['ClientRequestMethod']+'|'+d['ClientRequestPath'][:30]+'|'+str(st)]+=1
            c['mcp_country'][d['ClientCountry']]+=1
        if 'mcp' in h: c['mcp_hosts'][h]+=1
        ref=d['ClientRequestReferer']
        if ref:
            try: rh=urlparse(ref).netloc.lower()
            except: rh=''
            if 'mcp.digitalocean' in rh: c['mcp_referer'][rh]+=1
        p=d['ClientRequestPath']
        if re.search(r'agents|gen-ai|/mcp|inference|serverless-inference|managed-agents',p):
            c['agent_ep'][h+'|'+norm(p)[:55]+'|'+str(st)]+=1
        if h=='api.digitalocean.com':
            c['api_total']['n']+=1; c['api_status'][st]+=1
            if st in(401,429,403,404,500,502,503): c['api_err'][str(st)+'|'+d['ClientRequestMethod']+' '+normapi(p)]+=1
            c['api_path'][d['ClientRequestMethod']+' '+normapi(p)]+=1
            c['api_ua_class'][k]+=1
            if st==429: c['api429_ua'][re.sub(r'/[\d.]+.*','',ua)[:30]]+=1
            if st==401: c['api401_ua'][re.sub(r'/[\d.]+.*','',ua)[:30]]+=1
            c['api_cache'][d['CacheCacheStatus']]+=1
        if h=='cloud.digitalocean.com':
            c['cloud_path'][norm(p)[:60]+'|'+str(st)]+=1
        if d['SecurityAction'] in('block','challenge'):
            c['sec'][h+'|'+d['SecurityAction']+'|'+(d['WAFRuleMessage'] or d['SecurityRuleDescription'])[:45]]+=1
        c['sec_action'][d['SecurityAction']]+=1
        if d['WAFAttackScore'] is not None and d['WAFAttackScore']<20: c['attack_lowscore_host'][h]+=1
        if h in('www.digitalocean.com','docs.digitalocean.com') and d['ClientRequestMethod']=='GET':
            sp=SPECIAL.search(p)
            if sp: c['special_path'][k+'|'+sp.group(0).lower()[:30]+'|'+str(st)]+=1
            if d['EdgeResponseContentType'].startswith('text/html') or sp:
                if d['EdgeResponseContentType'].startswith('text/html'):
                    kind='crawler' if k=='crawler' else ('ai_client' if k=='ai_client' else ('human' if k=='browser' else 'other'))
                    c['pv_kind'][h.split('.')[0]+'|'+kind]+=1
                    c['pv_cache'][kind+'|'+d['CacheCacheStatus']]+=1
                    c['pv_bytes'][kind]+=d['EdgeResponseBytes']
                    c['pv_origin_ms'][kind]+=d['OriginResponseDurationMs']; c['pv_n'][kind]+=1
                    sec=('/'+p.strip('/').split('/')[0]) if p!='/' else '/'
                    if h.startswith('docs'): sec='docs'+sec
                    if k=='crawler':
                        c['pv_crawler_op'][info[0]+'|'+info[1]+'|'+info[2]]+=1
                        c['pv_crawler_sec'][sec]+=1
                        c['pv_crawler_path'][norm(p)[:70]]+=1
                        c['bot_tags'][str(d['BotTags'])[:60]]+=1
                        c['bot_score_crawler'][d['BotScore']//20 if d['BotScore'] else -1]+=1
                        c['bot_ids'][str(d['BotDetectionIDs'])[:40]]+=1
                    elif k=='browser':
                        c['pv_human_sec'][sec]+=1
                        c['pv_human_path'][norm(p)[:70]]+=1
                    if ref:
                        rh=urlparse(ref).netloc.lower().replace('www.','') if '://' in ref else ref[:40]
                        c['ref_host|'+kind][rh]+=1
                        if AIREF.search(rh): c['ai_ref|'+kind][rh]+=1
                        if kind=='human': c['ref_sec'][sec+'|'+('search' if re.search(r'google|bing|duckduckgo|baidu|yandex|ecosia|brave',rh) else ('ai' if AIREF.search(rh) else ('internal' if 'digitalocean' in rh else 'other')))]+=1
                    uri=d['ClientRequestURI']
                    if 'utm_' in uri or 'ref=' in uri:
                        q=parse_qs(urlparse(uri).query)
                        c['utm_source'][(q.get('utm_source') or q.get('ref') or ['?'])[0][:30]+'|'+kind]+=1
            c['tls_ja3_crawler'][info[0] if k=='crawler' else 'x']+=0
    res={'file':fn,'n':n,'keys':keys,'c':{k:{str(a):b for a,b in v.items()} for k,v in c.items()}}
    json.dump(res,open(os.path.join(OUT,fn.replace('.gz','')+'.json'),'w'))
    return fn,n
if __name__=='__main__':
    fs=sorted(f for f in os.listdir(IN) if f.endswith('.log.gz'))
    fs.append('20261110T143829Z_20261110T143930Z_bb2c8e23')
    with Pool(int(sys.argv[1])) as p:
        for fn,n in p.imap_unordered(run,fs): print(fn,n,flush=True)
