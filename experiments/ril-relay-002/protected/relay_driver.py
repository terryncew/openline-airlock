#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, platform, secrets, socket, time
from dataclasses import dataclass
from pathlib import Path

EXPERIMENT="RIL-RELAY-002"
MAX_WAIT=1200
LOGIN_PATTERNS=("accounts.google.com","Sign in")
REQUIRED_MARKERS=("Temporary Chat","Extended")
GEMINI_URL="https://gemini.google.com/app"

def sha256_text(s:str)->str:
    return hashlib.sha256(s.encode()).hexdigest()

def write_json(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")

def host_fingerprint()->dict:
    raw={
        "hostname":socket.gethostname(),
        "platform":platform.platform(),
        "machine":platform.machine(),
        "python":platform.python_version(),
    }
    raw["sha256"]=sha256_text(json.dumps(raw,sort_keys=True))
    return raw

def extract_last_json(text:str):
    dec=json.JSONDecoder(); found=[]
    for i,ch in enumerate(text):
        if ch!="{": continue
        try:
            obj,_=dec.raw_decode(text[i:])
            if isinstance(obj,dict): found.append(obj)
        except Exception:
            pass
    return found[-1] if found else None

def attach(cdp_url:str):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("playwright is required: python -m pip install playwright") from e
    pw=sync_playwright().start()
    browser=pw.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        pw.stop()
        raise RuntimeError("CDP browser has no context")
    return pw,browser,browser.contexts[0]

def preflight(cdp_url:str,out:Path)->int:
    pw,browser,ctx=attach(cdp_url)
    rec={
        "schema":"openline.ril-relay-002.egress-preflight.v1",
        "experiment":EXPERIMENT,
        "host":host_fingerprint(),
        "url":GEMINI_URL,
        "authenticated_primary_contact":False,
        "status":"FAIL",
    }
    page=ctx.new_page()
    try:
        started=time.time()
        resp=page.goto(GEMINI_URL,wait_until="domcontentloaded",timeout=60000)
        body=page.locator("body").inner_text(timeout=10000)
        rec.update({
            "elapsed_seconds":round(time.time()-started,3),
            "final_url":page.url,
            "http_status":resp.status if resp else None,
            "body_chars":len(body),
        })
        if page.url and body.strip():
            rec["status"]="PASS"
        else:
            rec["failure"]="EMPTY_DOCUMENT"
    except Exception as e:
        rec["failure"]=f"{type(e).__name__}: {e}"
    finally:
        shot=out/"RIL_RELAY_002_EGRESS_PREFLIGHT.png"
        try: page.screenshot(path=str(shot),full_page=True)
        except Exception: pass
        page.close()
        pw.stop()
    write_json(out/"RIL_RELAY_002_EGRESS_PREFLIGHT.json",rec)
    print(json.dumps(rec,indent=2,sort_keys=True))
    return 0 if rec["status"]=="PASS" else 2

@dataclass
class Receipt:
    prompt_sha256:str
    submitted_utc:str
    completed_utc:str|None
    screenshot:str
    transcript:str
    response:dict|None
    status:str

class GeminiRelay:
    def __init__(self,cdp_url:str,out:Path,preflight_path:Path):
        pre=json.loads(preflight_path.read_text())
        if pre.get("status")!="PASS":
            raise RuntimeError("egress preflight did not PASS")
        current=host_fingerprint()
        if pre.get("host",{}).get("sha256")!=current["sha256"]:
            raise RuntimeError("preflight host fingerprint mismatch")
        self.preflight=pre
        self.pw,self.browser,self.ctx=attach(cdp_url)
        self.out=out; out.mkdir(parents=True,exist_ok=True)
    def close(self): self.pw.stop()
    def _assert_authenticated(self,page):
        body=page.locator("body").inner_text(timeout=10000)
        if any(p in page.url or p in body for p in LOGIN_PATTERNS):
            raise RuntimeError("LOGIN_REQUIRED")
    def _assert_markers(self,page):
        body=page.locator("body").inner_text(timeout=10000)
        missing=[m for m in REQUIRED_MARKERS if m not in body]
        if missing: raise RuntimeError(f"required UI marker(s) missing: {missing}")
    def fresh_temp_chat(self):
        page=self.ctx.new_page()
        page.goto(GEMINI_URL,wait_until="domcontentloaded",timeout=60000)
        self._assert_authenticated(page)
        body=page.locator("body").inner_text(timeout=10000)
        if "Temporary Chat" not in body:
            raise RuntimeError("Temporary Chat control not visible")
        loc=page.get_by_text("Temporary Chat",exact=True)
        if loc.count()==0: loc=page.locator('[aria-label*="Temporary" i]')
        if loc.count()==0: raise RuntimeError("could not locate Temporary Chat control")
        loc.first.click(timeout=10000)
        time.sleep(0.5)
        self._assert_authenticated(page); self._assert_markers(page)
        return page
    def submit(self,page,prompt:str,tag:str,expected_json=None,expected_token=None)->Receipt:
        self._assert_authenticated(page); self._assert_markers(page)
        boxes=page.locator('[contenteditable="true"][role="textbox"], textarea')
        if boxes.count()==0: raise RuntimeError("Gemini input box not found")
        target=boxes.last; target.click(); target.fill(prompt)
        ph=sha256_text(prompt); started=time.time()
        submitted=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
        target.press("Enter")
        last=""
        while time.time()-started<MAX_WAIT:
            self._assert_authenticated(page)
            text=page.locator("main, body").first.inner_text(timeout=10000)
            last=text
            if expected_token is not None and expected_token in text: break
            obj=extract_last_json(text)
            if expected_json is not None and isinstance(obj,dict) and all(obj.get(k)==v for k,v in expected_json.items()): break
            time.sleep(1)
        else:
            shot=self.out/f"{tag}.timeout.png"; page.screenshot(path=str(shot),full_page=True)
            tr=self.out/f"{tag}.transcript.txt"; tr.write_text(last)
            return Receipt(ph,submitted,None,shot.name,tr.name,None,"TIMEOUT")
        shot=self.out/f"{tag}.png"; page.screenshot(path=str(shot),full_page=True)
        tr=self.out/f"{tag}.transcript.txt"; tr.write_text(last)
        return Receipt(ph,submitted,time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),shot.name,tr.name,extract_last_json(last),"RETURNED")

