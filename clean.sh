#!/bin/sh
# ZeroCam release preparation.
#
# Run this on the Pi, ONLY when preparing an image for other people:
#
#     sudo sh /boot/clean.sh
#
# It removes everything personal from the card, sets up the default
# account, switches ssh off, blanks the unused space so the image
# compresses well, prints the exact command for copying the card, and
# powers the Pi off.
#
# THIS IS DESTRUCTIVE. It deletes your user account, your photographs,
# your ssh keys and your shell history. Do not run it on a camera you
# are still using.
#
# MIT licensed. https://github.com/z-l-o-k/ZeroCam

set -e

BOOT=/boot
if [ -d /boot/firmware ]; then
    BOOT=/boot/firmware
fi

DEFAULT_USER=zerocam
DEFAULT_PASS=zerocam

echo "=============================================="
echo " ZeroCam release preparation"
echo "=============================================="
echo

if [ "$(id -u)" != "0" ]; then
    echo "This must be run with sudo:  sudo sh $BOOT/clean.sh"
    exit 1
fi

printf "This deletes your account, photos and keys. Type YES to continue: "
read CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Cancelled. Nothing was changed."
    exit 1
fi
echo

# ---------------------------------------------------------------
echo "[1/9] Removing photographs and working files"
# ---------------------------------------------------------------
rm -f "$BOOT"/photos/*.jpg
rm -f "$BOOT"/zerocam-error.txt
rm -f "$BOOT"/config.txt.zerocam-backup
rm -rf "$BOOT"/debs
rm -rf /home/*/Pictures 2>/dev/null || true
echo "      done"

# ---------------------------------------------------------------
echo "[2/9] Switching ssh off and removing host keys"
# ---------------------------------------------------------------
systemctl disable ssh 2>/dev/null || true
rm -f /etc/ssh/ssh_host_*
rm -f "$BOOT"/ssh "$BOOT"/ssh.txt
# Raspberry Pi OS regenerates host keys at boot when they are missing.
systemctl enable regenerate_ssh_host_keys 2>/dev/null || true
echo "      ssh disabled, host keys removed"
echo "      users can re-enable it with a file named ssh on the card"

# ---------------------------------------------------------------
echo "[3/9] Creating the default account"
# ---------------------------------------------------------------
if ! id "$DEFAULT_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$DEFAULT_USER"
fi
echo "$DEFAULT_USER:$DEFAULT_PASS" | chpasswd
for g in sudo adm dialout cdrom audio video plugdev games users input netdev gpio i2c spi; do
    getent group "$g" >/dev/null 2>&1 && adduser "$DEFAULT_USER" "$g" >/dev/null 2>&1 || true
done
echo "$DEFAULT_USER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/010_zerocam-nopasswd
chmod 0440 /etc/sudoers.d/010_zerocam-nopasswd
rm -f /etc/sudoers.d/010_pi-nopasswd
echo "      user '$DEFAULT_USER', password '$DEFAULT_PASS'"

# ---------------------------------------------------------------
echo "[4/9] Removing personal accounts"
# ---------------------------------------------------------------
for u in $(awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd); do
    [ "$u" = "$DEFAULT_USER" ] && continue
    userdel -r -f "$u" 2>/dev/null || true
    echo "      removed $u"
done
rm -f "$BOOT"/userconf.txt "$BOOT"/userconf

# ---------------------------------------------------------------
echo "[5/9] Clearing identity and history"
# ---------------------------------------------------------------
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id
echo zerocam > /etc/hostname
sed -i 's/127\.0\.1\.1.*/127.0.1.1\tzerocam/' /etc/hosts
rm -f /root/.bash_history /home/*/.bash_history
rm -f /root/.python_history /home/*/.python_history
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
rm -f /var/lib/dhcpcd/*.lease /var/lib/dhcp/* 2>/dev/null || true
rm -f /var/lib/systemd/random-seed
echo "      machine id, hostname, history and network state cleared"

# ---------------------------------------------------------------
echo "[6/9] Clearing logs"
# ---------------------------------------------------------------
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-time=1s >/dev/null 2>&1 || true
find /var/log -type f -exec truncate -s 0 {} \; 2>/dev/null || true
rm -rf /var/log/journal/* 2>/dev/null || true
apt-get clean
rm -rf /var/lib/apt/lists/*
echo "      done"

# ---------------------------------------------------------------
echo "[7/9] Blanking unused space (this takes a few minutes)"
# ---------------------------------------------------------------
# Deleted files leave their contents on the card. Writing zeros over the
# free space means the finished image compresses to a fraction of its
# size, and that nothing of yours survives in the gaps.
dd if=/dev/zero of=/zero.fill bs=1M 2>/dev/null || true
rm -f /zero.fill
sync
dd if=/dev/zero of="$BOOT/zero.fill" bs=1M 2>/dev/null || true
rm -f "$BOOT/zero.fill"
sync
echo "      done"

# ---------------------------------------------------------------
echo "[8/9] Working out the image size"
# ---------------------------------------------------------------
LAST_MB=""
if [ -r /sys/class/block/mmcblk0p2/start ] && [ -r /sys/class/block/mmcblk0p2/size ]; then
    START=$(cat /sys/class/block/mmcblk0p2/start)
    SIZE=$(cat /sys/class/block/mmcblk0p2/size)
    LAST_MB=$(( ((START + SIZE) * 512) / 1048576 + 1 ))
fi

# ---------------------------------------------------------------
echo "[9/9] Removing this script and powering off"
# ---------------------------------------------------------------
rm -f "$BOOT/clean.sh"
sync

echo
echo "=============================================="
echo " Ready to image."
echo
echo " Wait for the green LED to blink ten times and"
echo " go dark, then unplug and put the card in your"
echo " computer."
echo
echo " On a Mac, find the card's disk number with:"
echo
echo "     diskutil list"
echo
echo " Unmount it (replace N with that number):"
echo
echo "     diskutil unmountDisk /dev/diskN"
echo
echo " Then copy and compress it in one pass:"
echo
if [ -n "$LAST_MB" ]; then
echo "     sudo dd if=/dev/rdiskN bs=1m count=$LAST_MB | gzip > zerocam.img.gz"
echo
echo " The count of $LAST_MB stops at the end of the last"
echo " partition, so you get a ${LAST_MB}MB image rather than"
echo " one the size of the whole card."
else
echo "     sudo dd if=/dev/rdiskN bs=1m count=2200 | gzip > zerocam.img.gz"
fi
echo
echo " Then publish its checksum:"
echo
echo "     shasum -a 256 zerocam.img.gz"
echo "=============================================="
echo

sleep 5
poweroff -f
