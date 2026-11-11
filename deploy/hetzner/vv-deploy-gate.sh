#!/usr/bin/env bash
# Forced command for the GitHub Actions deploy key on the pilot backend server.
#
# Installed as ~/deploy/vv-deploy-gate.sh and referenced from ~/.ssh/authorized_keys:
#   restrict,command="/home/maan/deploy/vv-deploy-gate.sh" ssh-ed25519 AAAA... github-actions-deploy
#
# The key can do exactly two things:
#   1. push commits into the server's bare repo (git push <host>:vv.git <sha>:refs/heads/deploy)
#   2. run the deploy script for one full commit SHA (ssh <host> deploy <sha>)
set -euo pipefail

cmd="${SSH_ORIGINAL_COMMAND:-}"

case "$cmd" in
	"git-receive-pack 'vv.git'" | "git-receive-pack '/home/maan/vv.git'" | "git-receive-pack '~/vv.git'")
		exec git-receive-pack "$HOME/vv.git"
		;;
	deploy\ *)
		sha="${cmd#deploy }"
		if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
			echo "deploy gate: expected a full 40-character commit SHA" >&2
			exit 2
		fi
		exec "$HOME/deploy/vv-deploy.sh" "$sha"
		;;
	*)
		echo "deploy gate: command not allowed" >&2
		exit 1
		;;
esac
