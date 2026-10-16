"""How much of the PC SpeakerWeave itself uses: processor time, memory, threads.

Windows is asked directly (kernel32), so no extra library is needed. Elsewhere (when
SpeakerWeave is tested on Linux) the same numbers come from /proc.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import byref, c_size_t, c_ulong, c_ulonglong, c_void_p, sizeof


class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", c_ulong), ("hi", c_ulong)]

    def seconds(self) -> float:
        return ((self.hi << 32) | self.lo) * 1e-7          # 100 ns steps


class _MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", c_ulong), ("PageFaultCount", c_ulong), ("PeakWorkingSetSize", c_size_t),
                ("WorkingSetSize", c_size_t), ("QuotaPeakPagedPoolUsage", c_size_t),
                ("QuotaPagedPoolUsage", c_size_t), ("QuotaPeakNonPagedPoolUsage", c_size_t),
                ("QuotaNonPagedPoolUsage", c_size_t), ("PagefileUsage", c_size_t),
                ("PeakPagefileUsage", c_size_t), ("PrivateUsage", c_size_t)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", c_ulong), ("dwMemoryLoad", c_ulong), ("ullTotalPhys", c_ulonglong),
                ("ullAvailPhys", c_ulonglong), ("ullTotalPageFile", c_ulonglong),
                ("ullAvailPageFile", c_ulonglong), ("ullTotalVirtual", c_ulonglong),
                ("ullAvailVirtual", c_ulonglong), ("ullAvailExtendedVirtual", c_ulonglong)]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", c_ulong), ("cntUsage", c_ulong), ("th32ThreadID", c_ulong),
                ("th32OwnerProcessID", c_ulong), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", c_ulong)]


class _Windows:
    def __init__(self):
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = c_void_p
        self.k32 = k32
        self.me = c_void_p(k32.GetCurrentProcess())

    def process_cpu(self) -> float:
        made, ended, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        self.k32.GetProcessTimes(self.me, byref(made), byref(ended), byref(kernel), byref(user))
        return kernel.seconds() + user.seconds()

    def system_cpu(self):
        """(busy seconds, all seconds) of every processor together."""
        idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not self.k32.GetSystemTimes(byref(idle), byref(kernel), byref(user)):
            return None
        total = kernel.seconds() + user.seconds()           # kernel time includes idle time
        return total - idle.seconds(), total

    def memory(self) -> dict:
        counters = _MEMORY_COUNTERS()
        counters.cb = sizeof(counters)
        self.k32.K32GetProcessMemoryInfo(self.me, byref(counters), counters.cb)
        status = _MEMORYSTATUSEX()
        status.dwLength = sizeof(status)
        self.k32.GlobalMemoryStatusEx(byref(status))
        return {"in_use": counters.WorkingSetSize, "private": counters.PrivateUsage,
                "peak": counters.PeakWorkingSetSize, "pc_total": status.ullTotalPhys}

    def handles(self) -> int:
        count = c_ulong()
        self.k32.GetProcessHandleCount(self.me, byref(count))
        return count.value

    def threads(self) -> int:
        self.k32.CreateToolhelp32Snapshot.restype = c_void_p
        snap = self.k32.CreateToolhelp32Snapshot(0x4, 0)     # TH32CS_SNAPTHREAD
        if not snap or snap == c_void_p(-1).value:
            return threading.active_count()
        try:
            entry = _THREADENTRY32()
            entry.dwSize = sizeof(entry)
            me, count = os.getpid(), 0
            ok = self.k32.Thread32First(c_void_p(snap), byref(entry))
            while ok:
                if entry.th32OwnerProcessID == me:
                    count += 1
                ok = self.k32.Thread32Next(c_void_p(snap), byref(entry))
            return count
        finally:
            self.k32.CloseHandle(c_void_p(snap))


class _Proc:
    """Linux, for the tests."""

    def process_cpu(self) -> float:
        t = os.times()
        return t.user + t.system

    def system_cpu(self):
        try:
            with open("/proc/stat", encoding="ascii") as fh:
                parts = [float(v) for v in fh.readline().split()[1:]]
        except OSError:
            return None
        tick = os.sysconf("SC_CLK_TCK")
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
        total = sum(parts[:8])
        return (total - idle) / tick, total / tick

    def _status(self) -> dict:
        out = {}
        try:
            with open("/proc/self/status", encoding="ascii") as fh:
                for line in fh:
                    key, _, value = line.partition(":")
                    out[key] = value.split()
        except OSError:
            pass
        return out

    def memory(self) -> dict:
        status = self._status()
        kb = lambda key: int(status.get(key, ["0"])[0]) * 1024
        total = 0
        try:
            with open("/proc/meminfo", encoding="ascii") as fh:
                total = int(fh.readline().split()[1]) * 1024
        except OSError:
            pass
        return {"in_use": kb("VmRSS"), "private": kb("RssAnon"), "peak": kb("VmHWM"), "pc_total": total}

    def handles(self) -> int:
        try:
            return len(os.listdir("/proc/self/fd"))
        except OSError:
            return 0

    def threads(self) -> int:
        try:
            return int(self._status().get("Threads", ["0"])[0])
        except ValueError:
            return threading.active_count()


MIN_GAP_S = 0.25            # processor use is measured over at least this long


class ProcessStats:
    """Call sample() now and then (once a second suits): each call gives the processor
    use since the last call."""

    def __init__(self):
        self.os = _Windows() if sys.platform == "win32" else _Proc()
        self.cores = os.cpu_count() or 1
        self.started = time.monotonic()
        self._last = None
        self._cpu = {}

    def sample(self, threads: bool = True) -> dict:
        now = time.monotonic()
        try:
            cpu = self.os.process_cpu()
        except Exception:
            cpu = time.process_time()
        try:
            system = self.os.system_cpu()
        except Exception:
            system = None
        out = {"cores": self.cores, "uptime_s": now - self.started}
        try:
            out.update(self.os.memory())
        except Exception:
            out.update({"in_use": 0, "private": 0, "peak": 0, "pc_total": 0})
        try:
            out["handles"] = self.os.handles()
            out["threads"] = self.os.threads() if threads else 0
        except Exception:
            out["handles"], out["threads"] = 0, threading.active_count()
        if self._last is not None and now - self._last[0] < MIN_GAP_S:
            out.update(self._cpu)       # too soon to measure: the clocks tick too coarsely
            return out
        if self._last is not None:
            then, then_cpu, then_system = self._last
            elapsed = max(1e-6, now - then)
            core = min(100.0 * self.cores, 100.0 * max(0.0, cpu - then_cpu) / elapsed)
            self._cpu = {"cpu_core": core,                      # of one processor core
                         "cpu_pc": core / self.cores}           # of the whole PC
            if system is not None and then_system is not None:
                busy = system[0] - then_system[0]
                total = system[1] - then_system[1]
                self._cpu["pc_busy"] = min(100.0, 100.0 * busy / total) if total > 0 else 0.0
            out.update(self._cpu)
        self._last = (now, cpu, system)
        return out
