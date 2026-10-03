#!/usr/bin/env python3
"""What a Niagara station does with a point whose device stopped talking.

    tools/tuning-stale-scan.py [NIAGARA_HOME]

Why this exists. Every driver point in Niagara is tuned by a BTuningPolicy,
and one of that policy's six properties - staleTime - is the only thing in the
framework that notices a point has gone quiet. For a polled device that barely
matters, because a failed poll sets fault anyway. For anything that reports
unsolicited - a wireless sensor, a meter that pushes, an MQTT or EnOcean
telegram, a device that sends on change - staleTime is the whole of the
liveness story: no poll fails, so nothing goes fault, and the last value just
sits there.

This script reads the answer out of driver-rt.jar rather than asserting it:
the six property defaults out of BTuningPolicy's static initialiser, the
skip-if-zero branch out of Tuning.process's bytecode, the scan interval out of
BTuningPolicyMap, which clock the check reads, and where the errors go.

Nothing is installed, patched or sent anywhere. unzip and javap only.
"""
import os
import shutil
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def _find_javap(niagara_home=None):
    """javap from $JAVAP, then PATH, then the JDK Niagara ships, then Debian's."""
    cand = [os.environ.get("JAVAP"), shutil.which("javap")]
    for base in (os.environ.get("JAVA_HOME"), niagara_home):
        if base:
            cand += [os.path.join(base, "bin", "javap"),
                     os.path.join(base, "jre", "bin", "javap")]
    cand.append("/usr/lib/jvm/java-8-openjdk-amd64/bin/javap")
    for c in cand:
        if c and os.path.exists(c):
            return c
    return None

HOME = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/Niagara/Niagara-4.15.5.22")
JAVAP = _find_javap(str(HOME))
JARS = ("driver-rt.jar", "baja.jar")

LONG1 = {"lconst_0": 0, "lconst_1": 1}


def abort(msg):
    print("ABORT " + msg, file=sys.stderr)
    sys.exit(2)


def dis(classpath, cls):
    out = subprocess.run([JAVAP, "-p", "-c", "-classpath", str(classpath), cls],
                         capture_output=True, text=True)
    if out.returncode != 0 or "Compiled from" not in out.stdout:
        abort("javap failed on %s: %s" % (cls, out.stderr.strip()[:200]))
    return out.stdout


def method(text, sig, what):
    """The bytecode of one method: from its signature to the blank line."""
    i = text.find(sig)
    if i < 0:
        abort("no %s in this jar (looked for %r)" % (what, sig))
    j = text.find("\n\n", i)
    return text[i:j if j > 0 else len(text)]


def one(hay, pat, what):
    m = re.findall(pat, hay)
    if len(m) != 1:
        abort("%d matches for %s (expected 1)" % (len(m), what))
    return m[0]


def millis(tok, what):
    """A long pushed by a one-byte constant, or an ldc2_w with a value."""
    if tok in LONG1:
        return LONG1[tok]
    m = re.match(r"ldc2_w\s+#\d+\s+// long (-?\d+)l", tok)
    if not m:
        abort("cannot read a long out of %r (%s)" % (tok, what))
    return int(m.group(1))


if not JAVAP:
    abort("no javap found - set $JAVAP or put a JDK 8 javap on PATH")
for jar in JARS:
    if not (HOME / "modules" / jar).exists():
        abort("no %s under %s" % (jar, HOME / "modules"))

work = Path(tempfile.mkdtemp(prefix="tuning-scan-"))
for jar in JARS:
    with zipfile.ZipFile(HOME / "modules" / jar) as z:
        z.extractall(work)

ver = subprocess.run([JAVAP, "-version"], capture_output=True, text=True).stdout.strip()
TP = dis(work, "javax.baja.driver.point.BTuningPolicy")
TPM = dis(work, "javax.baja.driver.point.BTuningPolicyMap")
BG = dis(work, "javax.baja.driver.point.BTuningPolicyMap$BackgroundThread")
TUN = dis(work, "javax.baja.driver.point.Tuning")

print("Stale points: what notices that a device stopped talking")
print("=" * 70)
print()
print("read from %s" % HOME)
print("javap:    %s" % ver)
print()

