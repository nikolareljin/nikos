# Dual boot

NikOS installs onto an Ubuntu or Xubuntu 22.04, 24.04 or 26.04 that already boots. It does not
partition disks or install a boot loader; it only adjusts GRUB's settings.

## Windows in the GRUB menu

Ubuntu turns os-prober off by default (GRUB 2.06 and later), so a Windows
install on the same machine is not listed. With `nikos_grub_os_prober: true`
(the default) the `base` role installs `os-prober`, writes

```
/etc/default/grub.d/60-nikos-os-prober.cfg
GRUB_DISABLE_OS_PROBER=false
```

and runs `update-grub`. It does this only when `/etc/default/grub` exists and
never during an image build. Set `nikos_grub_os_prober: false` in
`vars/local.yml` to leave GRUB's default alone; the file is then no longer
managed (delete it by hand to undo it).

If Windows is still missing, mount its EFI partition or let os-prober see the
disk, then run `sudo update-grub` and look for `Found Windows Boot Manager`.

## Which boot entry the firmware starts

On UEFI machines the firmware, not GRUB, picks what boots first. A Windows
update can move its own entry back to the top. List and reorder with
`efibootmgr`:

```bash
sudo efibootmgr                 # BootOrder and the numbered entries
sudo efibootmgr -o 0001,0000    # ubuntu first, then Windows Boot Manager
```

## UEFI or legacy

Both systems must boot the same way. Check Linux with
`[ -d /sys/firmware/efi ] && echo UEFI || echo legacy`, and Windows in
`msinfo32` (BIOS Mode). A legacy-mode Linux cannot chain-load a UEFI Windows,
and os-prober will not offer it.

## Secure Boot and SBAT

Ubuntu boots under Secure Boot through its signed shim. When firmware or a
Windows update raises the SBAT revocation level, an older shim or GRUB is
refused at boot ("SBAT self-check failed" or "Verifying shim SBAT data
failed"). Update Ubuntu's `shim-signed` and `grub-efi-amd64-signed` packages
from a working boot, or temporarily disable Secure Boot in firmware setup to
get back in and update them.

## GRUB theme location

GRUB loads its theme before the kernel runs, from a filesystem it can read
itself. On an installed system NikOS always puts the NikOS theme in
`/usr/share/grub/themes/NikOS`. When `/boot` is a separate mount or the root
filesystem sits on LUKS (`crypt` in `lsblk -s` of the root device), GRUB cannot
read `/usr/share`, so the theme is also copied to `/boot/grub/themes/NikOS`
and `GRUB_THEME` points at that copy.

## Image builds

When the play runs as an ISO build (`nikos_image_build: true` in
`isoforge.yml`, a chroot, or `nikos_home: /etc/skel`):

- `update-grub` is not run, by either role.
- The GRUB theme goes to `/usr/share/grub/themes/NikOS` only, because the
  image's squashfs excludes `boot/grub`. `GRUB_THEME` points there.
- The `linux-image*`, `linux-generic*`, `linux-headers-generic` and
  `linux-modules*` packages are held while `base` upgrades packages and
  released straight after, so the squashfs keeps the kernel the live casper
  kernel was built from. The holds are not left in the image.
