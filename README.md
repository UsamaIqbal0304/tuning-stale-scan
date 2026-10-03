# tuning-stale-scan

What notices that a device stopped talking, and why by default nothing does.
The tuning policy's three time properties, the one branch in the framework that
acts on them, and the thread that is supposed to wake up and check. Read out of
`driver-rt.jar` and `baja.jar` rather than out of the documentation.

One Python file, standard library only.

```
./tuning-stale-scan.py [NIAGARA_HOME]
```

## Why this exists

Every proxy point on a Niagara station sits under a tuning policy, and that
policy owns `staleTime` - the property that is supposed to notice a value has
stopped arriving.

**It defaults to zero, and zero means off.** `Tuning.process()` is the only
code in the framework that acts on it: it loads `staleTime`, compares it with
zero, and on less-or-equal jumps straight to the method's own return. So on a
default station, no point under any driver ever goes stale, no matter how long
the device has been silent.

That matters most where polling is not what keeps a value fresh. If a device
reports unsolicited - a meter pushing, a wireless gateway relaying, an MQTT or
BACnet COV subscription - then nothing fails when it dies. No poll errors, so
no fault status; `staleTime` is zero, so no stale flag. The last value it ever
sent sits there with an ok status for as long as the station runs.

The second finding is the one that defeats a fix. With `staleTime` set, the
comparison is against `readTicks`, and `readTicks` is only ever set by
`readOk()`. If a driver calls `readOk()` when a link or a subscription is
healthy rather than when a value actually arrives, a configured `staleTime`
still never fires. That is one line in a proxy extension, and it decides
whether the feature works at all.

Two smaller ones worth knowing. The background thread's wake interval is
computed by halving `maxScan` towards each of the three time properties, but
only for a property greater than zero - so with the defaults it wakes every
20 seconds and has nothing to check. And the tuning machinery's four operations
each swallow their exception to `printStackTrace()`, which is stderr, where a
station's log export will not have it.

## What it reads, and where from

- `javax.baja.driver.util.BTuningPolicy` - the three time properties and their
  defaults, read out of the static initialiser with their minimum facets.
- `com.tridium.driver.util.Tuning` - `process()` disassembled, so the
  zero-check, the branch target and the comparison against `readTicks` are read
  off the bytecode rather than inferred.
- `stale()` - its three instructions, and which call it ends on.
- `BackgroundThread.computeScanFrequency()` - the halving, the clamp, and the
  thread's name.
- The logger name, the warning text, and every `printStackTrace()` site in the
  tuning classes.

## Read first: what it does and does not touch

**It never connects to a station.** It unzips the two jars out of
`modules/` and runs `javap`. Nothing is installed, patched, written to a
station or sent anywhere.

It needs a Niagara installation to read and a `javap` from a JDK 8. It looks
for `javap` in `$JAVAP`, then on `PATH`, then under `$JAVA_HOME` and the
Niagara install, then in Debian's default location. The install to read comes
from the first argument.

**The output below was measured against Niagara 4.15.5.22.** Another version
may differ, and that is the point - run it against yours rather than trusting
this page.

## Running it

```
$ ./tuning-stale-scan.py
Stale points: what notices that a device stopped talking
======================================================================

read from /opt/Niagara/Niagara-4.15.5.22
javap:    1.8.0_504

The default tuning policy, read out of the static initialiser:
  minWriteTime   0 ms     (min facet 0 ms)
  maxWriteTime   0 ms     (min facet 0 ms)
  staleTime      0 ms     (min facet 0 ms)
  writeOnStart   true
  writeOnUp      true
  writeOnEnabled true

Tuning.process(), the only code in the framework that notices:
  at offset 160 it loads staleTime, compares it with zero, and on
  less-or-equal jumps to 212 - which is the method's own return.
  The default is 0, so by default this branch is never taken and no
  point in any driver on the station ever goes stale.

  With staleTime set, the rest reads:
    elapsed = now - (mode.isWriteonly() ? writeTicks : readTicks)
    if elapsed > staleTime, call stale()   (the branch is ifle)
  so the threshold is strictly greater than staleTime, and the clock is
  readTicks - which only readOk() ever sets.

stale() is three instructions: get the tunable, call setStale(true, null).
  It is the driver's own BITunable implementation that decides what
  that means for the point's status and value. The framework sets a
  flag and stops.

How often: BackgroundThread sleeps computeScanFrequency() milliseconds,
  which starts at maxScan = 20000 and is halved towards each of the three
  time properties - but only for a property greater than zero - then
  clamped up to minScan = 200. With the defaults, all three are zero,
  so the thread wakes every 20000 ms and has nothing to check.
  The thread is named 'Tuning:' plus the network name.

Where the errors go. Tuning holds a logger named 'driver.tuning' with
  1 warning call, and 4 printStackTrace() sites.
  The warning says: TuningPolicy not found:
  The stack traces are in:
    void write(javax.baja.sys.Context)
    void readSubscribed()
    void readUnsubscribed()
    void stale()
  Those are the four things the tuning machinery does. Every one of
  them swallows its exception to stderr, where a station's log export
  will not have it.
  The background thread does the same with anything process() throws,
  and nulls a tuning out of its array when process() returns false.

Two consequences worth designing for
----------------------------------------------------------------------
  1. If your device reports unsolicited rather than being polled, a
     dead device is invisible by default. No poll fails, so nothing
     goes fault; staleTime is 0, so nothing goes stale; the last
     value sits there with an ok status for as long as the station runs.
  2. staleTime measures readTicks, and readTicks is set by readOk().
     If a driver calls readOk() when a link or a subscription is
     healthy rather than when a value actually arrives, then even a
     configured staleTime never fires. That is one line in a proxy
     extension and it decides whether the feature works at all.

Three checks one station settles in an afternoon
----------------------------------------------------------------------
  1. Read the default tuning policy on a live network and confirm
     staleTime is 0. If it is, no point under it can go stale.
  2. Set staleTime to a minute on one point, pull the device, and watch
     whether the point goes stale within 20000 ms of the minute.
  3. Set staleTime, leave the device alive but stop its reporting at
     the source, and see whether the point still goes stale. If it does
     not, readOk() is being called for the wrong event.
```

## Licence

MIT. Written by Usama Iqbal at [Plantroom Labs](https://plantroomlabs.com).
