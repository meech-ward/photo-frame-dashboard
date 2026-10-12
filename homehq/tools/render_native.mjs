import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const countdownOnly=process.argv.includes('--countdown-only');
const [app,out,runtime=path.join(repo,'playground/public/runtime/micropython.mjs'),fonts=path.join(os.homedir(),'.cache/badge-playground/tufty2350/romfs/fonts')]=process.argv.slice(2).filter(arg=>arg!=='--countdown-only');
if(!app||!out)throw new Error('Usage: node render_native.mjs APP_MPY_DIR OUTPUT_DIR [RUNTIME_MJS] [ROM_FONTS_DIR] [--countdown-only]');
process.argv[1] = 'homehq-polish-render';
const {loadMicroPython}=await import(pathToFileURL(path.resolve(runtime)).href);
const logs=[];
const mp=await loadMicroPython({stdout:x=>logs.push(x),stderr:x=>logs.push(x)});
function mkdir(p){let c='';for(const bit of p.split('/').filter(Boolean)){c+='/'+bit;try{mp.FS.mkdir(c)}catch{}}}
function stage(s,d){mkdir(d);for(const e of fs.readdirSync(s,{withFileTypes:true})){if(e.isDirectory())stage(path.join(s,e.name),d+'/'+e.name);else mp.FS.writeFile(d+'/'+e.name,fs.readFileSync(path.join(s,e.name)));}}
stage(app,'/system/apps/homehq');mkdir('/state');mkdir('/rom/fonts');mkdir('/captures');
for(const n of ['smart.ppf','sins.ppf','badgewaremax.ppf'])mp.FS.writeFile('/rom/fonts/'+n,fs.readFileSync(path.join(fonts,n)));
fs.mkdirSync(out,{recursive:true});
const frames=[];
const python=`
import builtins,sys,os,json,picovector as pv
for name in dir(pv):
 if not name.startswith('__'): setattr(builtins,name,getattr(pv,name))
buf=bytearray(320*240*4)
builtins.screen=image(320,240,buf)
pressed=set()
class Badge:
 default_clear=None
 def mode(self,mode): pass
 def pressed(self,button=None): return button in pressed
 def held(self,*args): return False
class Display:
 def update(self): pass
builtins.badge=Badge()
builtins.display=Display()
builtins.HIRES=1
builtins.VSYNC=2
for key in ('A','B','C','UP','DOWN'): setattr(builtins,'BUTTON_'+key,key)
builtins.run=lambda update:update()
root='/system/apps/homehq'
sys.path.insert(0,root)
os.chdir(root)
product=__import__(root)
from model import HomeHQ,PAGES
import demo
def fresh(page,member=None):
 global app
 app=HomeHQ(demo.snapshot(),member)
 app.status={'state':'demo','pending':0}
 app.page=PAGES.index(page)
 app._align()
def select(target):
 for _ in range(64):
  if app.selected() and app.selected().get('id')==target: return
  app.press('DOWN')
 raise AssertionError('fixture row not found')
def capture(name):
 product._view.draw(app)
 with open('/captures/'+name+'.rgba','wb') as f: f.write(buf)
 print(json.dumps({'frame':name,'state':app.debug()}))
# Compare the actual countdown call against an unrestricted same-font line.
# Native font em bounds can clip digits even when their text fits horizontally;
# intercepting the call keeps the check independent of the layout's constants.
original_text=product._view.text
for minutes in (0,9,75,99,100,999,1000,9999,10080):
 fresh('today')
 app.epoch=None
 app.minute=17*60+15
 app.date_label='MON · OCT 12'
 app.data['events']=[{'id':'countdown','day':0,'start':app.minute+minutes,'title':"Dinner at Nonna's",'people':['alex'],'travel':20}]
 calls={}
 def record(value,*args,**kwargs):
  if str(value)==str(minutes): calls['number']=(str(value),args,kwargs)
  if value=='MIN': calls['unit']=(str(value),args,kwargs)
  return original_text(value,*args,**kwargs)
 product._view.text=record
 product._view.draw(app)
 with open('/captures/countdown-'+str(minutes)+'.rgba','wb') as f: f.write(buf)
 product._view.text=original_text
 assert 'number' in calls and 'unit' in calls
 for label in ('number','unit','control'):
  screen.pen=color.rgb(0,0,0)
  screen.clear()
  value,args,kwargs=calls['number' if label=='control' else label]
  x,y,width,height,size=args[:5]
  align=kwargs.get('align',args[6] if len(args)>6 else None)
  if label=='control':
   # Preserve the right edge and baseline, but remove both clipping limits.
   x,width,height=0,x+width,100
  original_text(value,x,y,width,height,size,color.rgb(255,255,255),align)
  with open('/captures/countdown-'+str(minutes)+'-'+label+'.rgba','wb') as f: f.write(buf)
 print(json.dumps({'countdown':minutes,'number_box':list(calls['number'][1][:5]),'unit_box':list(calls['unit'][1][:5])}))
for page in PAGES:
 fresh(page)
 capture(page)
fresh('today');app.press('B');capture('event-detail')
fresh('chores');select('maya');app.press('B');capture('chore-detail')
app.press('B');capture('chore-after-action')
app.press('C');capture('routine-picker')
fresh('chores');select('any');app.press('B');capture('anyone-chores')
app.press('B');capture('who-picker')
fresh('shopping');app.press('B');capture('shopping-after-action')
fresh('photos');app.press('B');capture('photos-paused')
fresh('home');app.press('B');capture('light-detail')
fresh('home')
for row in app.rows('devices'):
 if row.get('type')=='lock': lock_id=row['id']
 if row.get('type')=='garage': garage_id=row['id']
select(lock_id);app.press('B');capture('lock-detail')
app.press('B');capture('lock-confirm')
fresh('home');select(garage_id);app.press('B');capture('garage-detail')
app.press('B');capture('garage-confirm')
fresh('agents');select('codex');app.press('B');capture('agent-detail')
fresh('shopping');app.status={'state':'offline','pending':2};app.notice='Saved on badge';capture('offline-notice')
fresh('today');app.status={'state':'live','pending':0};capture('today-live')
for member in demo.snapshot()['people']:
 fresh('chores',member['id'])
 assert app.selected()['id']==member['id']
 assert len(app.current_rows())==5
 capture('family-'+member['id'])
product.on_exit()
# A config-only badge must open the compiled login entry without exposing a
# previous household or making a network call before its first useful frame.
with open('/state/homehq-config.json','w') as f:
 json.dump({'url':'https://virtual.supabase.co','publishable_key':'sb_publishable_virtual'},f)
sys.modules.pop(root)
product=__import__(root)
assert product._login.active()
assert not product._app.rows('people')
form=product._login
def capture_login(name):
 product._login_view.draw(form)
 with open('/captures/'+name+'.rgba','wb') as f: f.write(buf)
 print(json.dumps({'frame':name,'state':{'page':'login','detail':form.editing,'focus':form.focus,'keys':form.softkeys(),'login':form.debug()}}))
capture_login('login-form')
pressed.add('B');product.update();pressed.clear()
assert form.editing=='email'
class QueuedLogin:
 def __init__(self): self.count=0
 def start_login(self,email,password):
  self.count+=1
  return True
auth=QueuedLogin()
def choose_key(token):
 model=form.keyboard
 at=model.find(token)
 assert at is not None
 model.move_row(at[0]-model.row)
 model.move_column(at[1]-model.column)
 form.press('B',auth)
capture_login('login-email')
choose_key('NUM')
form.keyboard.text='person+badge@example.invalid'
capture_login('login-email-symbols')
choose_key('DONE')
form.press('B',auth)
form.keyboard.text='Masked+Case@'+chr(96)+'123'
# Prove the actual draw never sends password characters to the native text
# rasterizer. Mask pixels are circles; no last-character reveal is used.
drawn=[]
original_text=product._view.text
def watch(value,*args,**kwargs):
 drawn.append(str(value))
 return original_text(value,*args,**kwargs)
product._view.text=watch
capture_login('login-password')
assert not any('Masked+Case' in value for value in drawn)
choose_key('SHIFT')
capture_login('login-password-uppercase')
choose_key('NUM');choose_key('SYM')
capture_login('login-password-symbols')
assert form.keyboard.find(chr(96)) is not None
choose_key('DONE')
capture_login('login-ready')
assert not any('Masked+Case' in value for value in drawn)
product._view.text=original_text
form.press('B',auth)
assert auth.count==1 and not form.email and not form.password
form.press('B',auth)
assert auth.count==1
capture_login('login-progress')
form.synchronize({'auth_state':'error','auth_error':'Check email and password.'},{})
capture_login('login-error')
form.synchronize({'auth_state':'signed_in'}, {})
capture_login('login-opening-home')
live=demo.snapshot()
live['home']['id']='virtual-home'
live['viewer']={'user_id':'virtual-user','person_id':'maya'}
form.synchronize({'auth_state':'signed_in'},live)
assert not form.active()
app=HomeHQ(live,'alex')
app.status={'state':'live','auth_state':'signed_in','pending':0}
app.page=PAGES.index('chores');app._align()
assert app.selected()['id']=='maya'
capture('viewer-chores')
app.focus['chores']='any';app.press('B')
command=app.press('B')
assert command['done_by']=='maya' and app.detail=='chores'
app=HomeHQ(live)
app.status={'state':'live','auth_state':'signed_in','pending':0}
app.page=PAGES.index('home');app.focus['home']='__account';app.press('B')
capture('account')
app.press('B');capture('logout')
app.status['pending']=2;capture('logout-pending')
assert app.softkeys()==('BACK','','') and app.press('B') is None
product._app=app
product._view._photo=image.load(root+'/assets/photo-coast.png')
product._view._photo_path='/state/homehq-photo-0.png'
product._replace_snapshot({})
assert product._app.detail is None and product._app.page==0
assert product._view._photo is None and product._view._photo_path is None
product._replace_snapshot(live)
assert product._app.detail is None and product._app.viewer_person_id=='maya'
retained_icons=len(product._view.icon_shapes)
for _ in range(100): product._view.draw(app)
assert len(product._view.icon_shapes)==retained_icons
print(json.dumps({'icon_cache':retained_icons,'steady_redraws':100,'button_centres':product._view.chrome.softkey_x,'footer_top':product._view.chrome.bar_y}))
product.on_exit()
`;
await mp.runPythonAsync(countdownOnly?python.slice(0,python.indexOf('for page in PAGES:')):python);
let cache;
const countdowns=[];
for(const line of logs){if(line.startsWith('{')){const row=JSON.parse(line);if(row.frame)frames.push(row);else if(row.countdown!==undefined)countdowns.push(row);else cache=row;}else if(line.includes('Traceback'))throw new Error(line);}
if(frames.length!==(countdownOnly?0:41))throw new Error('unexpected captured state count: '+frames.length);
function bounds(bytes){let left=320,top=240,right=-1,bottom=-1,pixels=0;for(let y=0;y<240;y++)for(let x=0;x<320;x++){if(bytes[(y*320+x)*4]>0){left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x);bottom=Math.max(bottom,y);pixels++;}}return {left,top,right,bottom,pixels};}
for(const row of countdowns){
 const name='countdown-'+row.countdown;
 const captures={};
 for(const suffix of ['', '-number','-unit','-control']){const bytes=mp.FS.readFile('/captures/'+name+suffix+'.rgba');fs.writeFileSync(path.join(out,name+suffix+'.rgba'),bytes);if(suffix)captures[suffix.slice(1)]=bytes;}
 row.number_pixels=bounds(captures.number);
 row.control_pixels=bounds(captures.control);
 row.unit_pixels=bounds(captures.unit);
 row.unclipped=Buffer.from(captures.number).equals(Buffer.from(captures.control));
 row.unit_gap=row.unit_pixels.top-row.number_pixels.bottom-1;
}
fs.writeFileSync(path.join(out,'countdown-check.json'),JSON.stringify(countdowns,null,2)+'\n');
for(const item of frames){const bytes=mp.FS.readFile('/captures/'+item.frame+'.rgba');if(bytes.length!==307200)throw new Error('bad frame length');fs.writeFileSync(path.join(out,item.frame+'.rgba'),bytes);item.sha256=crypto.createHash('sha256').update(bytes).digest('hex');}
if(!countdownOnly){fs.writeFileSync(path.join(out,'states.json'),JSON.stringify(frames,null,2));fs.writeFileSync(path.join(out,'runtime-check.json'),JSON.stringify(cache,null,2));}
console.log(JSON.stringify({frames:frames.length,countdowns,renderer:'canonical MicroPython + picovector',...cache,output:out}));
if(countdowns.length!==9||countdowns.some(row=>!row.unclipped||row.unit_gap<1))throw new Error('countdown glyph clipped, truncated or colliding with MIN; inspect countdown-check.json');
