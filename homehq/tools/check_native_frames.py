#!/usr/bin/env python3
"""Turn unchanged native framebuffer captures into review sheets and check keys."""
from pathlib import Path
import json
import argparse
from PIL import Image, ImageDraw

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('captures',type=Path)
p=parser.parse_args().captures
states=json.loads((p/'states.json').read_text())
runtime=json.loads((p/'runtime-check.json').read_text())
assert runtime['button_centres']==[56,147,253]
assert runtime['footer_top']==214
assert runtime['steady_redraws']==100 and runtime['icon_cache']<=16
images={}
active=inactive=0
paper=(242,238,230)
for state in states:
    name=state['frame']
    img=Image.frombytes('RGBA',(320,240),(p/(name+'.rgba')).read_bytes()).convert('RGB')
    images[name]=img
    img.save(p/(name+'.png'))
    for cx,label in zip(runtime['button_centres'],state['state']['keys']):
        pixels=list(img.crop((cx-12,218,cx+13,238)).getdata())
        painted=sum(1 for v in pixels if max(abs(v[i]-paper[i]) for i in range(3))>20)
        if label:
            assert painted>12, (name,'active physical key has no visible icon')
            active+=1
        else:
            assert painted==0, (name,'inactive key has a misleading icon')
            inactive+=1
def glyph(name,cx):
    return images[name].crop((cx-9,219,cx+10,236)).tobytes()
assert glyph('today',56)!=glyph('event-detail',56), 'previous and back must differ'
assert glyph('today',253)!=glyph('chore-detail',253), 'next and routine clock must differ'
assert len({glyph(n,147) for n in ('today','shopping','shopping-after-action','photos','photos-paused')})==5, 'detail/check/undo/pause/play must be distinct'
for person in ('alex','jordan','maya','otto'):
    state=next(s for s in states if s['frame']=='family-'+person)['state']
    assert state['page']=='chores' and state['focus']==person
groups={
    'pages':['today','calendar','chores','shopping','photos','home','agents'],
    'details':['event-detail','chore-detail','chore-after-action','routine-picker','anyone-chores','who-picker','shopping-after-action','photos-paused','light-detail','lock-detail','lock-confirm','garage-detail','garage-confirm','agent-detail','offline-notice'],
    'family':['family-alex','family-jordan','family-maya','family-otto'],
    'login':['login-form','login-email','login-email-symbols','login-password','login-password-uppercase','login-password-symbols','login-ready','login-progress','login-error','login-opening-home','viewer-chores','account','logout','logout-pending'],
}
for group,names in groups.items():
    cols=4;rows=(len(names)+cols-1)//cols
    canvas=Image.new('RGB',(cols*340,rows*276),(220,216,208));draw=ImageDraw.Draw(canvas)
    for i,name in enumerate(names):
        x=(i%cols)*340;y=(i//cols)*276
        label={'family-alex':'Wes','family-jordan':'Claudia','family-maya':'Buzzsaw','family-otto':'Skidmark'}.get(name,name)
        draw.text((x+10,y+8),label,fill=(45,43,39))
        canvas.paste(images[name],(x+10,y+28))
    canvas.save(p/(group+'-contact.png'))
result={'frames':len(states),'active_key_slots':active,'inactive_key_slots':inactive,
        'context_glyphs':'five distinct B actions, distinct prev/back and next/time',
        'member_focus':'four preferences, five household rows retained',
        'steady_redraws':100,'retained_icon_shapes':runtime['icon_cache'],'renderer':'compiled canonical MicroPython/picovector; no hardware'}
(p/'visual-check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
for group in groups:print(p/(group+'-contact.png'))
