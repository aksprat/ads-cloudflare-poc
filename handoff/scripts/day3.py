import json,sys,re,gzip,os,hashlib,collections as C
from multiprocessing import Pool
HERE=os.path.dirname(os.path.abspath(__file__))
IN=os.environ.get('LOGS_DIR',os.path.join(HERE,'..','..'))
OUT=os.path.join(HERE,'..','results','out3')
os.makedirs(OUT,exist_ok=True)
H=lambda s:hashlib.md5(s.encode()).hexdigest()[:8]
UAF=lambda ua:re.sub(r'[/ ].*','',ua)[:24] or 'empty'
norm=lambda p:re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27}|\b\d{3,}\b|[0-9a-f]{24,}','{id}',p)
BOT=re.compile(r'bot|spider|crawl|uptime|monitor|blackbox|pingdom',re.I)
def run(fn):
    c=C.defaultdict(C.Counter); sets=C.defaultdict(set); n=0; hdr=0; hdrkeys=C.Counter()
    op=gzip.open if fn.endswith('.gz') else open
    for line in op(os.path.join(IN,fn),'rt',errors='replace'):
        d=json.loads(line); n+=1
        h=d['ClientRequestHost'].split(':')[0]; ua=d['ClientRequestUserAgent']; st=d['EdgeResponseStatus']; p=d['ClientRequestPath']
        if d['RequestHeaders']:
            hdr+=1
            for k in d['RequestHeaders']: hdrkeys[k]+=1
        if h.startswith('otlp-'):
            c['ttfb_otlp'][d['EdgeColoCode']+'|'+str(min(d['EdgeTimeToFirstByteMs'],2000)//5*5)]+=1
            continue
        f=UAF(ua); ip=H(d['ClientIP'])
        c['ja3_fam'][f+'|'+d['JA3Hash'][:10]]+=1
        if h in('api.digitalocean.com','cloud.digitalocean.com','www.digitalocean.com'):
            c['ttfb_ctl'][h.split('.')[0]+'|'+d['EdgeColoCode']+'|'+str(min(d['EdgeTimeToFirstByteMs'],3000)//10*10)]+=1
        if h=='cloud.digitalocean.com' and ua.startswith('Mozilla') and not BOT.search(ua): sets['cloud_browser_ips'].add(ip)
        if h=='api.digitalocean.com' and re.search(r'godo|doctl|terraform|pulumi',ua,re.I): sets['api_sdk_ips'].add(ip)
        if h=='api.digitalocean.com' and re.search(r'godo|doctl|terraform|pulumi',ua,re.I) and st==200: sets['api_sdk_ok_ips'].add(ip)
        if h=='mcp.digitalocean.com': sets['mcp_ips'].add(ip)
        if h=='mcp.digitalocean.com': sets['mcp_asn_'+str(d['ClientASN'])].add(ip)
        if h in('www.digitalocean.com','docs.digitalocean.com') and d['ClientRequestMethod']=='GET':
            ct=d['EdgeResponseContentType']
            kind='crawler' if BOT.search(ua) else ('browser' if ua.startswith('Mozilla') else 'other')
            sc='2xx' if 200<=st<300 else ('3xx' if 300<=st<400 else ('404' if st==404 else ('4xx' if st<500 else '5xx')))
            if ct.startswith('text/html') or st in(404,301,302,307,308):
                c['pv_status'][h.split('.')[0]+'|'+kind+'|'+sc]+=1
                if st==404: c['p404'][h.split('.')[0]+'|'+kind+'|'+norm(p)[:70]]+=1
                if st in(301,302,307,308): c['p3xx'][h.split('.')[0]+'|'+kind+'|'+norm(p)[:60]]+=1
        if h in('api.digitalocean.com','mcp.digitalocean.com','cloud.digitalocean.com'):
            c['asn_fam'][f+'|'+str(d['ClientASN'])]+=1
    json.dump({'n':n,'hdr':hdr,'hdrkeys':dict(hdrkeys.most_common(20)),'c':{k:dict(v) for k,v in c.items()},'sets':{k:sorted(v) for k,v in sets.items()}},open(os.path.join(OUT,fn.replace('.gz','')+'.json'),'w'))
    return fn,n
if __name__=='__main__':
    fs=sorted(f for f in os.listdir(IN) if f.endswith('.log.gz')); fs.append('20261110T143829Z_20261110T143930Z_bb2c8e23')
    with Pool(int(sys.argv[1])) as p:
        for fn,n in p.imap_unordered(run,fs): print(fn,n,flush=True)
