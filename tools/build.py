#!/usr/bin/env python3
"""Build the standalone Home HQ app, with reproducible pure MicroPython bytecode.

No firmware is built and no device is opened. The source export is an explicit
allowlist: personalized configuration, refresh sessions and state never enter it.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from dependencies import dependency_path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "devices" / "badge"
PIN = "b29530abbd0550c8ab6963024aef36f3cd6cd278"
APP_FILES = ("__init__.py", "model.py", "view.py", "demo.py", "service.py", "cache.py", "transport.py", "auth_client.py", "login.py")
LIBRARIES = {"aiohttp": dependency_path("network/vendor/aiohttp"),
             "realtime": dependency_path("badgelink/badge/realtime")}
CA = dependency_path("badgelink/badge/badgelink/ca")
CA_FILES = ("gts-we1.der", "gts-root-r4.der", "gts-root-r1.der")
PHOTOS = ("photo-coast.png", "photo-lake.png", "photo-mountain.png")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    sources = {Path(name): APP / name for name in APP_FILES}
    sources[Path("ui.py")] = dependency_path("shared/ui.py")
    sources[Path("verified_tls.py")] = dependency_path("badgelink/badge/badgelink/verified_tls.py")
    sources[Path("ws_backoff.py")] = dependency_path("network/badge/ws_backoff.py")
    sources[Path("kb_shell.py")] = dependency_path("shared/kb_shell.py")
    sources[Path("identity_keyboard.py")] = dependency_path("identity/badge/identity/identity_keyboard.py")
    sources[Path("kbqwerty_board.py")] = dependency_path("kbqwerty/badge/kbqwerty/kbqwerty_board.py")
    for library, directory in LIBRARIES.items():
        # These pinned generic packages are maintained in the public SELECT source;
        # import dependencies are bundled without the fleet's application layer.
        for source in sorted(directory.glob("*.py")):
            sources[Path(library) / source.name] = source
    assets = {Path("ca") / name: CA / name for name in CA_FILES}
    assets.update({Path("assets") / name: APP / "assets" / name for name in PHOTOS})
    assets[Path("MonaSans-Medium.af")] = dependency_path("assets/fonts/MonaSans-Medium.af")
    assets[Path("LICENSE-MonaSans")] = dependency_path("assets/fonts/LICENSE-MonaSans")
    assets[Path("aiohttp") / "PROVENANCE.md"] = LIBRARIES["aiohttp"] / "PROVENANCE.md"
    if (APP / "icon.png").is_file():
        assets[Path("icon.png")] = APP / "icon.png"
    for source in list(sources.values()) + list(assets.values()):
        if not source.is_file():
            raise ValueError("required source missing: " + str(source.relative_to(REPO)))
    # A source relocation must not silently change the shared networking/UI
    # implementation. Keep the pinned dependency gate in the normal build.
    vendor = APP / "vendor"
    provenance = json.loads((vendor / "provenance.json").read_text())
    recorded = set(provenance["source_paths"]) | set(provenance.get("additional_sources", {}))
    bundled = {source.relative_to(vendor).as_posix(): digest(source)
               for source in list(sources.values()) + list(assets.values())
               if vendor in source.parents}
    if set(bundled) != recorded or bundled != provenance["files"]:
        raise ValueError("vendored dependencies differ from their recorded public provenance")
    return sources, assets


def compiler_info(toolchain):
    root = toolchain / "micropython"
    compiler = root / "mpy-cross" / "build" / "mpy-cross"
    if not compiler.is_file():
        raise ValueError("pinned mpy-cross is missing; see devices/badge/README.md")
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != PIN:
        raise ValueError("MicroPython toolchain commit differs from Badgeware pin " + PIN)
    header = (root / "py" / "persistentcode.h").read_text()
    match = re.search(r"^#define\s+MPY_VERSION\s+(\d+)", header, re.M)
    if not match:
        raise ValueError("cannot determine pinned firmware's MPY_VERSION")
    firmware_version = int(match.group(1))
    banner = subprocess.check_output([str(compiler), "--version"], text=True).strip()
    match = re.search(r"emitting mpy v(\d+)\.(\d+)", banner)
    if not match or int(match.group(1)) != firmware_version:
        raise ValueError("compiler bytecode format does not match the pinned firmware")
    return compiler, firmware_version, banner


def compile_one(compiler, source, output, relative, version):
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), "-X", "heapsize=67108864", "-msmall-int-bits=31",
                    "-s", "homehq/" + relative.as_posix(), "-o", str(output), str(source)], check=True)
    header = output.read_bytes()[:4]
    # _mpy does not encode the runtime's small-int width. Inspect the emitted
    # header and additionally load it in the pinned runtime when requested.
    if len(header) != 4 or header[0] != ord("M") or header[1] != version or header[2] >> 2 or header[3] > 31:
        raise ValueError("unexpected native/ABI header in " + relative.as_posix())


NODE_VERIFY = r'''
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {pathToFileURL} from 'node:url';
const [runtime, app, fonts] = process.argv.slice(1);
// With node -e, argv[1] is our first argument. The runtime interprets its own
// filename there as a CLI invocation; keep this host harness distinct.
process.argv[1]='homehq-bytecode-check';
const {loadMicroPython}=await import(pathToFileURL(runtime).href);
const logs=[];
const mp=await loadMicroPython({stdout:x=>logs.push(x),stderr:x=>logs.push(x)});
function mkdir(dir){let c='';for(const p of dir.split('/').filter(Boolean)){c+='/'+p;try{mp.FS.mkdir(c)}catch{}}}
function stage(src,dst){mkdir(dst);for(const e of fs.readdirSync(src,{withFileTypes:true})){const s=path.join(src,e.name),d=dst+'/'+e.name;if(e.isDirectory())stage(s,d);else mp.FS.writeFile(d,fs.readFileSync(s));}}
stage(app,'/system/apps/homehq');mkdir('/rom/fonts');mkdir('/state');
for(const name of ['smart.ppf','badgewaremax.ppf','sins.ppf'])mp.FS.writeFile('/rom/fonts/'+name,fs.readFileSync(path.join(fonts,name)));
// Opaque RGBA noise matches the web converter's worst practical output. This
// fixture exists only in the verifier's memory filesystem, never in the export.
let seed=0x31415926;
function randomByte(){seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return seed>>>24;}
const raw=Buffer.alloc(240*(320*4+1));let at=0;
for(let y=0;y<240;y++){raw[at++]=0;for(let x=0;x<320;x++){raw[at++]=randomByte();raw[at++]=randomByte();raw[at++]=randomByte();raw[at++]=255;}}
function crc(bytes){let v=0xffffffff;for(const b of bytes){v^=b;for(let i=0;i<8;i++)v=(v&1)?0xedb88320^(v>>>1):v>>>1;}return(v^0xffffffff)>>>0;}
function chunk(name,data){const kind=Buffer.from(name),head=Buffer.alloc(4),tail=Buffer.alloc(4);head.writeUInt32BE(data.length);tail.writeUInt32BE(crc(Buffer.concat([kind,data])));return Buffer.concat([head,kind,data,tail]);}
const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(320,0);ihdr.writeUInt32BE(240,4);ihdr[8]=8;ihdr[9]=6;
const photo=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',zlib.deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);
if(photo.length<=262144||photo.length>327680)throw new Error('large RGBA fixture outside intended photo-budget boundary');
mp.FS.writeFile('/state/homehq-test-photo.png',photo);
await mp.runPythonAsync(`
import builtins, sys, os, json, gc, picovector as pv
for name in dir(pv):
    if not name.startswith('__'):
        setattr(builtins,name,getattr(pv,name))
buf=bytearray(320*240*4)
builtins.screen=image(320,240,buf)
class Badge:
    default_clear=None
    def mode(self,mode): pass
    def pressed(self,button=None): return False
    def held(self,button=None): return False
class Display:
    def update(self): pass
builtins.badge=Badge()
builtins.display=Display()
builtins.HIRES=1
builtins.VSYNC=2
for key in ('A','B','C','UP','DOWN'):
    setattr(builtins,'BUTTON_'+key,key)
builtins.run=lambda update:update()
root='/system/apps/homehq'
sys.path.insert(0,root)
os.chdir(root)
files=[]
stack=[root]
while stack:
    directory=stack.pop()
    for entry in os.ilistdir(directory):
        target=directory+'/'+entry[0]
        if entry[1]&0x4000:
            stack.append(target)
        elif target.endswith('.mpy'):
            with open(target,'rb') as source:
                header=source.read(4)
            if header[0]!=77 or header[1]!=(sys.implementation._mpy&255) or header[2]>>2 or header[3]>31:
                raise AssertionError('incompatible bytecode '+target)
            files.append(target)
import model,demo,cache,service,transport,auth_client,login,kb_shell,identity_keyboard,kbqwerty_board,verified_tls,ui,view
import aiohttp,aiohttp.aiohttp_ws,realtime,realtime.client,realtime.phoenix,ws_backoff
# Imports cannot detect CPython-only string methods in an API body. Exercise
# the compiled Auth/RPC seams with immediate fake I/O; physical TLS is separate.
class APIHTTP:
    async def request(self,path,headers,body=None):
        data=({'access_token':'test-access','refresh_token':'test-refresh','expires_in':3600,'user':{'id':'test-user'}}
              if path.startswith('/auth/') else {'home':{'id':'test-home'}})
        return 200,json.dumps(data).encode()
class APIRealtime:
    async def set_access_token(self,token): pass
class APIClient:
    rpc=transport.SupabaseTransport.rpc
    def clock(self): return 1000
api=APIClient()
api.key='sb_publishable_fixture'
api.session={'v':1,'refresh_token':'test-old','user_id':'test-user'}
api.events=[]
api.http=APIHTTP()
api.realtime=APIRealtime()
api.auth=auth_client.AuthClient(api)
async def api_contract():
    result=await api.auth.refresh_session_async()
    assert result['status_code']==200 and 'error' not in result and api.ready
    assert api.events[0]['data']=={'v':1,'refresh_token':'test-refresh','user_id':'test-user'}
    result=await api.rpc('homehq_snapshot').execute_async()
    assert result=={'data':{'home':{'id':'test-home'}},'status_code':200}
    result=await api.auth.sign_in_with_password_async('member@example.test','test-password')
    assert result['status_code']==200 and 'error' not in result
contract=api_contract()
try:
    contract.send(None)
except StopIteration:
    pass
else:
    raise AssertionError('compiled API fixture unexpectedly requires network pumping')
api=None
class APILoginService:
    submitted=False
    def start_login(self,email,password):
        assert email=='member@example.test' and password=='test-password'
        self.submitted=True
        return True
signin=login.SignIn()
signin.auth_state='signed_out'
signin.email='member@example.test'
signin.password='test-password'
signin.focus=2
login_service=APILoginService()
assert signin.press('B',login_service) and login_service.submitted
assert not signin.email and not signin.password and signin.keyboard is None and signin.auth_state=='signing_in'
signin=None
threshold=getattr(gc,'threshold',None)
saved_threshold=threshold() if callable(threshold) else None
if saved_threshold is not None:
    threshold(-1)
product=__import__(root)
if product.debug_snapshot()['page']!='today':
    raise AssertionError('standalone bytecode entry did not reach Today')
if not product._view.vector:
    raise AssertionError('standalone export did not load its bundled outline font')
if not any(buf[i]!=242 for i in range(0,len(buf),4)):
    raise AssertionError('standalone bytecode entry did not draw content')
photo=image.load('/state/homehq-test-photo.png')
if photo.width!=320 or photo.height!=240 or photo.has_palette:
    raise AssertionError('large web-style RGBA photo did not decode natively')
product._app.page=4
product._app._align()
product._view.draw(product._app,'/state/homehq-test-photo.png')
gc_lifecycle=[]
if saved_threshold is not None:
    # Exercise the compiled app lifecycle through the real interpreter, not a
    # CPython imitation of gc.threshold(). A close error must restore policy.
    if threshold()!=262144:
        raise AssertionError('compiled entry did not set allocation GC policy')
    product.on_exit()
    if threshold()!=-1:
        raise AssertionError('compiled exit did not restore disabled threshold')
    gc_lifecycle.append('disabled restored')
    for previous in (65536,524288):
        threshold(previous)
        sys.modules.pop(root)
        product=__import__(root)
        if threshold()!=min(previous,262144):
            raise AssertionError('compiled entry weakened existing GC policy')
        def fail_close():
            raise OSError('injected close failure')
        product._service.close=fail_close
        try:
            product.on_exit()
        except OSError:
            pass
        else:
            raise AssertionError('close failure was not exercised')
        if threshold()!=previous:
            raise AssertionError('close failure leaked allocation GC policy')
        gc_lifecycle.append('close failure restored '+str(previous))
    threshold(saved_threshold)
print(json.dumps({'files':len(files),'runtime_mpy':sys.implementation._mpy,'entry':'today','font':'bundled outline','photo':'320x240 RGBA over 256 KiB','photo_bytes':os.stat('/state/homehq-test-photo.png')[6],'network':'not configured','compiled_auth_rpc_api':True,'compiled_signin_submit':True,'gc_lifecycle':gc_lifecycle}))
`);
for(const log of logs)console.log(log);
'''


def verify_runtime(runtime, app, toolchain):
    provenance = runtime.parent / "provenance.json"
    if not provenance.is_file() or json.loads(provenance.read_text()).get("micropython", {}).get("commit") != PIN:
        raise ValueError("verification runtime must have matching pinned provenance.json")
    fonts = toolchain / "tufty2350" / "romfs" / "fonts"
    if not fonts.is_dir():
        raise ValueError("byte-exact ROM fonts missing from pinned Tufty source")
    result = subprocess.run(["node", "--input-type=module", "-e", NODE_VERIFY, str(runtime), str(app), str(fonts)],
                            text=True, capture_output=True)
    if result.returncode:
        raise ValueError("bytecode import check failed:\n" + (result.stderr or result.stdout).strip())
    print(result.stdout.strip())
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("runtime did not report a successful bytecode entry")


def build(out, toolchain, runtime=None):
    sources, assets = inputs()
    compiler, version, banner = compiler_info(toolchain)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="homehq-build-", dir=str(out.parent)) as temporary:
        root = Path(temporary)
        source_root, bytecode_root = root / "source" / "homehq", root / "mpy" / "homehq"
        hashes = {}
        for relative, source in sources.items():
            exported = source_root / relative
            exported.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, exported)
            compiled = bytecode_root / relative.with_suffix(".mpy")
            compile_one(compiler, exported, compiled, relative, version)
            witness = root / "check" / relative.with_suffix(".mpy")
            compile_one(compiler, exported, witness, relative, version)
            if compiled.read_bytes() != witness.read_bytes():
                raise ValueError("non-reproducible bytecode: " + relative.as_posix())
            hashes["source/homehq/" + relative.as_posix()] = digest(exported)
            hashes["mpy/homehq/" + relative.with_suffix(".mpy").as_posix()] = digest(compiled)
        for relative, source in assets.items():
            for mode in ("source", "mpy"):
                exported = root / mode / "homehq" / relative
                exported.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, exported)
                hashes[mode + "/homehq/" + relative.as_posix()] = digest(exported)
        if list(bytecode_root.rglob("*.py")):
            raise ValueError("source file would shadow installed bytecode")
        verification = verify_runtime(runtime, bytecode_root, toolchain) if runtime else None
        manifest = {"schema_version": 1, "artifact": "standalone-homehq", "micropython_commit": PIN,
                    "compiler": banner, "mpy_version": version, "small_int_bits": 31,
                    "reproducible": True, "runtime_verification": verification, "files": hashes}
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (root / ".homehq-build").write_text("standalone-homehq\n")
        shutil.rmtree(root / "check")
        if out.exists():
            if out.is_symlink() or not (out / ".homehq-build").is_file():
                raise ValueError("refusing to replace an output directory not created by this builder")
            existing = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
            expected = set(hashes) | {"manifest.json", ".homehq-build"}
            if existing - expected:
                raise ValueError("previous output contains unexpected files; choose a fresh --out directory")
            shutil.rmtree(out)
        shutil.move(str(root), str(out))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "build")
    parser.add_argument("--toolchain", type=Path, default=Path(os.environ.get("HOMEHQ_TOOLCHAIN", "~/.cache/badge-playground")).expanduser())
    parser.add_argument("--verify-runtime", type=Path, help="matching pinned micropython.mjs; performs real bytecode imports and offline first paint")
    args = parser.parse_args()
    try:
        result = build(args.out.resolve(), args.toolchain.resolve(), args.verify_runtime.resolve() if args.verify_runtime else None)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit("Home HQ build failed: " + str(error))
    print("Built {} bytecode modules; mpy v{}; reproducible; runtime {}".format(
        sum(path.endswith(".mpy") for path in result["files"]), result["mpy_version"],
        "verified" if result["runtime_verification"] else "not verified (use --verify-runtime)"))
    print(args.out.resolve())


if __name__ == "__main__":
    main()