# ---- 1. the six defaults, out of the static initialiser -------------------
tp_static = method(TP, "  static {};", "BTuningPolicy's static initialiser")
times = {}
for prop in ("minWriteTime", "maxWriteTime", "staleTime"):
    m = re.search(r"(lconst_[01]|ldc2_w\s+#\d+\s+// long -?\d+l)\n"
                  r"\s+\d+: invokestatic\s+#\d+\s+"
                  r"// Method javax/baja/sys/BRelTime\.make:\(J\)"
                  r"Ljavax/baja/sys/BRelTime;\n"
                  r"\s+\d+: ldc\s+#\d+\s+// String min\n"
                  r"\s+\d+: (lconst_[01]|ldc2_w\s+#\d+\s+// long -?\d+l)"
                  r"[\s\S]{0,700}?// Field %s:Ljavax/baja/sys/Property;" % prop,
                  tp_static)
    if not m:
        abort("could not read the %s default out of the static block" % prop)
    times[prop] = (millis(m.group(1), prop), millis(m.group(2), prop + " min facet"))

flags = {}
for prop in ("writeOnStart", "writeOnUp", "writeOnEnabled"):
    m = re.search(r"(iconst_[01])\n\s+\d+: aconst_null\n\s+\d+: invokestatic\s+#\d+\s+"
                  r"// Method newProperty:\(IZLjavax/baja/sys/BFacets;\)"
                  r"Ljavax/baja/sys/Property;\n\s+\d+: putstatic\s+#\d+\s+"
                  r"// Field %s:Ljavax/baja/sys/Property;" % prop, tp_static)
    if not m:
        abort("could not read the %s default out of the static block" % prop)
    flags[prop] = m.group(1) == "iconst_1"

print("The default tuning policy, read out of the static initialiser:")
for prop in ("minWriteTime", "maxWriteTime", "staleTime"):
    val, facet = times[prop]
    print("  %-14s %-8s (min facet %s ms)" % (prop, "%d ms" % val, facet))
for prop in ("writeOnStart", "writeOnUp", "writeOnEnabled"):
    print("  %-14s %s" % (prop, str(flags[prop]).lower()))
print()

stale_ms = times["staleTime"][0]

# ---- 2. the skip-if-zero branch ------------------------------------------
proc = method(TUN, "  boolean process();", "Tuning.process")
skip = re.search(r"(\d+): lload\s+(\d+)\n\s+\d+: lconst_0\n\s+\d+: lcmp\n"
                 r"\s+\d+: ifle\s+(\d+)\n[\s\S]{0,200}?"
                 r"// InterfaceMethod javax/baja/driver/point/BITunable\.getMode",
                 proc)
if not skip:
    abort("could not find the staleTime guard in Tuning.process")
guard_at, guard_target = int(skip.group(1)), int(skip.group(3))
tail = re.search(r"(\d+): iconst_1\n\s+(\d+): ireturn", proc)
if not tail or int(tail.group(1)) != guard_target:
    abort("the staleTime guard does not jump to the method's own return "
          "(jumps to %d)" % guard_target)
cmp_op = one(proc, r"lcmp\n\s+\d+: (ifle)\s+%d\n\s+\d+: aload_0\n"
                   r"\s+\d+: invokevirtual\s+#\d+\s+// Method stale:\(\)V"
                   % guard_target,
             "the elapsed-vs-staleTime comparison")
writeonly = "isWriteonly" in proc
read_field = "readTicks" in proc and "writeTicks" in proc

print("Tuning.process(), the only code in the framework that notices:")
print("  at offset %d it loads staleTime, compares it with zero, and on" % guard_at)
print("  less-or-equal jumps to %d - which is the method's own return." % guard_target)
print("  The default is %d, so by default this branch is never taken and no" % stale_ms)
print("  point in any driver on the station ever goes stale.")
print()
print("  With staleTime set, the rest reads:")
if writeonly and read_field:
    print("    elapsed = now - (mode.isWriteonly() ? writeTicks : readTicks)")
else:
    abort("process() no longer picks its clock by read/write mode")
# ifle skips the call when elapsed <= staleTime, so the call needs strictly >
if cmp_op != "ifle":
    abort("the elapsed comparison is %s, not ifle - re-read the branch" % cmp_op)
print("    if elapsed > staleTime, call stale()   (the branch is %s)" % cmp_op)
print("  so the threshold is strictly greater than staleTime, and the clock is")
print("  readTicks - which only readOk() ever sets.")
print()

# ---- 3. what stale() actually does --------------------------------------
st = method(TUN, "  void stale();", "Tuning.stale")
set_stale = one(st, r"// InterfaceMethod javax/baja/driver/point/BITunable\."
                    r"(setStale):\(ZLjavax/baja/sys/Context;\)V",
                "the setStale call")
arg = one(st, r"invokevirtual\s+#\d+\s+// Method getTunable[\s\S]{0,80}?"
              r"(iconst_[01])\n\s+\d+: aconst_null", "the setStale argument")
