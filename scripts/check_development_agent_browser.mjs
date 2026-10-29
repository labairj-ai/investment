// Synthetic browser QA only. No production service, ledger or owner action is used.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {spawn,execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const artifacts=path.resolve(process.argv[2]||await fs.mkdtemp(path.join(os.tmpdir(),'investment-ecc-browser-')));
if(artifacts.startsWith(path.resolve(root)+path.sep))throw Error('Browser artifacts must remain outside source');
await fs.mkdir(artifacts,{recursive:true});
const sourceHead=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
if(execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim())throw Error('Commit the exact source before browser acceptance');
const assets=path.join(root,'dev_agent/control_center_assets');
const legacy=execFileSync(process.env.PYTHON||'python3',['-c','from dev_agent.dashboard import HTML; print(HTML)'],{cwd:root,encoding:'utf8'});
const head='a'.repeat(40),now=Date.now()/1000;let mode='normal';const requests=[];const errors=[];
const judgment=(status='UNAVAILABLE')=>({status,reason_code:'SYNTHETIC_FIXTURE',reason_summary:'Synthetic safety evidence for browser QA. No operating acceptance.',observed_at:now,expires_at:mode==='stale'?now-2:now+300,source:'synthetic-browser-fixture',policy_version:'fixture',repository:'labairj-ai/investment',head_sha:head,receipt_id:null,verifier_status:'FIXTURE_ONLY'});
const candidate={id:'fixture-candidate',title:'<img src=x onerror=alert(1)> '+ 'Long candidate title '.repeat(12),created_at:now-100,state:'PLANNED',risk:'L5',category:'DOCUMENT',source:'test',value_score:null,score_version:null,blocker:'Independent evidence is unavailable. Inspect financial, execution and governance scope.',files:['docs/'+'long-path-'.repeat(30)+'.md'],evidence:judgment()};
const event={seq:7,event_id:'=untrusted-event',candidate:candidate.id,kind:'SCHEDULE_FAILURE',created_at:now-80,actor:'=HYPERLINK("invalid")',actor_identity_source:'UNVERIFIED_LEDGER_CLAIM',head_sha:head,status:judgment(),details:{problem:'<script>window.injected=true</script>'}};
function envelope(data){return {version:'investment-engineering-1',repository:'labairj-ai/investment',head_sha:head,read_at:now,fixture_only:true,...data};}
const certificate=()=>envelope({technical:judgment(),technical_details:{harness_hash:'b'.repeat(64)},supervised:{completed:2,required:3,observation_days:2,required_days:7,evidence:judgment('NOT READY')},scout:{successful_runs:2,required_runs:3,evidence:judgment('NOT READY')},autonomy:{configuration:{source:'committed-configuration-not-host-observation',values:{autonomy_stage:'SHADOW',autonomous_implementation:false}},eligible:false,enabled:false,blockers:['Three genuine timer slots and the supervised observation period remain incomplete.']}});
function fixture(endpoint,url){
 if(endpoint==='overview')return envelope({readiness:judgment('NOT READY'),blockers:[{reason:'Independent Oracle certificate unavailable.',destination:'certification'},{reason:'Two of three genuine Scout runs.',destination:'certification'}],metrics:{candidate_backlog:mode==='empty'?0:1,owner_decisions:null},priority_queue:mode==='empty'?[]:[candidate],autonomy_configuration:{values:{autonomy_stage:'SHADOW'}},scheduler:judgment()});
 if(endpoint==='candidates')return envelope({items:mode==='empty'||url.searchParams.get('search')==='no-matches'?[]:[candidate],total:mode==='empty'?0:1,snapshot_seq:7,next_cursor:null});
 if(endpoint==='candidates/'+candidate.id)return envelope({id:candidate.id,title:candidate.title,proposal:{problem:'Literal <script>window.injected=true</script> text',files:candidate.files},latest:{PLAN:{context:{risk:'L5',head}}},timeline:[event],timeline_complete:false,actions:{build:false,approve:false}});
 if(endpoint==='certification')return certificate();
 if(endpoint==='prs')return envelope({items:mode==='empty'?[]:[{number:31,candidate:candidate.id,recorded_head:head,evidence:judgment()}],next_cursor:null});
 if(endpoint==='prs/31')return envelope({number:31,base_branch:'main',base_sha:'b'.repeat(40),head_branch:'fixture/'+ 'long-'.repeat(30),risk:'L5',file_count:1,files_complete:true,files:candidate.files,url:'https://github.com/labairj-ai/investment/pull/31',diff_url:'https://github.com/labairj-ai/investment/pull/31/files',ci:judgment('PASS'),protection:judgment(),owner_evidence:judgment(),owner_disposition:'MISSING',oracle:judgment(),deployment:judgment(),actions:{go:false,no_go:false,reason:'Existing isolated owner-connector UI handoff has not been accepted. Current Oracle evidence is unavailable.'}});
 if(endpoint==='validations/'+candidate.id)return envelope({candidate:candidate.id,manifest_version:'development-validation-3',all_required_pass:false,items:['focused_tests','full_suite','release_baseline','cc_contract','agent_contract','todo_consistency','development_governance'].map(name=>({name,evidence:judgment(),inventory:null})),repository_ci_manifest:{version:'repository-validation-1',authority:'diagnostics-only',gates:['todo_consistency','agent_contract','development_governance','focused_agent_tests','full_suite','release_baseline','cc_contract','summary_integrity']}});
 if(endpoint==='audit')return envelope({items:mode==='empty'?[]:[event],next_cursor:null,snapshot_seq:7});
 throw Error('Unknown fixture endpoint '+endpoint);
}
const server=http.createServer(async(req,res)=>{try{requests.push({method:req.method,url:req.url});if(req.method!=='GET'){res.writeHead(405);res.end();return;}const url=new URL(req.url,'http://fixture.invalid');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'");
 const fixed={'/engineering/projects/investment':['index.html','text/html'],'/engineering/assets/control-center.js':['control-center.js','text/javascript'],'/engineering/assets/control-center.css':['control-center.css','text/css']};
 if(fixed[url.pathname]){const [name,type]=fixed[url.pathname];res.setHeader('Content-Type',type);res.end(await fs.readFile(path.join(assets,name)));return;}
 if(url.pathname==='/development-agent'){res.setHeader('Content-Type','text/html');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'");res.end(legacy);return;}
 if(url.pathname==='/api/development-agent'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({candidates:[{...candidate,created:now,problem:'Fixture only',outcome:'Fixture only',events:[],latest:{PLAN:{context:{risk:'L5'}},ITERATION:{review:{disposition:'REQUEST_CHANGES'}}}}],readiness:{owner:{status:'NOT READY',reason:'Fixture safety stop'}},certification:'UNAVAILABLE'}));return;}
 const prefix='/api/engineering/v1/projects/investment/';if(!url.pathname.startsWith(prefix)){res.writeHead(404);res.end();return;}
 if(mode==='denied'){res.writeHead(403);res.end('{}');return;}
 if(mode==='latency'&&url.pathname===prefix+'overview')await new Promise(resolve=>setTimeout(resolve,300));
 if(url.searchParams.get('format')==='csv'){res.setHeader('Content-Type','text/csv');res.end('repository,seq,event_id\nlabairj-ai/investment,7,\'=untrusted-event\n');return;}
 res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixture(url.pathname.slice(prefix.length),url)));
 }catch(error){errors.push(String(error));res.writeHead(500);res.end('{}');}});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
