#!/usr/bin/env python3
"""
ZeroCam: a deliberately low-fi camera for SeedSigner hardware.

Runs on its own microSD card. Your SeedSigner card is never touched, and
nothing is written to the Pi itself, which has no writable storage on the
board at all.

Hardware assumed:
  Raspberry Pi Zero 1.3 or Zero 2 W
  Waveshare 1.3 inch LCD HAT, ST7789 controller, 240x240
  Raspberry Pi camera module on the CSI ribbon
  Five-way joystick and three keys on the HAT

Controls:
  joystick press          take a photo
  joystick left / right   previous / next effect
  joystick up / down      cycle white balance
  KEY1                    next effect
  KEY2                    status: effect, white balance, count, free space
  KEY3 held 2 seconds     clean shutdown, then it is safe to unplug

Photos are written to the card's FAT partition as IMG_0001.jpg and so on.
Put the card in any computer and they are simply there. There is no clock
on this board, so numbering is sequential rather than dated.

If anything goes wrong, the error is drawn on the screen and written to
zerocam-error.txt on the same FAT partition, readable on any computer.

Written by Claude (Anthropic) directed by ZLOK. Read it before you run it.
MIT licensed. https://github.com/z-l-o-k/ZeroCam
"""

import os
import sys
import glob
import time
import traceback
import warnings

# picamera is chatty about harmless resolution rounding. We handle it.
warnings.filterwarnings("ignore", module="picamera")

# ----------------------------------------------------------------------
# Configuration. These are the things most likely to need adjusting.
# ----------------------------------------------------------------------

WIDTH = 240
HEIGHT = 240

# The FAT partition, visible to any computer. Bullseye mounts it at /boot.
BOOT_DIR = "/boot/firmware" if os.path.isdir("/boot/firmware") else "/boot"
PHOTO_DIR = os.path.join(BOOT_DIR, "photos")
ERROR_FILE = os.path.join(BOOT_DIR, "zerocam-error.txt")

# Waveshare 1.3 inch LCD HAT pins, BCM numbering.
PIN_DC = 25
PIN_RST = 27
PIN_BL = 24

# SeedSigner button layout.
BUTTONS = {
    "up": 6,
    "down": 19,
    "left": 5,
    "right": 26,
    "press": 13,
    "key1": 21,
    "key2": 20,
    "key3": 16,
}

SPI_SPEED_HZ = 40000000

# Display orientation. 0x70 is correct for this screen: it puts the text
# the right way up. If text appears rotated or mirrored on your hardware,
# try 0x00, 0xC0, 0xA0 or 0x60 instead.
MADCTL = 0x70

# The camera module is mounted at 90 degrees to the screen on this board,
# so the camera image needs rotating even though the text does not. The
# camera hardware does this, so it is free, and it applies to saved photos
# as well as to the preview. Use 270 if yours comes out the other way.
CAMERA_ROTATION = 90

# The ST7789 on this HAT needs colour inversion enabled.
INVERT_COLOURS = True

# 1296x972 is the sensor's binned mode: full field of view, quick on a
# Zero, and far more detail than a 240x240 screen can show.
CAPTURE_RESOLUTION = (1296, 972)

JPEG_QUALITY = 88

# Warn when the card has less than this much room left, in megabytes.
LOW_SPACE_MB = 20

# Effects rendered by the camera hardware, so they cost no CPU at all.
EFFECTS = [
    "none", "film", "sketch", "cartoon", "colorswap", "posterise",
    "solarize", "washedout", "emboss", "negative", "gpen", "pastel",
    "watercolor", "hatch", "oilpaint", "blur",
]

WB_MODES = [
    "auto", "sunlight", "cloudy", "shade", "tungsten",
    "fluorescent", "incandescent", "flash", "horizon",
]

SHUTDOWN_HOLD_SECONDS = 2.0


# ----------------------------------------------------------------------
# Imports that depend on installed packages.
# ----------------------------------------------------------------------

