"""Make the HDS reference: generate the HDL of a real project with HDS itself (batch mode on the
Linux server where HDS is installed), and bring it here to compare Dolphin HDS against.

    python tests/hds_compare/hds_reference.py

What it does, all through ssh/scp with the key ~/.ssh/id_ed25519_dolphin_hds:
  1. copies the project folder to /tmp/dolphin_hds_check/src on the server. The real project
     is only read: nothing is ever written in it.
  2. copies your HDS settings (~/hdl_designer_series) to /tmp/dolphin_hds_check/home, so that HDS
     generates with your own preferences without touching them.
  3. in the copy, moves aside the HDL of every unit that has a graphical view, and HDS's file
     caches (.xrf, .hdlsidedata, .cache.dat). Otherwise HDS treats the existing .v files as source
     files and refuses to generate over them.
  4. runs  hdl_designer -hdpfile <copy> -user_home ... -team_home ... -tcl gen.tcl  under xvfb-run:
     setupGenerate -generateAlways ON, then runGenerate on every regular library.
  5. downloads the copy (diagrams + the HDL HDS just wrote) to tests/hds_compare/reference/, with
     hds_generated.txt listing the files HDS wrote and gen.log its output.

Settings (environment variables): DHDS_HDS_HOST (lampn0@192.168.35.25), DHDS_HDS_PROJECT (the
.hdp on the server), DHDS_HDS_HOME (/tools/mentor/HDS_2024.2), DHDS_HDS_LICENSE (8787@dt70-linux),
DHDS_HDS_KEY (~/.ssh/id_ed25519_dolphin_hds), DHDS_HDS_ENV (extra NAME=value for the .hdp).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, 'reference')
HOST = os.environ.get('DHDS_HDS_HOST', 'lampn0@192.168.35.25')
PROJECT = os.environ.get('DHDS_HDS_PROJECT',
                         '/data_sip/sip4/workspace/lampn0/dolphinware_ip_db/dti_hbm/trunk/src/dti_hbm.hdp')
HDS_HOME = os.environ.get('DHDS_HDS_HOME', '/tools/mentor/HDS_2024.2')
LICENSE = os.environ.get('DHDS_HDS_LICENSE', '8787@dt70-linux')
KEY = os.path.expanduser(os.environ.get('DHDS_HDS_KEY', '~/.ssh/id_ed25519_dolphin_hds'))
WORK = '/tmp/dolphin_hds_check'           # on the server; the only place written there
# variables the .hdp uses (dti_hbm maps an include search path to $dti_axi_sw)
EXTRA_ENV = os.environ.get('DHDS_HDS_ENV', f'dti_axi_sw={WORK}/src/libs/dti_axi_sw/include')
SSH = ['ssh', '-i', KEY, '-o', 'BatchMode=yes', HOST]

# Libraries HDS generates (the regular libraries of dti_hbm; standard/protected ones are skipped).
LIBRARIES = ('dataflow_controller datapath dfi_bridge dti_hbm dti_io dti_umc40_phy_lib p1500_port '
             'phy_ctl_blk_lib port_bridge protocol_controller register_block')

GEN_TCL = f'''setupGenerate -generateAlways ON
foreach lib {{{LIBRARIES}}} {{
  if {{[catch {{runGenerate $lib}} err]}} {{ puts "GENERR $lib $err" }} else {{ puts "GENOK $lib" }}
}}
puts "TCL done"
exit
'''

# Runs on the server, in the COPY: move the HDL of every unit with a graphical view to orig/ and
# HDS's caches to orig_cache/, so that HDS generates all of them again.
MOVE_ASIDE = r'''
import os, re, shutil
D = "/tmp/dolphin_hds_check"; P = D + "/src"
hdp = [f for f in os.listdir(P) if f.endswith(".hdp")][0]
hdl, hds, sec = {}, {}, None
for line in open(os.path.join(P, hdp)):
    line = line.strip()
    m = re.match(r"\[(\w+)\]", line)
    if m:
        sec = m.group(1); continue
    if "=" in line and sec in ("hdl", "hds"):
        k, v = [x.strip() for x in line.split("=", 1)]
        (hdl if sec == "hdl" else hds).setdefault(k, v.replace("$HDS_PROJECT_DIR", P))
moved = 0
for lib, hdir in hds.items():
    if lib not in hdl or not os.path.isdir(hdir):
        continue
    for unit in os.listdir(hdir):
        u = os.path.join(hdir, unit)
        if not os.path.isdir(u) or not any(f.endswith((".bd", ".sm", ".fc", ".tt", ".asm")) for f in os.listdir(u)):
            continue
        for ext in (".v", ".sv"):
            f = os.path.join(hdl[lib], unit + ext)
            if os.path.exists(f):
                dst = os.path.join(D, "orig", lib, unit + ext)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(f, dst); moved += 1
for root, dirs, files in os.walk(P):
    for name in list(dirs) + files:
        if name in (".xrf", ".hdlsidedata", ".cache.dat"):
            src = os.path.join(root, name)
            dst = os.path.join(D, "orig_cache", os.path.relpath(src, P))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            if name in dirs:
                dirs.remove(name)
print("moved", moved, "HDL files aside")
'''


def remote(script: str, timeout: int = 1800) -> str:
    """Run a bash script on the server; return its output (raise on failure)."""
    run = subprocess.run(SSH + ['bash -s'], input=script, capture_output=True, text=True, timeout=timeout)
    if run.returncode != 0:
        raise SystemExit(f'server step failed:\n{run.stdout}\n{run.stderr}')
    return run.stdout


def main() -> int:
    src_dir = os.path.dirname(PROJECT)
    hdp = os.path.basename(PROJECT)
    print('1-3. copying the project and settings on the server, moving generated HDL aside', flush=True)
    print(remote(f'''set -e
rm -rf {WORK}; mkdir -p {WORK}
cp -a {src_dir} {WORK}/src
find {WORK}/src -name "*.lck" -delete
cp -a ~/hdl_designer_series {WORK}/home
cat > {WORK}/gen.tcl <<'EOF'
{GEN_TCL}EOF
cat > {WORK}/move_aside.py <<'EOF'
{MOVE_ASIDE}EOF
python3 {WORK}/move_aside.py
'''))
    print('4. running HDS batch generation (several minutes)', flush=True)
    out = remote(f'''cd {WORK}; touch marker
export HDS_HOME={HDS_HOME} LM_LICENSE_FILE={LICENSE} {EXTRA_ENV}
timeout 1700 xvfb-run -a $HDS_HOME/bin/hdl_designer -hdpfile {WORK}/src/{hdp} \
  -user_home {WORK}/home/hds_user -team_home {WORK}/home/hds_team -tcl {WORK}/gen.tcl > gen.log 2>&1 || true
find src -newer marker -type f \\( -name "*.v" -o -name "*.sv" \\) > hds_generated.txt
grep "GENOK\\|GENERR\\|TCL done" gen.log; echo "HDS wrote $(wc -l < hds_generated.txt) files"
tar czf {WORK}.tgz src orig hds_generated.txt gen.log home/hds_user/v2024.2/hds_user_prefs home/hds_team/v2024.2/hds_team_prefs
''')
    print(out)
    print('5. downloading to', REF, flush=True)
    tgz = os.path.join(HERE, 'reference.tgz')
    subprocess.run(['scp', '-q', '-i', KEY, '-o', 'BatchMode=yes', f'{HOST}:{WORK}.tgz', tgz], check=True)
    shutil.rmtree(REF, ignore_errors=True)
    os.makedirs(REF)
    with tarfile.open(tgz) as t:
        t.extractall(REF)
    os.remove(tgz)
    os.makedirs(os.path.join(REF, 'prefs'), exist_ok=True)
    for name, rel in (('hds_user_prefs', 'home/hds_user/v2024.2/hds_user_prefs'),
                      ('hds_team_prefs', 'home/hds_team/v2024.2/hds_team_prefs')):
        shutil.move(os.path.join(REF, rel), os.path.join(REF, 'prefs', name))
    shutil.rmtree(os.path.join(REF, 'home'), ignore_errors=True)
    print('done: now run  python tests/hds_compare/compare.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
