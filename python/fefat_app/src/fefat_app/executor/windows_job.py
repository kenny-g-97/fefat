"""A Windows Job Object over a runner (step 4.5, `01-architecture.md` section 6), through `ctypes`
alone, without pywin32 (the step's amendment, D-83): the runner starts suspended and joins a job
whose processes may commit `memory_bytes` together, past which an allocation fails, as Python's
`MemoryError`, before it runs a line; every process it starts joins the job too, and closing the
job's handle, at the end of an execution, at its timeout, or at the end of the process holding
it, ends them all. Imported on Windows alone."""

import ctypes
import sys
from ctypes import wintypes

assert sys.platform == "win32", f"Expected Windows for a Job Object, got {sys.platform}."

EXTENDED_LIMIT_INFORMATION = 9
"""`JobObjectExtendedLimitInformation`, the class of limits `SetInformationJobObject` sets."""
LIMIT_JOB_MEMORY = 0x00000200
LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
KERNEL32.SetInformationJobObject.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
KERNEL32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
KERNEL32.CloseHandle.restype = wintypes.BOOL


class IoCounters(ctypes.Structure):
    """`IO_COUNTERS`, which the extended limits hold and the job leaves at zero."""

    _fields_ = tuple(
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    )


class BasicLimitInformation(ctypes.Structure):
    """`JOBOBJECT_BASIC_LIMIT_INFORMATION`, whose flags name the limits set."""

    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    )


class ExtendedLimitInformation(ctypes.Structure):
    """`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, which holds the job's limit of memory."""

    _fields_ = (
        ("BasicLimitInformation", BasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class JobObject:
    """A Job Object whose processes may commit `memory_bytes` together, and which ends them all
    when its handle closes (module docstring)."""

    def __init__(self, memory_bytes: int) -> None:
        handle = KERNEL32.CreateJobObjectW(None, None)
        if not handle:
            raise _refused("a Job Object for the runner")
        self._handle: int | None = handle
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = LIMIT_JOB_MEMORY | LIMIT_KILL_ON_JOB_CLOSE
        limits.JobMemoryLimit = memory_bytes
        size = ctypes.sizeof(limits)
        if not KERNEL32.SetInformationJobObject(
            handle, EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), size
        ):
            refused = _refused(f"a Job Object limited to {memory_bytes} bytes")
            self.close()
            raise refused

    @classmethod
    def holding(cls, pid: int, memory_bytes: int) -> "JobObject":
        """A job limited to `memory_bytes` that the process `pid`, started suspended, joined."""
        job = cls(memory_bytes)
        try:
            job.assign(pid)
        except OSError:
            job.close()
            raise
        return job

    def assign(self, pid: int) -> None:
        """Put the process `pid` in the job, with every process it starts from then on."""
        process = KERNEL32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            raise _refused(f"the runner {pid} opened to join its Job Object")
        try:
            if not KERNEL32.AssignProcessToJobObject(self._handle, process):
                raise _refused(f"the runner {pid} in its Job Object")
        finally:
            KERNEL32.CloseHandle(process)

    def close(self) -> None:
        """Close the job's handle, which ends every process still in it; again, nothing."""
        handle, self._handle = self._handle, None
        if handle is not None:
            KERNEL32.CloseHandle(handle)


def _refused(expected: str) -> OSError:
    """The error of the call of the Windows API that just failed, read before any other call."""
    error = ctypes.get_last_error()
    return OSError(
        error, f"Expected {expected}, got Windows error {error}: {ctypes.FormatError(error)}"
    )