try:
    import numpy as np
    import spidev
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    sys.stderr.write(
        "ZeroCam: a required package is missing: %s\n"
        "Run build.sh again with a working internet connection.\n" % exc
    )
    raise


def load_font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


FONT_BIG = load_font(30)
FONT_MED = load_font(18)
FONT_SMALL = load_font(12)
FONT_TINY = load_font(10)


# ----------------------------------------------------------------------
# Display
# ----------------------------------------------------------------------

class Display:
    """Minimal ST7789 driver over SPI. No external display library."""

    def __init__(self):
        GPIO.setup(PIN_DC, GPIO.OUT)
        GPIO.setup(PIN_RST, GPIO.OUT)
        GPIO.setup(PIN_BL, GPIO.OUT)
        GPIO.output(PIN_BL, GPIO.HIGH)

        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = SPI_SPEED_HZ
        self.spi.mode = 0

        self._reset()
        self._init_panel()

    def _reset(self):
        GPIO.output(PIN_RST, GPIO.HIGH)
        time.sleep(0.01)
        GPIO.output(PIN_RST, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(PIN_RST, GPIO.HIGH)
        time.sleep(0.15)

    def _cmd(self, value):
        GPIO.output(PIN_DC, GPIO.LOW)
        self.spi.writebytes([value])

    def _data(self, values):
        if isinstance(values, int):
            values = [values]
        GPIO.output(PIN_DC, GPIO.HIGH)
        self.spi.writebytes(list(values))

    def _write_pixels(self, buf):
        GPIO.output(PIN_DC, GPIO.HIGH)
        step = 4096
        for i in range(0, len(buf), step):
            chunk = buf[i:i + step]
            try:
                self.spi.writebytes2(chunk)
            except AttributeError:
                self.spi.writebytes(list(chunk))

    def _init_panel(self):
        self._cmd(0x36); self._data(MADCTL)
        self._cmd(0x3A); self._data(0x05)
        self._cmd(0xB2); self._data([0x0C, 0x0C, 0x00, 0x33, 0x33])
        self._cmd(0xB7); self._data(0x35)
        self._cmd(0xBB); self._data(0x19)
        self._cmd(0xC0); self._data(0x2C)
        self._cmd(0xC2); self._data(0x01)
        self._cmd(0xC3); self._data(0x12)
        self._cmd(0xC4); self._data(0x20)
        self._cmd(0xC6); self._data(0x0F)
        self._cmd(0xD0); self._data([0xA4, 0xA1])
        self._cmd(0xE0); self._data([0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B,
                                     0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B,
                                     0x1F, 0x23])
        self._cmd(0xE1); self._data([0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C,
                                     0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F,
                                     0x20, 0x23])
        if INVERT_COLOURS:
            self._cmd(0x21)
        self._cmd(0x11)
        time.sleep(0.12)
        self._cmd(0x29)

    def _set_window(self):
        self._cmd(0x2A); self._data([0x00, 0x00, 0x00, WIDTH - 1])
        self._cmd(0x2B); self._data([0x00, 0x00, 0x00, HEIGHT - 1])
        self._cmd(0x2C)

    def show_array(self, arr):
        """arr is a uint8 numpy array shaped (240, 240, 3)."""
        r = (arr[:, :, 0].astype(np.uint16) & 0xF8) << 8
        g = (arr[:, :, 1].astype(np.uint16) & 0xFC) << 3
        b = (arr[:, :, 2].astype(np.uint16) >> 3)
        buf = (r | g | b).astype(">u2").tobytes()
        self._set_window()
        self._write_pixels(buf)

    def show_image(self, img):
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT))
        self.show_array(np.asarray(img, dtype=np.uint8))

    def blank(self):
        self.show_array(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))

    def backlight(self, on):
        GPIO.output(PIN_BL, GPIO.HIGH if on else GPIO.LOW)

    def close(self):
        try:
            self.blank()
            self.backlight(False)
            self.spi.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Screens
# ----------------------------------------------------------------------

def new_canvas(colour=(0, 0, 0)):
    img = Image.new("RGB", (WIDTH, HEIGHT), colour)
    return img, ImageDraw.Draw(img)