def self_check()->int:
    assert len(sha256_text("abc"))==64
    assert extract_last_json('x {"a":1} y {"trial":2}')=={"trial":2}
    fp=host_fingerprint(); assert len(fp["sha256"])==64
    print(json.dumps({"self_check":"PASS","retry_policy":"FORBIDDEN","credential_input":False},indent=2))
    return 0

def qualify(cdp_url:str,out:Path,preflight_path:Path)->int:
    r=GeminiRelay(cdp_url,out,preflight_path); trials=[]
    try:
        for n in (1,2):
            canary=f"RILRELAY2-{n}-{secrets.token_hex(24)}"
            exposure=r.fresh_temp_chat()
            p1=json.dumps({"instruction":"Reply with exactly one JSON object and no prose.","experiment":EXPERIMENT,"trial":n,"action":"expose","canary":canary,"response_contract":{"experiment":EXPERIMENT,"trial":n,"ack":canary}},sort_keys=True)
            a=r.submit(exposure,p1,f"trial-{n}-expose",expected_json={"experiment":EXPERIMENT,"trial":n})
            if a.status!="RETURNED" or not a.response or a.response.get("ack")!=canary: raise RuntimeError(f"trial {n} exposure failed")
            p2=json.dumps({"instruction":"Reply with exactly one JSON object and no prose.","experiment":EXPERIMENT,"trial":n,"action":"same_chat_recall","response_contract":{"experiment":EXPERIMENT,"trial":n,"recall":"<exact prior canary>"}},sort_keys=True)
            b=r.submit(exposure,p2,f"trial-{n}-same",expected_json={"experiment":EXPERIMENT,"trial":n})
            if b.status!="RETURNED" or not b.response or b.response.get("recall")!=canary: raise RuntimeError(f"trial {n} same-chat recall failed")
            exposure.close()
            blind=r.fresh_temp_chat()
            p3=json.dumps({"instruction":"Reply with exactly one JSON object and no prose. If you do not know the canary from another chat, use UNKNOWN.","experiment":EXPERIMENT,"trial":n,"action":"blind_recall","response_contract":{"experiment":EXPERIMENT,"trial":n,"recall":"UNKNOWN"}},sort_keys=True)
            c=r.submit(blind,p3,f"trial-{n}-blind",expected_json={"experiment":EXPERIMENT,"trial":n})
            blind.close()
            if c.status!="RETURNED" or not c.response or c.response.get("recall")!="UNKNOWN": raise RuntimeError(f"trial {n} blind chat leaked/recalled")
            trials.append({"trial":n,"canary_sha256":sha256_text(canary),"exposure":a.__dict__,"same_chat":b.__dict__,"blind":c.__dict__})
        result={
            "schema":"openline.ril-relay-002.result.v1",
            "experiment":EXPERIMENT,
            "formal_verdict":"PASS_RIL_RELAY_002_PREFLIGHT_BOUND_DETERMINISTIC_RELAY",
            "host":host_fingerprint(),
            "preflight_sha256":hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
            "trials":trials,
            "credentials_supplied":False,
            "primary_retry_used":False
        }
        write_json(out/"RIL_RELAY_002_RESULT.json",result)
        print(json.dumps(result,indent=2))
        return 0
    finally:
        r.close()

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-check")
    p=sub.add_parser("preflight"); p.add_argument("--cdp-url",default="http://127.0.0.1:9222"); p.add_argument("--output",type=Path,required=True)
    q=sub.add_parser("qualify"); q.add_argument("--cdp-url",default="http://127.0.0.1:9222"); q.add_argument("--output",type=Path,required=True); q.add_argument("--preflight",type=Path,required=True)
    a=ap.parse_args()
    if a.cmd=="self-check": return self_check()
    if a.cmd=="preflight": return preflight(a.cdp_url,a.output)
    return qualify(a.cdp_url,a.output,a.preflight)

if __name__=="__main__":
    raise SystemExit(main())
