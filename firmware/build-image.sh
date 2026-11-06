#!/usr/bin/env bash
set -euo pipefail
# Run inside the ARM64 Linux builder container. Only the downloaded image is mounted.
here=$(cd -- "$(dirname -- "$0")" && pwd)
assets=${1:?assets directory}
source_dir=${2:?patched firmware directory}
payload=${3:?directory containing compiled mediad}
name=hello-microduck-zero3w-r1-preview
base="$assets/microduck-zero3w-0.15.1-R1.img.xz"
echo '75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5  '"$base" | sha256sum -c -
mkdir -p "$assets/output" /mnt/hello-image
image="$assets/output/$name.img"
xz -dc "$base" > "$image"
mounted=0
cleanup() { if [[ $mounted == 1 ]]; then umount /mnt/hello-image; fi; }
trap cleanup EXIT
mount -o loop,offset=16777216 "$image" /mnt/hello-image
mounted=1
python3 "$here/patch-image.py" /mnt/hello-image "$payload" "$source_dir"
# Verify the shipped native executable against the image's actual dynamic libraries.
GST_PLUGIN_PATH=/usr/local/lib/gstreamer-1.0 chroot /mnt/hello-image \
    /usr/local/lib/hello-microduck/mediad --check-calibration
python3 "$here/verify-image.py" /mnt/hello-image
sync -f /mnt/hello-image
umount /mnt/hello-image
mounted=0
# Confirm a clean ext4 filesystem after an offline modification, without touching a host disk.
loop=$(losetup --find --show --offset 16777216 "$image")
trap 'losetup -d "$loop"' EXIT
e2fsck -fn "$loop"
losetup -d "$loop"
trap - EXIT
xz -T2 -3 -f "$image"
(cd "$assets/output" && sha256sum "$name.img.xz" > SHA256SUMS)
echo "Built $assets/output/$name.img.xz"