def centred(draw, y, text, font, fill=(255, 255, 255)):
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        w = right - left
    except AttributeError:
        w, _ = draw.textsize(text, font=font)
    draw.text(((WIDTH - w) // 2, y), text, font=font, fill=fill)


def splash_screen(display):
    img, draw = new_canvas((10, 10, 14))
    centred(draw, 78, "ZEROCAM", FONT_BIG, (255, 170, 40))
    centred(draw, 118, "low-fi camera", FONT_SMALL, (150, 150, 150))
    centred(draw, 200, "warming up", FONT_TINY, (90, 90, 90))
    display.show_image(img)


def message_screen(display, lines, colour=(0, 0, 0), text_colour=(255, 255, 255)):
    img, draw = new_canvas(colour)
    y = (HEIGHT - (len(lines) * 26)) // 2
    for line in lines:
        centred(draw, y, line, FONT_MED, text_colour)
        y += 26
    display.show_image(img)


def status_screen(display, effect, wb, count, free_mb):
    img, draw = new_canvas((8, 8, 10))
    centred(draw, 16, "STATUS", FONT_MED, (255, 170, 40))
    rows = [
        ("effect", effect),
        ("white bal", wb),
        ("photos", str(count)),
        ("card free", "%d MB" % free_mb if free_mb >= 0 else "unknown"),
    ]
    y = 62
    for label, value in rows:
        colour = (255, 255, 255)
        if label == "card free" and 0 <= free_mb < LOW_SPACE_MB:
            colour = (255, 110, 110)
        draw.text((22, y), label, font=FONT_SMALL, fill=(130, 130, 130))
        draw.text((130, y), value, font=FONT_SMALL, fill=colour)
        y += 30
    centred(draw, 206, "hold KEY3 to shut down", FONT_TINY, (90, 90, 90))
    display.show_image(img)


def error_screen(display, text):
    img, draw = new_canvas((40, 0, 0))
    centred(draw, 10, "ERROR", FONT_MED, (255, 120, 120))
    y = 42
    for line in wrap_text(text, 34)[:14]:
        draw.text((6, y), line, font=FONT_TINY, fill=(255, 220, 220))
        y += 12
    centred(draw, 214, "see zerocam-error.txt on the card", FONT_TINY,
            (200, 150, 150))
    display.show_image(img)


def wrap_text(text, width):
    out = []
    for raw in text.splitlines():
        while len(raw) > width:
            out.append(raw[:width])
            raw = raw[width:]
        out.append(raw)
    return out


# ----------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------

class Buttons:
    def __init__(self):
        for pin in BUTTONS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.previous = {name: 1 for name in BUTTONS}
        self.pressed_at = {name: None for name in BUTTONS}

    def poll(self):
        """Return the names of buttons that have just been pressed."""
        events = []
        now = time.time()
        for name, pin in BUTTONS.items():
            value = GPIO.input(pin)
            if value == 0 and self.previous[name] == 1:
                events.append(name)
                self.pressed_at[name] = now
            elif value == 1:
                self.pressed_at[name] = None
            self.previous[name] = value
        return events

    def held_for(self, name, seconds):
        started = self.pressed_at[name]
        return started is not None and (time.time() - started) >= seconds


# ----------------------------------------------------------------------
# Photos
# ----------------------------------------------------------------------

def photo_count():
    return len(glob.glob(os.path.join(PHOTO_DIR, "IMG_*.jpg")))


def next_photo_path():
    highest = 0
    for path in glob.glob(os.path.join(PHOTO_DIR, "IMG_*.jpg")):
        name = os.path.basename(path)
        try:
            highest = max(highest, int(name[4:8]))
        except ValueError:
            continue
    return os.path.join(PHOTO_DIR, "IMG_%04d.jpg" % (highest + 1))


def free_megabytes(path):
    try:
        st = os.statvfs(path)
        return int(st.f_bavail * st.f_frsize / (1024 * 1024))
    except Exception:
        return -1


def take_photo(camera, display):
    free = free_megabytes(PHOTO_DIR)
    if 0 <= free < 3:
        message_screen(display, ["card full", "", "copy photos off", "and delete them"],
                       (40, 0, 0), (255, 200, 200))
        time.sleep(3.0)
        return None

    path = next_photo_path()
    message_screen(display, ["taking photo"], (0, 0, 0), (255, 170, 40))
    camera.capture(path, format="jpeg", quality=JPEG_QUALITY)
    # Force it onto the card immediately, so unplugging cannot lose it.
    os.sync()

    lines = ["saved", os.path.basename(path)]
    free = free_megabytes(PHOTO_DIR)
    if 0 <= free < LOW_SPACE_MB:
        lines.append("%d MB left" % free)
    message_screen(display, lines, (0, 30, 0))
    time.sleep(0.7)
    return path


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def run(display, buttons):
    import picamera
    from picamera.array import PiRGBArray

    os.makedirs(PHOTO_DIR, exist_ok=True)

    effect_index = 0
    wb_index = 0

    with picamera.PiCamera() as camera:
        camera.resolution = CAPTURE_RESOLUTION
        camera.framerate = 15
        camera.image_effect = EFFECTS[effect_index]
        camera.awb_mode = WB_MODES[wb_index]
        camera.rotation = CAMERA_ROTATION
        time.sleep(2.0)  # let exposure and white balance settle

        raw = PiRGBArray(camera, size=(WIDTH, HEIGHT))
        stream = camera.capture_continuous(
            raw, format="rgb", use_video_port=True, resize=(WIDTH, HEIGHT)
        )

        for _ in stream:
            display.show_array(raw.array)
            raw.truncate(0)

            events = buttons.poll()

            if buttons.held_for("key3", SHUTDOWN_HOLD_SECONDS):
                message_screen(display,
                               ["shutting down", "", "wait for the", "screen to clear"],
                               (0, 0, 40))
                os.sync()
                time.sleep(1.0)
                display.close()
                os.system("poweroff")
                return

            if not events:
                continue

            if "press" in events:
                take_photo(camera, display)

            elif "key1" in events or "right" in events:
                effect_index = (effect_index + 1) % len(EFFECTS)
                camera.image_effect = EFFECTS[effect_index]
                message_screen(display, [EFFECTS[effect_index]], (0, 0, 0),
                               (255, 170, 40))
                time.sleep(0.4)

            elif "left" in events:
                effect_index = (effect_index - 1) % len(EFFECTS)
                camera.image_effect = EFFECTS[effect_index]
                message_screen(display, [EFFECTS[effect_index]], (0, 0, 0),
                               (255, 170, 40))
                time.sleep(0.4)

            elif "up" in events or "down" in events:
                step = 1 if "up" in events else -1
                wb_index = (wb_index + step) % len(WB_MODES)
                camera.awb_mode = WB_MODES[wb_index]
                message_screen(display, ["white balance", WB_MODES[wb_index]],
                               (0, 0, 0), (120, 200, 255))
                time.sleep(0.4)

            elif "key2" in events:
                status_screen(display, EFFECTS[effect_index],
                              WB_MODES[wb_index], photo_count(),
                              free_megabytes(PHOTO_DIR))
                time.sleep(2.0)


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    display = None
    try:
        display = Display()
        splash_screen(display)
        buttons = Buttons()
        time.sleep(1.0)
        run(display, buttons)

    except KeyboardInterrupt:
        # Ctrl-C during testing. Exit quietly rather than unwinding noisily.
        sys.stderr.write("\nZeroCam stopped.\n")

    except Exception:
        detail = traceback.format_exc()
        try:
            with open(ERROR_FILE, "w") as handle:
                handle.write(detail)
            os.sync()
        except Exception:
            pass
        sys.stderr.write(detail)
        if display is not None:
            try:
                error_screen(display, detail.strip().splitlines()[-1])
            except Exception:
                pass
        time.sleep(30)

    finally:
        if display is not None:
            display.close()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
