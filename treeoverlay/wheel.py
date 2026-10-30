"""Mouse wheel notches, read with Raw Input on a thread of its own.

Raw Input hands us a copy of each mouse event. A low-level hook would make
every mouse event wait for Python, and a busy interpreter would then make the
game's mouse lag; Raw Input can't. Nothing is ever sent to the game.

PoE zooms the passive tree one step per wheel notch around the cursor, so a
notch tells where the tree is going before the game has drawn it. The zoom
ladder and how many steps a notch moves are learned from what the tracker
then confirms (see ZoomPredictor).
"""
import ctypes
import ctypes.wintypes as wt
import threading
import time
from collections import deque

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RI_MOUSE_WHEEL = 0x0400
HWND_MESSAGE = wt.HWND(-3)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    # the button flags/data sit in a union aligned to 4 bytes, hence the padding
    _fields_ = [("usFlags", wt.USHORT), ("_pad", wt.USHORT), ("usButtonFlags", wt.USHORT),
                ("usButtonData", ctypes.c_short), ("ulRawButtons", wt.ULONG), ("lLastX", wt.LONG),
                ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class WheelReader:
    """Collects (time, notches) of every wheel turn; notches > 0 is away from the user."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.events = deque(maxlen=256)
        self.ok = False
        self._thread = threading.Thread(target=self._run, name="wheel", daemon=True)
        self._thread.start()

    def take(self):
        """Wheel turns since the last call, oldest first."""
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def _run(self):
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT), wt.UINT]
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.RegisterRawInputDevices.argtypes = [ctypes.c_void_p, wt.UINT, wt.UINT]
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        buf = RAWINPUT()
        size = wt.UINT()
        header = ctypes.sizeof(RAWINPUTHEADER)

        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                size.value = ctypes.sizeof(buf)
                if (user32.GetRawInputData(lparam, RID_INPUT, ctypes.byref(buf), ctypes.byref(size), header) > 0
                        and buf.header.dwType == RIM_TYPEMOUSE and buf.mouse.usButtonFlags & RI_MOUSE_WHEEL):
                    self.events.append((self.clock(), buf.mouse.usButtonData / 120))
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = WNDPROC(proc)   # kept alive as long as the window
        cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=kernel32.GetModuleHandleW(None),
                        lpszClassName="PoETreeOverlayWheel")
        user32.RegisterClassW(ctypes.byref(cls))
        hwnd = user32.CreateWindowExW(0, cls.lpszClassName, None, 0, 0, 0, 0, 0, HWND_MESSAGE, None,
                                      cls.hInstance, None)
        dev = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)   # generic desktop / mouse, also when not in front
        if not hwnd or not user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(dev)):
            return
        self.ok = True
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


class ZoomPredictor:
    """Where the tree goes after wheel notches, from the zoom levels the game
    uses (PoE at 1440p: 0.144 + 0.09 n up to 0.684) and how many of them one
    notch moves. Both start from what was seen in game and follow what the
    tracker confirms afterwards."""
    LADDER_1440 = tuple(round(0.144 + 0.09 * n, 3) for n in range(7))

    def __init__(self, height=1440):
        self.ladder = [z * height / 1440 for z in self.LADDER_1440]
        self.per_notch = 1.0      # ladder steps per notch away from the user (negative: the other way)
        self.samples = deque(maxlen=12)

    def set_height(self, height):
        if abs(self.ladder[0] / (0.144 * height / 1440) - 1) > 1e-6:
            self.ladder = [z * height / 1440 for z in self.LADDER_1440]

    def index(self, scale):
        """The ladder step nearest to a scale (fractional when between two)."""
        lad = self.ladder
        if scale <= lad[0]:
            return 0.0
        if scale >= lad[-1]:
            return float(len(lad) - 1)
        for i in range(len(lad) - 1):
            if scale <= lad[i + 1]:
                return i + (scale - lad[i]) / (lad[i + 1] - lad[i])
        return float(len(lad) - 1)

    def target(self, scale, notches):
        """The scale the game settles on after `notches` from `scale`."""
        i = round(self.index(scale) + notches * self.per_notch)
        return self.ladder[max(0, min(len(self.ladder) - 1, i))]

    @staticmethod
    def zoomed(t, scale, anchor, cls):
        """Transform t zoomed to `scale` around the screen point `anchor`."""
        k = scale / t.scale
        ax, ay = anchor
        return cls(scale, ax - (ax - t.tx) * k, ay - (ay - t.ty) * k)

    def learn(self, start_scale, notches, end_scale):
        """A wheel turn the tracker has confirmed: how many steps did it go?
        A turn that ended at either end of the ladder may have been cut short
        there, so it says nothing about that."""
        if not notches:
            return
        i0, i1 = self.index(start_scale), self.index(end_scale)
        if i1 <= 0.01 or i1 >= len(self.ladder) - 1.01:
            # the end of the ladder clips the turn; only the direction can be read
            if i1 != i0 and (i1 - i0) * notches * self.per_notch < 0:
                self.per_notch = -self.per_notch
            return
        steps = i1 - i0
        if abs(steps) < 0.5:
            return
        self.samples.append(steps / notches)
        ratios = sorted(self.samples)
        self.per_notch = ratios[len(ratios) // 2]
