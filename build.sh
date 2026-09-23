#!/bin/sh
# ZeroCam build script.
#
# Turns a freshly flashed Raspberry Pi OS Lite (Bullseye) card into a
# working ZeroCam. Run it once, on the Pi, with a working internet
# connection:
#
#     sudo sh /boot/build.sh
#
# It enables SPI and the legacy camera stack, installs the handful of
# Python packages the camera needs, removes the kernels and device trees
# for Pi models this cannot run on, installs the app and its startup
# service, and leaves you ready to reboot into a camera.
#
# This script makes no network connection other than to Raspberry Pi's
# own package servers, and installs nothing that is not listed in
# PACKAGES below.
#
# MIT licensed. https://github.com/z-l-o-k/ZeroCam

set -e

BOOT=/boot
if [ -d /boot/firmware ]; then
    BOOT=/boot/firmware
fi

PACKAGES="python3-picamera python3-numpy python3-pil python3-spidev python3-rpi.gpio fonts-dejavu-core"

echo "=============================================="
echo " ZeroCam build"
echo " boot partition: $BOOT"
echo "=============================================="
echo

if [ "$(id -u)" != "0" ]; then
    echo "This must be run with sudo:  sudo sh $BOOT/build.sh"
    exit 1
fi

if ! grep -qi bullseye /etc/os-release; then
    echo "WARNING: this is not Bullseye."
    echo "ZeroCam needs the legacy camera stack, which Bookworm removed."
    echo "See the readme for which image to flash."
    exit 1
fi

if [ ! -f "$BOOT/zerocam.py" ]; then
    echo "ERROR: $BOOT/zerocam.py is missing. Copy it onto the card first."
    exit 1
fi

# ---------------------------------------------------------------
echo "[1/7] Enabling SPI and the legacy camera stack"
# ---------------------------------------------------------------
CFG="$BOOT/config.txt"
cp "$CFG" "$CFG.zerocam-backup" 2>/dev/null || true

grep -q "^dtparam=spi=on" "$CFG" || {
    echo "dtparam=spi=on" >> "$CFG"
    echo "      added dtparam=spi=on"
}

# The legacy camera stack and libcamera autodetect cannot coexist.
if grep -q "^camera_auto_detect=1" "$CFG"; then
    sed -i 's/^camera_auto_detect=1/#camera_auto_detect=1/' "$CFG"
    echo "      disabled camera_auto_detect"
fi

grep -q "^start_x=1" "$CFG" || {
    echo "start_x=1" >> "$CFG"
    echo "      added start_x=1"
}

grep -q "^gpu_mem=128" "$CFG" || {
    echo "gpu_mem=128" >> "$CFG"
    echo "      added gpu_mem=128"
}

# ---------------------------------------------------------------
echo "[2/7] Refreshing the package list (needs internet)"
# ---------------------------------------------------------------
apt-get update

# ---------------------------------------------------------------
echo "[3/7] Installing packages"
# ---------------------------------------------------------------
DEBIAN_FRONTEND=noninteractive apt-get install -y $PACKAGES

# ---------------------------------------------------------------
echo "[4/7] Removing kernels for Pi models this cannot run on"
# ---------------------------------------------------------------
# ZeroCam targets the Pi Zero and Zero 2 W, which use kernel.img (armv6)
# and kernel7.img (armv7) respectively. The Pi 4 and Pi 5 kernels and
# their initramfs images are dead weight on a partition that also has to
# hold your photographs. How much this frees depends on the image; the
# script reports the real figure below rather than promising one.
BEFORE=$(df -k "$BOOT" | awk 'NR==2 {print $4}')
for f in kernel7l.img kernel8.img initramfs7l initramfs8; do
    rm -f "$BOOT/$f" && echo "      removed $f"
done
# Device trees for boards that cannot boot this image.
rm -f "$BOOT"/bcm2711-*.dtb "$BOOT"/bcm2712*.dtb 2>/dev/null || true
echo "      removed Pi 4 and Pi 5 device trees"
AFTER=$(df -k "$BOOT" | awk 'NR==2 {print $4}')
echo "      freed $(( (AFTER - BEFORE) / 1024 )) MB for photographs"

# ---------------------------------------------------------------
echo "[5/7] Installing the camera app"
# ---------------------------------------------------------------
mkdir -p /opt/zerocam
cp "$BOOT/zerocam.py" /opt/zerocam/zerocam.py
chmod +x /opt/zerocam/zerocam.py
mkdir -p "$BOOT/photos"
echo "      app at /opt/zerocam/zerocam.py"
echo "      photos will be written to $BOOT/photos"

# ---------------------------------------------------------------
echo "[6/7] Installing the startup service"
# ---------------------------------------------------------------
cat > /etc/systemd/system/zerocam.service <<'UNIT'
[Unit]
Description=ZeroCam low-fi camera
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/zerocam/zerocam.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable zerocam
echo "      zerocam.service enabled, starts at power on"

# ---------------------------------------------------------------
echo "[7/7] Tidying up"
# ---------------------------------------------------------------
apt-get clean
rm -rf /var/lib/apt/lists/*
echo "      package cache cleared"

echo
echo "=============================================="
echo " Built. Reboot to start the camera:"
echo
echo "     sudo reboot"
echo
echo " Controls:"
echo "     joystick press        take a photo"
echo "     joystick left/right   change effect"
echo "     joystick up/down      change white balance"
echo "     KEY2                  status"
echo "     KEY3 held 2 seconds   shut down safely"
echo
echo " If you are building a release image, run clean.sh"
echo " next. Do not skip it: it removes your account,"
echo " your ssh keys and your photographs."
echo "=============================================="
