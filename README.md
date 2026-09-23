# ZeroCam

A deliberately low-fi camera that runs on SeedSigner hardware.

Swap the microSD card and your signing device becomes a small, slow, strange
little camera with sixteen picture effects and no network connection of any
kind. Swap the card back and it is a SeedSigner again. Nothing about the
hardware changes in between.

The photographs are not good. That is the point. A fixed-focus sensor behind a
pinhole lens, rendered through effects that belong to 2012 phone cameras,
saved as sequential JPEGs on a card with no clock to date them.

---

## ⚠️ Read this before you run it

**This code was written by an AI.** Claude (Anthropic) wrote essentially all of
it, directed and tested by a human who cannot read Python. It works on the
hardware it was built for, and it has not been reviewed by anyone who could
have caught a subtle mistake.

If you are the kind of person who owns a SeedSigner, you already know what to
do with that sentence. Read the source. It is one Python file of about 500
lines, plus two shell scripts. Do not run it because a stranger on the internet
said it was fine.

**ZeroCam never touches your SeedSigner card**, and it has no network
capability, no wallet code and no knowledge that bitcoin exists. But verify
that for yourself rather than taking this paragraph's word for it.

---

## Does this change my SeedSigner?

No, and the reason is worth stating precisely.

**A Pi Zero 1.3 has no writable storage on the board at all.** No flash chip,
no firmware EEPROM. The first-stage bootloader lives in mask ROM inside the
processor, burned at manufacture and physically unwritable. Everything else
(bootloader, GPU firmware, kernel, operating system) is loaded from the SD card
at every power-on. Swap the card and the board is byte for byte what it was.

This is not true of newer Raspberry Pis. The Pi 4 and Pi 5 keep their
bootloader in a writable SPI EEPROM which software can reflash. The Zero 1.3
and the Zero 2 W both predate that and boot only from the card.

**The one theoretical exception**, for the properly paranoid: the chip contains
one-time-programmable fuses holding the serial number and a few configuration
flags, and some of them can be burned by a directive in `config.txt`. ZeroCam
contains no such directive. This is verifiable rather than a promise, because
`config.txt` is plain text on the card that anyone can read. The only lines
ZeroCam adds are:

```
dtparam=spi=on
start_x=1
gpu_mem=128
```

All three are read fresh at each boot and persist nowhere.

**The real risk is not firmware, it is card confusion.** Two visually identical
microSD cards, one of which holds your signing device. That is the failure mode
that could actually cost you money. **Label the cards physically.** A sticker, a
paint mark, different coloured adapters, anything.

---

## What you need

- A SeedSigner, or the same parts: a Raspberry Pi Zero 1.3 or Zero 2 W, a
  Waveshare 1.3 inch LCD HAT (ST7789, 240x240, joystick and three keys), and a
  Raspberry Pi camera module.
- A **second** microSD card, 4GB or larger. Not the one your SeedSigner is on.
- A way to write it: Raspberry Pi Imager or Balena Etcher.

---

## Install

1. Download `zerocam.img.gz` from the [releases page](../../releases).
2. Verify it:
   ```
   shasum -a 256 zerocam.img.gz
   ```
   and compare against the checksum published with the release.
3. Write it to the card with Balena Etcher or Raspberry Pi Imager. Both read
   the `.gz` directly, no need to decompress it first. In Raspberry Pi Imager,
   choose "Use custom" at the bottom of the OS list.
4. Put the card in the Pi and apply power.

It takes about 45 seconds to boot, then shows a splash screen and becomes a
camera. There is nothing to configure and nothing to log into.

---

## Using it

| Control | What it does |
| --- | --- |
| Joystick press | Take a photo |
| Joystick left / right | Previous / next effect |
| Joystick up / down | Change white balance |
| KEY1 | Next effect |
| KEY2 | Status: effect, white balance, photo count, free space |
| **KEY3 held 2 seconds** | **Shut down safely** |

The effects are rendered by the camera hardware itself rather than in software,
so they cost nothing on a 1GHz single core and you see them in the live preview
before you take the shot. There are sixteen, including sketch, cartoon,
solarise, posterise, emboss, watercolour and negative.

**Always hold KEY3 and wait for the screen to clear before unplugging.** Each
photo is flushed to the card as it is taken, so you will rarely lose one, but
the FAT filesystem has no way to repair itself if power is cut during a write.

---

## Getting the photos off

Shut down, take the card out, put it in any computer. A drive called `boot`
appears, with a folder called `photos` inside it. The JPEGs are simply there.

No software, no drivers, no cable. This is why the photographs live on the FAT
partition rather than somewhere more sensible.

