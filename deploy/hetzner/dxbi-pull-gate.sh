#!/usr/bin/env bash
# Forced command for the 16 GB server's pull key on the 4 GB scraper box (installed as
# /usr/local/sbin/dxbi-pull-gate). The key can do one thing: read /root/data/dxbi-daily
# through rsync. Anything else is refused.
#
# authorized_keys line (maan@ the scraper box):
#   restrict,command="/usr/local/sbin/dxbi-pull-gate" ssh-ed25519 AAAA... vv-dxbi-pull
set -euo pipefail

command="${SSH_ORIGINAL_COMMAND:-}"
allowed='^sudo rsync --server --sender -[lDtpre.iLsfxCIvu]+ (--timeout=[0-9]+ )?\. /root/data/dxbi-daily/$'
if [[ ! "$command" =~ $allowed ]]; then
	echo "dxbi-pull-gate: refused" >&2
	exit 126
fi
read -ra argv <<<"$command"
exec "${argv[@]}"