const profile=await fs.mkdtemp(path.join(os.tmpdir(),'investment-ecc-chrome-'));
let browser,socket;
try{
 const choices=[process.env.DEV_AGENT_BROWSER_EXECUTABLE,'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/usr/bin/chromium','/usr/bin/google-chrome'].filter(Boolean);let executable;
 for(const p of choices){try{await fs.access(p);executable=p;break;}catch{}}
 if(!executable)throw Error('Set DEV_AGENT_BROWSER_EXECUTABLE to an isolated Chromium executable');
 browser=spawn(executable,['--headless=new','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','about:blank'],{stdio:['ignore','ignore','pipe']});
 let log='';browser.stderr.on('data',chunk=>{log+=chunk;});
 const deadline=Date.now()+15000;let ws;
 while(Date.now()<deadline){const found=log.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/[^\s]+)/);if(found){ws=found[1];break;}if(browser.exitCode!==null)throw Error('Isolated browser exited: '+log.slice(-1500));await new Promise(r=>setTimeout(r,50));}
 if(!ws)throw Error('Isolated browser startup unavailable: '+log.slice(-1500));
 const port=new URL(ws).port;const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();const target=tabs.find(t=>t.type==='page'&&t.url==='about:blank');if(!target)throw Error('Isolated blank target missing');
 socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 let counter=0;const waiting=new Map();socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);waiting.delete(m.id);if(m.error)p.reject(Error(JSON.stringify(m.error)));else p.resolve(m.result);}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++counter,timer=setTimeout(()=>{waiting.delete(id);reject(Error('CDP timeout '+method));},15000);waiting.set(id,{resolve:v=>{clearTimeout(timer);resolve(v);},reject});socket.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
 const until=async expression=>{for(let i=0;i<150;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Browser condition unavailable: '+expression);};
 const assert=(value,reason)=>{if(!value)throw Error(reason);};
 const contrastCheck=()=>{
  const parse=v=>{const n=v.match(/[\d.]+/g)?.map(Number)||[0,0,0];return {rgb:n.slice(0,3),alpha:n[3]??1};};
  const background=e=>{if(!e)return [255,255,255];const c=parse(getComputedStyle(e).backgroundColor);if(c.alpha===1)return c.rgb;const under=background(e.parentElement);return c.rgb.map((v,i)=>v*c.alpha+under[i]*(1-c.alpha));};
  const luminance=c=>c.map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[0.2126,0.7152,0.0722][i],0);
  let minimum=100,checked=0;const failures=[];
  for(const e of document.querySelectorAll('body *')){if(!e.getClientRects().length||!Array.from(e.childNodes).some(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim()))continue;const s=getComputedStyle(e);if(s.visibility==='hidden')continue;const a=luminance(parse(s.color).rgb),b=luminance(background(e)),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05),size=parseFloat(s.fontSize),threshold=size>=24||size>=18.66&&parseInt(s.fontWeight)>=700?3:4.5;minimum=Math.min(minimum,ratio);checked++;if(ratio+0.01<threshold)failures.push({text:e.textContent.slice(0,60),ratio,threshold});}
  return {checked,minimum_ratio:minimum,failures};
 };
 await call('Runtime.enable');await call('Page.enable');
 await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
 const results=[];
 for(const width of [320,360,390,430,768,1280,1440]){
  mode='normal';await call('Emulation.setDeviceMetricsOverride',{width,height:960,deviceScaleFactor:1,mobile:width<768});await call('Page.navigate',{url:origin+'/engineering/projects/investment'});
  await until('document.getElementById("content")?.getAttribute("aria-busy")==="false"');
  assert(await evaluate('document.querySelector(".hero").textContent.includes("NOT READY")'),'backend readiness not rendered');
  assert(await evaluate('document.querySelector(".hero").textContent.includes("Independent Oracle certificate unavailable")'),'ranked blocker missing');
  assert(await evaluate('document.querySelectorAll("article img, article script").length===0 && !window.injected'),'unsafe HTML rendered');
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'overview overflow '+width);
  const contrast=await evaluate(`(${contrastCheck.toString()})()`);assert(contrast.failures.length===0,'text contrast below AA: '+JSON.stringify(contrast.failures));
  const screenshot=await call('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(artifacts,`overview-${width}.png`),Buffer.from(screenshot.data,'base64'));
  await evaluate('document.querySelector(".candidate button").focus();document.querySelector(".candidate button").click()');
  await until('document.getElementById("detail").open && document.getElementById("detail-content").textContent.includes("Literal <script>")');
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'detail overflow '+width);
  assert(await evaluate('document.getElementById("detail").contains(document.activeElement)'),'focus outside modal');
  for(let i=0;i<10;i++){await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});assert(await evaluate('document.getElementById("detail").contains(document.activeElement)'),'focus escaped modal');}
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await until('!document.getElementById("detail").open');assert(await evaluate('document.activeElement.textContent.includes("Inspect")'),'focus not restored');
  await evaluate('navigate("candidates")');await until('document.getElementById("candidate-filters") && document.querySelector("#candidate-results article")');
  await evaluate('document.querySelector("#candidate-filters input").value="no-matches";document.getElementById("candidate-filters").requestSubmit()');await until('document.getElementById("candidate-results").textContent.includes("No matching")');
  await evaluate('navigate("prs")');await until('document.querySelector("#content article button")');await evaluate('document.querySelector("#content article button").click()');
  await until('document.getElementById("detail-content").textContent.includes("Go · unavailable")');
  assert(await evaluate('[...document.querySelectorAll("#detail-content button")].filter(b=>b.textContent.includes("Go")).every(b=>b.disabled)'),'owner action enabled');
  assert(await evaluate('document.getElementById("owner-disabled-reason").textContent.includes("unavailable")'),'owner disabled reason missing');
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'PR overflow '+width);await evaluate('closeDetail()');
  await evaluate('navigate("validation")');await until('document.querySelector("#content article button")');await evaluate('document.querySelector("#content article button").click()');await until('document.getElementById("detail-content").textContent.includes("summary_integrity")');
  assert(await evaluate('document.querySelectorAll("#detail-content .state-card").length===7'),'required trusted gate omitted');await evaluate('closeDetail()');
  await evaluate('navigate("certification")');await until('document.getElementById("content").textContent.includes("Scout: 2 / 3")');assert(await evaluate('document.getElementById("content").textContent.includes("2 / 7 days")'),'calendar qualification missing');
  await evaluate('navigate("audit")');await until('document.getElementById("audit-results")?.textContent.includes("UNVERIFIED_LEDGER_CLAIM")');assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'audit overflow '+width);
  const tap=await evaluate('[...document.querySelectorAll("button,input,select")].filter(e=>e.getClientRects().length&&!e.closest("dialog:not([open])")).map(e=>e.getBoundingClientRect().height).every(h=>h>=44)');assert(tap,'tap target smaller than 44px');
  if(width<768){await evaluate('document.getElementById("more").click()');assert(await evaluate('document.getElementById("more-dialog").open'),'mobile More unavailable');await evaluate('document.querySelector("#more-dialog [data-view=certification]").click()');await until('document.getElementById("content").textContent.includes("Scout: 2 / 3")');}
  // The retained legacy interface still renders its own backend gate.
  await call('Page.navigate',{url:origin+'/development-agent'});await until('Boolean(document.getElementById("load"))');await evaluate('document.getElementById("load").click()');await until('document.querySelector("#queue article")');assert(await evaluate('document.getElementById("readiness").textContent.includes("Fixture safety stop")'),'legacy readiness changed');assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'legacy overflow '+width);
  results.push({width,status:'PASS',readiness:'backend fixture matched',overflow:false,unsafe_html:false,modal_focus:'PASS',tap_targets:'>=44px',text_contrast:contrast,legacy:'PASS'});
 }
 mode='normal';await call('Page.navigate',{url:origin+'/engineering/projects/investment#overview/candidates/'+candidate.id});await until('document.getElementById("detail")?.open');assert(await evaluate('document.getElementById("detail-content").textContent.includes("Read-only")'),'deep link unavailable');await evaluate('closeDetail()');
 mode='latency';await evaluate('navigate("overview");navigate("audit")');await until('document.getElementById("audit-results")?.textContent.includes("UNVERIFIED_LEDGER_CLAIM")');await new Promise(r=>setTimeout(r,400));assert(await evaluate('document.getElementById("page-title").textContent==="Audit history"&&!document.querySelector(".hero")'),'older request overwrote active view');
 mode='denied';await evaluate('navigate("overview")');await until('document.getElementById("message").textContent.includes("UNAVAILABLE")');assert(await evaluate('!document.querySelector(".hero")'),'cached readiness retained on access failure');
 mode='empty';await evaluate('navigate("candidates")');await until('document.getElementById("candidate-results")?.textContent.includes("No matching")');
 mode='stale';await evaluate('navigate("overview")');await until('document.getElementById("message").textContent.includes("STALE")');assert(await evaluate('!document.querySelector(".hero")'),'expired readiness retained');
 assert(requests.every(r=>r.method==='GET'),'browser attempted a mutation');assert(errors.length===0,'browser/server errors: '+JSON.stringify(errors));
 const unchanged=sourceHead===execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim()&&!execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim();assert(unchanged,'source changed during browser QA');
 const result={status:'PASS',source_head:sourceHead,source_unchanged:unchanged,fixture_only:true,physical_devices:'NOT_RUN',live_owner_connector:'NOT_ACCEPTED',results,negative_paths:['unauthorized source clears cached readiness','expired observation clears readiness','late response cannot overwrite navigation','no executable untrusted HTML','owner actions disabled','keyboard focus trap/restore','deep-link inspection'],mutations:0,requests:requests.length};await fs.writeFile(path.join(artifacts,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}finally{if(socket)socket.close();if(browser)browser.kill();await new Promise(resolve=>server.close(resolve));await fs.rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});}