print("stale() is three instructions: get the tunable, call %s(%s, null)."
      % (set_stale, "true" if arg == "iconst_1" else "false"))
print("  It is the driver's own BITunable implementation that decides what")
print("  that means for the point's status and value. The framework sets a")
print("  flag and stops.")
print()

# ---- 4. how often the check runs ----------------------------------------
tpm_static = method(TPM, "  static {};", "BTuningPolicyMap's static initialiser")
min_scan = int(one(tpm_static, r"ldc2_w\s+#\d+\s+// long (\d+)l\n\s+\d+: putstatic"
                               r"\s+#\d+\s+// Field minScan:J", "minScan"))
max_scan = int(one(tpm_static, r"ldc2_w\s+#\d+\s+// long (\d+)l\n\s+\d+: putstatic"
                               r"\s+#\d+\s+// Field maxScan:J", "maxScan"))
csf = method(TPM, "  long computeScanFrequency();", "computeScanFrequency")
halves = len(re.findall(r"lcmp\n\s+\d+: ifle\s+\d+\n[\s\S]{0,120}?"
                        r"ldc2_w\s+#\d+\s+// long 2l\n\s+\d+: ldiv", csf))
if halves != 3:
    abort("expected 3 halve-the-scan branches in computeScanFrequency, got %d"
          % halves)
print("How often: BackgroundThread sleeps computeScanFrequency() milliseconds,")
print("  which starts at maxScan = %d and is halved towards each of the three"
      % max_scan)
print("  time properties - but only for a property greater than zero - then")
print("  clamped up to minScan = %d. With the defaults, all three are zero," % min_scan)
print("  so the thread wakes every %d ms and has nothing to check." % max_scan)
print("  The thread is named 'Tuning:' plus the network name.")
print()

# ---- 5. where the errors go ---------------------------------------------
pst = len(re.findall(r"printStackTrace", TUN))
warns = re.findall(r"// String ([^\n]*?)\n[\s\S]{0,700}?"
                   r"// Method java/util/logging/Logger\.warning", TUN)
logname = one(method(TUN, "  static {};", "Tuning's static initialiser"),
              r'// String (\S+)\n\s+\d+: invokestatic\s+#\d+\s+'
              r'// Method java/util/logging/Logger\.getLogger',
              "the logger name")
holders = []
cur = None
for ln in TUN.split("\n"):
    if re.match(r"^  [\w$.<>\[\]]+[\w ]*\(.*\);$|^  (?:public|static|final|void)"
                r".*\(.*\);$", ln):
        cur = ln.strip().rstrip(";")
    if "printStackTrace" in ln and cur:
        holders.append(cur)
print("Where the errors go. Tuning holds a logger named '%s' with" % logname)
print("  %d warning call%s, and %d printStackTrace() sites."
      % (len(warns), "" if len(warns) == 1 else "s", pst))
if warns:
    print("  The warning says: %s" % warns[0].strip())
print("  The stack traces are in:")
for h in holders:
    print("    %s" % h)
print("  Those are the four things the tuning machinery does. Every one of")
print("  them swallows its exception to stderr, where a station's log export")
print("  will not have it.")
if "printStackTrace" in BG:
    print("  The background thread does the same with anything process() throws,")
    print("  and nulls a tuning out of its array when process() returns false.")
print()

print("Two consequences worth designing for")
print("-" * 70)
print("  1. If your device reports unsolicited rather than being polled, a")
print("     dead device is invisible by default. No poll fails, so nothing")
print("     goes fault; staleTime is %d, so nothing goes stale; the last" % stale_ms)
print("     value sits there with an ok status for as long as the station runs.")
print("  2. staleTime measures readTicks, and readTicks is set by readOk().")
print("     If a driver calls readOk() when a link or a subscription is")
print("     healthy rather than when a value actually arrives, then even a")
print("     configured staleTime never fires. That is one line in a proxy")
print("     extension and it decides whether the feature works at all.")
print()
print("Three checks one station settles in an afternoon")
print("-" * 70)
print("  1. Read the default tuning policy on a live network and confirm")
print("     staleTime is %d. If it is, no point under it can go stale." % stale_ms)
print("  2. Set staleTime to a minute on one point, pull the device, and watch")
print("     whether the point goes stale within %d ms of the minute."
      % (max_scan if max_scan else 0))
print("  3. Set staleTime, leave the device alive but stop its reporting at")
print("     the source, and see whether the point still goes stale. If it does")
print("     not, readOk() is being called for the wrong event.")