**Capacity is around 200MB**, which is a few hundred photographs. The status
screen (KEY2) shows the space remaining, and warns you when it is running low.
Copy them off and delete them to make room.

---

## Limitations, honestly

- **It is not a good camera.** Fixed focus, tiny sensor, no flash, no zoom.
- **No clock.** The Pi has no battery-backed real-time clock, so file
  timestamps are meaningless and photos are numbered rather than dated.
- **Preview runs at roughly 10 to 15 frames per second** on a Zero 1.3. It is
  usable, not smooth.
- **The image is about 500MB compressed**, and expands to roughly 2GB on the
  card. SeedSigner's own image is a fraction of that because it is built with
  Buildroot, a minimal Linux assembled from source. Doing the same here would
  be a project of weeks rather than an afternoon. Someone should. It is not
  this.
- **Built on Raspberry Pi OS Bullseye**, which is old and no longer receives
  security updates. For a device with no network connection this is a
  reasonable trade, and it is a necessary one: Bookworm removed the legacy
  camera stack that the hardware effects depend on. The one real risk is that
  Raspberry Pi eventually retires the Bullseye package servers, which would
  break `build.sh` but not any image already made.
- **ssh is switched off** in the released image. If you want it, put an empty
  file named `ssh` on the boot partition. The default account is `zerocam` with
  password `zerocam`, so **change it immediately** if you do that.

---

## Building it yourself

The image is a convenience. The scripts are the truth. If you would rather not
trust a binary built on someone else's laptop, build your own. It takes about
half an hour and the result is functionally identical.

You need a way to give the Pi an internet connection once, to fetch the
packages. On a Pi Zero with no wifi, the usual route is USB gadget networking
over the data port, which the steps below set up.

**1. Flash Raspberry Pi OS Lite (Bullseye, 32-bit).** It is no longer in the
Imager's list, so download it directly:

```
https://downloads.raspberrypi.org/raspios_lite_armhf/images/raspios_lite_armhf-2022-09-26/2022-09-22-raspios-bullseye-armhf-lite.img.xz
```

and choose "Use custom" in the Imager.

**2. Prepare the card.** With it mounted as `/Volumes/boot` on a Mac:

```sh
V=/Volumes/boot

# Enable ssh and create a temporary account (password: zerocam)
touch $V/ssh
echo 'zerocam:$6$5vvHpwbyTyNF6ai9$kERzebWk8g1o/RAaC1NdkoAGj2ZNBqA5X7P0CoyrUrtTOaR/8MRMdMvIr3WCAmR3d8Wp6Zc455hh39/i9fAH01' > $V/userconf.txt

# USB gadget networking, forced into peripheral mode
echo 'dtoverlay=dwc2,dr_mode=peripheral' >> $V/config.txt
sed -i '' -e 's| init=/usr/lib/raspberrypi-sys-mods/firstboot||' \
          -e 's|rootwait|rootwait modules-load=dwc2,g_ether|' $V/cmdline.txt

# The build files
cp zerocam.py build.sh clean.sh $V/
```

Removing the `firstboot` entry is what stops the root partition expanding to
fill the card. That is what keeps the finished image at 2GB instead of the size
of whatever card you built it on.

**3. Share the Mac's connection.** Plug the Pi into the **inner** micro USB
socket, wait for it to boot, then turn on Internet Sharing (from Wi-Fi, to the
Ethernet Gadget that has just appeared). Then unplug the Pi and plug it back
in, so that it asks for an address while the sharing is already running. This
ordering matters and is the single most common reason this fails.

**4. Connect and build:**

```sh
ssh zerocam@raspberrypi.local     # password: zerocam
sudo apt-get update               # if this fails, the Bullseye servers are gone
sudo sh /boot/build.sh
sudo reboot
```

It is a working camera at this point. Test it before going further.

**5. Only if you are making a release image**, run the cleanup. It deletes your
account, your photographs, your ssh keys and your shell history, then powers
off and prints the exact command for copying the card:

```sh
sudo sh /boot/clean.sh
```

---

## Files

| File | What it is |
| --- | --- |
| `zerocam.py` | The camera. Display driver, buttons, capture, effects. |
| `build.sh` | Turns a fresh Bullseye card into a working camera. |
| `clean.sh` | Strips a card of everything personal, for release. |

---

## Credits

Hardware and inspiration: the [SeedSigner](https://github.com/SeedSigner/seedsigner)
project, whose design made a pocket-sized airgapped computer cheap enough that
turning one into a toy camera seemed reasonable. ZeroCam is not affiliated with
SeedSigner and they bear no responsibility for it.

Code: written by Claude (Anthropic), directed and tested by
[@ZLOK](https://x.com/ZLOK).

MIT licensed. Do what you like with it.
