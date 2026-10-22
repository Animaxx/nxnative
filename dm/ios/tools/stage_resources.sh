#!/bin/bash
# Xcode target phase: copy the active game's resources into the app before CodeSign.
# Paths come from build_ipa.sh, not from a per-game rule or a phone-visible Mac path.
set -eu
[ "${DM_COPY_GAME_RESOURCES:-YES}" != NO ] || exit 0
die() { echo "[RED] $*" >&2; exit 1; }
[ "${PLATFORM_NAME:-}" = iphoneos ] || die 'This game needs a physical iPhone or iPad; choose a device, not a simulator.'
[ -f "${SRCROOT:?}/Gen/resources.env" ] || die 'Missing game resource paths; run build_ipa_from_nsp.py --prepare-xcode first.'
source "$SRCROOT/Gen/resources.env"
APP="${TARGET_BUILD_DIR:?}/${UNLOCALIZED_RESOURCES_FOLDER_PATH:?}"
case "$APP" in /*.app) ;; *) die "Unexpected app resource destination: $APP";; esac
# Validate every source before copying or removing anything (the external drive may be disconnected).
[ -e "$DM_RESOURCE_ROMFS/$DM_RESOURCE_MARKER" ] || die "Game files unavailable: $DM_RESOURCE_ROMFS/$DM_RESOURCE_MARKER"
[ -d "$DM_RESOURCE_SHADERS" ] || die "Shader libraries unavailable: $DM_RESOURCE_SHADERS"
[ -z "$DM_RESOURCE_AOC" ] || [ -d "$DM_RESOURCE_AOC" ] || die "Add-on content unavailable: $DM_RESOURCE_AOC"
echo 'Copy game resources (the first build copies the complete game; later builds sync changes)'
mkdir -p "$APP/romfs" "$APP/msl/$DM_RESOURCE_MSLDIR"
/usr/bin/rsync -a --delete -- "$DM_RESOURCE_ROMFS/" "$APP/romfs/"
/usr/bin/rsync -a --delete -- "$DM_RESOURCE_SHADERS/" "$APP/msl/$DM_RESOURCE_MSLDIR/"
for old in "$APP/msl/"*; do
    [ "$old" = "$APP/msl/$DM_RESOURCE_MSLDIR" ] || rm -rf "$old"
done
if [ -n "$DM_RESOURCE_AOC" ]; then
    mkdir -p "$APP/aoc"
    /usr/bin/rsync -a --delete -- "$DM_RESOURCE_AOC/" "$APP/aoc/"
else
    rm -rf "$APP/aoc"
fi
