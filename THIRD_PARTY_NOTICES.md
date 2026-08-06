# Third-party notices

## UxPlay 1.74

- Project: https://github.com/FDH2/UxPlay
- License: GNU General Public License version 3
- Use: AirPlay-compatible mirroring and audio receiver
- Pinned source archive: `vendor/UxPlay-master.zip`
- SHA-256: `7FDA6A6BF7227063388E67F7ADB15ADA222A5EEE5E45B139C881DB8F15E655A6`

The archived source includes `AIRMIRROR_PATCH.md` and a small Windows mDNS
interface patch. It allows the GUI to select the real LAN interface through the
`UXPLAY_MDNS_IPV4` environment variable without changing Windows adapter metrics.

UxPlay includes components under compatible licenses, including PlayFair, ShairPlay-derived code and llhttp. Their notices and source files are preserved inside the pinned source archive.

UxPlay's upstream documentation notes that the legal status of its third-party FairPlay compatibility library is unclear. AirMirrorLAN is intended for personal, non-commercial, open-source use. This intention is a community request, not an additional restriction on the rights granted by GPLv3.

## GStreamer and MSYS2 packages

GStreamer and its codec plugins are installed from signed MSYS2 packages by `scripts/setup-runtime.ps1`. Individual components retain their respective licenses. Package metadata is available through `pacman -Qi <package>` after installation.

## Apple trademarks

AirPlay, iPhone, Apple TV and Apple are trademarks of Apple Inc. AirMirrorLAN is an independent open-source project and is not affiliated with or endorsed by Apple Inc.
