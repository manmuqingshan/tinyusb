---
name: usb-recover
description: Use when a USB device or fixture on the ci HIL rig is stuck, hung, not enumerating, or wedged after a failed flash or test, or when processes touching USB (testusb, JLinkExe, uhubctl, libusb tools) start hanging in D state.
---

# USB Recovery on the HIL Rig

Run this skill's `scripts/usb_recover.sh` with `sudo` (abbreviated to
`usb_recover.sh` in the examples below). It wraps four sysfs reset actions plus
a resolver:

```bash
sudo usb_recover.sh resolve    /dev/ttyACM3    # /dev node -> busport (e.g. 3-4.7); also ttyUSB*, sg*
sudo usb_recover.sh authorized <busport>       # deauthorize+reauthorize: re-enumerate, no VBUS cut
sudo usb_recover.sh rebind     <busport>       # usb driver unbind+bind: re-probe
sudo usb_recover.sh pci-rebind <pciaddr>       # whole HCD controller unbind+bind, e.g. 0000:02:00.0
sudo usb_recover.sh pci-reset  <pciaddr>       # PCI function-level reset: kills URBs at HW level, no device lock
sudo usb_recover.sh pci-bind   <pciaddr> [drv] # re-bind a DRIVERLESS controller (auto-tries xHCI drivers)
```

## Decide first: is anything stuck in D state?

```bash
ps -eo pid,stat,wchan:30,cmd | awk '$2 ~ /D/'
```

**If yes** (uninterruptible sleep, typically a usbfs ioctl — e.g. testusb inside
`usb_sg_wait`): run `pci-reset` and NOTHING ELSE first:

```bash
sudo usb_recover.sh pci-reset <pciaddr>
```

FLR kills the URBs at the hardware level without taking the per-device lock;
the ioctl then returns and the convoy unwinds on its own.

**Not every controller supports FLR.** The Renesas uPD720201 (`0000:01:00.0`)
has no reset method — `pci-reset` fails with `Inappropriate ioctl for device`
(ENOTTY). On those, there is no clean software D-state cure — a VM reboot is NOT
reliable (the MosChip downstream hubs latch up across the PCIe reset and need a
physical replug); ask the operator for a full PVE host power cycle instead. Do NOT
fall through to `pci-rebind` (see next).

**`pci-rebind` can strand the controller driverless.** Its unbind succeeds but,
with a D-state process still holding a URB, the *re-bind* hangs — leaving the
PCI device with **no driver** (`/sys/bus/pci/devices/<addr>/driver` gone) and the
whole controller's fixtures offline. A second `pci-rebind` then dies with "no
driver bound". Recover with `pci-bind <addr>` (re-attaches the xHCI driver);
if that also hangs because the D-state URB is unkillable, only a full PVE host
power cycle (operator action) recovers. The Renesas binds via `xhci-pci-renesas` (firmware loader), others via
`xhci_hcd` — `pci-bind` auto-tries both, or pass the driver explicitly.

**Ordering is critical.** `authorized`/`rebind`/`pci-rebind` all take the
per-device lock the stuck ioctl holds — they block and join the convoy, and
soon every libusb tool (uhubctl, JLinkExe) hangs too. Worse, a blocked
`pci-rebind` grabs the PCI device lock on its way in, which `pci-reset` also
needs: once a rebind has been attempted and is stuck, even FLR deadlocks and
**only a full PVE host power cycle recovers**. pci-reset first (if supported), and never
`pci-rebind` a D-state wedge.

**If no** (device merely dead or silent), escalate gently:

1. `authorized <busport>` — re-enumerates just that device
2. `rebind <busport>` — re-probe; also worth trying on the parent hub's busport
3. `pci-rebind <pciaddr>` — last resort: bounces every fixture on that controller

## Finding targets

```bash
grep -l <SERIAL> /sys/bus/usb/devices/*/serial          # serial -> busport (dir name)
readlink -f /sys/bus/usb/devices/usb<N>                  # bus N -> its PCI addr in the path
```

Rig layout: buses 3+4 = `0000:02:00.0` (main fixture tree: J-Links, ST-Links,
WCH-Links, DUTs); buses 9+12 = `0000:01:00.0`, the only ones with uhubctl port
power (ganged VBUS: `sudo uhubctl -l 9 -a cycle`). Hubs on buses 1-4 have no
port power switching — uhubctl reports "No compatible devices" there.

## Common mistakes

- `resolve` takes a **/dev node**, not a busport or serial ("no such device node").
- `authorized`/`rebind` take a **busport** (`3-4.7`); `pci-rebind`/`pci-reset`
  take a **PCI addr**.
- Command produces no output and doesn't return → it is blocked on the device
  lock: a D-state holder exists; see above.
- Trying `pci-rebind` on a D-state hang — its re-bind hangs and strands the
  controller **driverless**; recover with `pci-bind <addr>`, or a PVE host power
  cycle if the D-state URB is unkillable. Use `pci-reset` (if supported) for D-state, never
  `pci-rebind`.
- Running `pci-reset` on a controller without FLR support (Renesas) → ENOTTY;
  no software recovery — needs a PVE host power cycle.
- A J-Link reset (`r; go`) does not disconnect a wedged DUT from the host: the
  DWC2 soft-connect pullup stays up through a core halt, so stuck URBs stay stuck.
