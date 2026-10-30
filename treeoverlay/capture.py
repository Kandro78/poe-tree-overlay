"""Screen capture of the game window.

Desktop Duplication (via dxcam) takes ~2 ms per frame, GDI (via mss) ~19 ms at
2560x1440; both leave out windows marked WDA_EXCLUDEFROMCAPTURE, so the overlay
never sees itself. dxcam is used when it is installed and works, mss otherwise.
"""
import time
import traceback
import warnings

import mss
import numpy as np

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # comtypes warns about Python 3.15 enums
        import dxcam
except Exception:                            # not installed or no Desktop Duplication
    dxcam = None


class Capture:
    def __init__(self):
        self.mss = mss.MSS()
        self.use_dx = dxcam is not None
        self.cams = None      # [(camera, (left, top, right, bottom)), ...] per screen
        self.last = None
        self.backend = "dxcam" if self.use_dx else "mss"

    def _outputs(self):
        if self.cams is None:
            self.cams = []
            self._enumerated = time.monotonic()
            for idx in range(16):
                try:
                    cam = dxcam.create(output_idx=idx, output_color="BGR")
                except Exception:
                    break
                c = cam._output.desc.DesktopCoordinates
                self.cams.append((cam, (c.left, c.top, c.right, c.bottom)))
        return self.cams

    def _release_dx(self):
        for cam, _ in self.cams or []:
            try:
                cam.release()
            except Exception:
                pass
        self.cams = None

    def _grab_dx(self, rect):
        left, top, w, h = rect
        cx, cy = left + w // 2, top + h // 2
        for _ in range(2):
            for cam, (ol, ot, orr, ob) in self._outputs():
                if ol <= cx < orr and ot <= cy < ob:
                    region = (max(left, ol) - ol, max(top, ot) - ot, min(left + w, orr) - ol, min(top + h, ob) - ot)
                    if region[2] - region[0] != w or region[3] - region[1] != h:
                        return None, False     # window spans screens: let mss handle it
                    return cam.grab(region=region), True
            # no known screen holds the window: the display layout may have
            # changed (monitor plugged in or rearranged) - look again, rarely
            if time.monotonic() - self._enumerated < 5.0:
                break
            self._release_dx()
        return None, False

    def grab(self, rect):
        """(frame, new): BGR frame of rect (left, top, width, height) in physical
        pixels. new is False when the screen hasn't been redrawn since the last
        grab; the frame is then the previous one, taken earlier."""
        left, top, w, h = rect
        if self.use_dx:
            try:
                frame, handled = self._grab_dx(rect)
                if handled:
                    if frame is None:
                        # no new desktop frame since the last grab
                        if self.last is not None and self.last.shape[:2] == (h, w):
                            return self.last, False
                    else:
                        self.last = frame
                        return frame, True
            except Exception:
                traceback.print_exc()
                self.use_dx = False
                self.backend = "mss"
        shot = self.mss.grab({"left": left, "top": top, "width": w, "height": h})
        self.last = np.ascontiguousarray(np.asarray(shot)[:, :, :3])
        return self.last, True

    def close(self):
        self._release_dx()
        self.mss.close()
