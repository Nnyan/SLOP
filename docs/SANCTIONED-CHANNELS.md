# Sanctioned Channels

Every entry in `permissions.deny` of `.claude/settings.local.json` must be
accounted for by EITHER:

(a) **A sanctioned tool** under `tools/sanctioned/` (or `tools/merge_wave_to_main.py`)
    that provides a single, audited, lift-restore-`try/finally` code path for the
    operation the deny would otherwise block; OR

(b) A **"no-exceptions-period" rationale** in this file — meaning the deny is
    NEVER intended to be lifted by any tool, for any reason.

The `check_sanctioned_channels_complete` gate in `ms-enforce` (TIER_1, warn-only)
verifies this dichotomy. Any deny rule not present in either column is a gap that
must be closed.

---

## Registry: deny → sanctioned tool

| Deny rule | Sanctioned tool | Notes |
|---|---|---|
| `Bash(git checkout main*)` | `tools/merge_wave_to_main.py` | Lift for post-wave merge-to-main only |
| `Bash(git switch main*)` | `tools/merge_wave_to_main.py` | Lift for post-wave merge-to-main only |
| `Bash(git push*)` | `tools/sanctioned/robot_settings.py` (push-then-restore subcommand) | Operator-triggered post-wave push only |
| `Bash(git push -f*)` | `tools/sanctioned/force_push_tag.py` | Force-push a single rewritten tag/ref after authorized history rewrite |
| `Bash(git push -u*)` | `tools/sanctioned/robot_settings.py` | Covered by push-then-restore |
| `Bash(git push --no-verify*)` | `tools/sanctioned/robot_settings.py` | Covered by push-then-restore |
| `Bash(git push --force*)` | `tools/sanctioned/force_push_tag.py` | Same as `git push -f*` — synonym deny |
| `Edit(/home/stack/code/slop/.claude/settings.local.json)` | `tools/sanctioned/robot_settings.py` | Lift-restore for post-wave operator handoff |
| `Write(/home/stack/code/slop/.claude/settings.local.json)` | `tools/sanctioned/robot_settings.py` | Lift-restore for post-wave operator handoff |

---

## No-exceptions-period: denies that are NEVER lifted

The following deny rules have no sanctioned lift tool and are intended to be
permanent with no exceptions. Each entry includes a rationale explaining why
the operation must be categorically blocked — no "special case" can justify it.

| Deny rule | No-exceptions rationale |
|---|---|
| `Bash(sudo *)` | Privilege escalation from an agent session would bypass the entire permission model; no legitimate wave operation requires sudo. Any system-level change goes through the installer or operator terminal. |
| `Bash(su -*)` | Same rationale as sudo — lateral privilege escalation from agent. |
| `Bash(su *)` | Same rationale as sudo. |
| `Bash(doas *)` | Same rationale as sudo. |
| `Bash(git commit --amend*)` | History mutation is forbidden in Robot mode. Amend replaces a commit, making the history non-linear and unreviewed. New commits only. |
| `Bash(git rebase*)` | History rewrite that can silently drop commits or reorder them. The only authorized history rewrite is the Tailscale-key-leak-style `filter-branch` which goes through `tools/sanctioned/filter_branch_secret_scrub.py`. |
| `Bash(git reset --hard*)` | Destructive local state reset. No wave operation needs to hard-reset; if a merge conflict is unresolvable, the stream writes a blocker and halts. |
| `Bash(git commit --no-verify*)` | Bypasses pre-commit hooks. Robot mode must run all hooks; bypassing them invalidates the automated quality gate. |
| `Bash(git config user.*)` | Impersonation risk — setting git identity inside an agent session could forge commit attribution. |
| `Bash(git config --global*)` | Global config mutation from an agent is never authorized; would affect all repositories on the host. |
| `Bash(git remote add*)` | Adding remotes from inside an agent session could exfiltrate code to attacker-controlled repositories. |
| `Bash(git remote set-url*)` | Same exfiltration risk as `git remote add*`. |
| `Bash(git clean -f*)` | Destroys untracked files without review. Wave streams never need this; if a state cleanup is required, it's a blocker not an autonomous action. |
| `Bash(git clean -fd*)` | Destroys untracked files and directories. Same rationale as `git clean -f*`. |
| `Bash(apt *)` | Package manager mutations — system state changes are never the agent's responsibility; they go through the installer. |
| `Bash(apt-get *)` | Same as `apt *`. |
| `Bash(dnf *)` | Same as `apt *`. |
| `Bash(yum *)` | Same as `apt *`. |
| `Bash(pacman *)` | Same as `apt *`. |
| `Bash(snap *)` | Same as `apt *`. |
| `Bash(brew *)` | Same as `apt *`. |
| `Bash(npm install -g*)` | Global npm installs modify system state and create supply-chain risk outside the project's dependency model. |
| `Bash(pip install --system*)` | System-wide pip install bypasses the venv boundary and could corrupt host python. |
| `Bash(systemctl *)` | Service management from inside an agent is never authorized; it would be opaque to the operator and could restart/stop production services. |
| `Bash(service *)` | Same as `systemctl *`. |
| `Bash(journalctl *)` | Log reading from an agent could leak sensitive system information. Wave streams don't need system logs. |
| `Bash(rc-service *)` | Same as `systemctl *`. |
| `Bash(init *)` | Init system manipulation — categorically forbidden. |
| `Bash(shutdown *)` | Host shutdown from agent — categorically forbidden. |
| `Bash(reboot *)` | Host reboot from agent — categorically forbidden. |
| `Bash(docker compose up*)` | Starting containers changes system state and port bindings; never autonomous from a wave stream. |
| `Bash(docker compose down*)` | Stopping containers risks disrupting running services; operator action only. |
| `Bash(docker run*)` | Spawning arbitrary containers from an agent is a code-execution escape vector. |
| `Bash(docker start*)` | Same as `docker run*`. |
| `Bash(docker stop*)` | Stopping containers — operator action only (could stop production). |
| `Bash(docker rm*)` | Removing containers — operator action only. |
| `Bash(docker rmi*)` | Removing images — operator action only; could delete images needed for other services. |
| `Bash(docker exec*)` | Exec into container — equivalent to arbitrary code execution inside the container; never agent-authorized. |
| `Bash(docker kill*)` | Same as `docker stop*` but more forceful. |
| `Bash(docker login*)` | Registry authentication from agent — credential exposure risk. |
| `Bash(docker push*)` | Pushing images to a registry — never autonomous from a wave stream. |
| `Bash(docker pull*)` | Pulling arbitrary images is a supply-chain risk during autonomous runs. |
| `Bash(ssh *)` | Remote shell access from an agent is a lateral movement / exfiltration vector. No wave operation requires SSH. |
| `Bash(scp *)` | Remote file copy — same risk as `ssh *`. |
| `Bash(rsync *)` | Remote sync — same risk as `ssh *`. |
| `Bash(sftp *)` | Remote file transfer — same risk as `ssh *`. |
| `Bash(curl *)` | Arbitrary outbound HTTP — fetches can leak data or pull untrusted code. Use the allow-listed `WebFetch(domain:*)` rules for approved domains. |
| `Bash(wget *)` | Same as `curl *`. |
| `Bash(nc *)` | Netcat — arbitrary TCP; exfiltration / backdoor risk. |
| `Bash(netcat *)` | Same as `nc *`. |
| `Bash(rm -rf /*)` | Destroys the root filesystem — categorically forbidden with no exceptions. |
| `Bash(rm -rf ~*)` | Destroys the home directory — categorically forbidden. |
| `Bash(rm -rf $HOME*)` | Same as `rm -rf ~*`. |
| `Bash(rm -rf $$HOME*)` | Shell double-expansion variant — same as above. |
| `Bash(rm -rf /home/stack/.claude*)` | Destroys the Claude configuration directory — would lose all settings, keys, and state. |
| `Bash(rm -rf /home/stack/code/slop/.git*)` | Destroys the git repository — catastrophic and unrecoverable without remote. |
| `Bash(find / *)` | Unrestricted filesystem scan; performance/resource exhaustion; could read secrets from arbitrary paths. Use scoped `find` (within the project tree). |
| `Bash(chown *)` | Ownership changes require elevated privileges in most configurations and could escalate access. |
| `Bash(chmod -R 777*)` | World-writable permissions — security hole; no legitimate operation needs this. |
| `Bash(crontab *)` | Persistent job scheduling from an agent is a persistence mechanism; never authorized. |
| `Bash(at *)` | One-time scheduled job — same rationale as `crontab *`. |
| `Bash(batch *)` | Batch job scheduler — same rationale as `crontab *`. |
| `Edit(/home/stack/.claude/**)` | The global `~/.claude/` directory holds Claude Code configuration and credentials; agents must not modify it. |
| `Write(/home/stack/.claude/**)` | Same as above. |
| `Edit(/etc/**)` | System configuration files — modifying `/etc` from an agent is equivalent to `sudo`. |
| `Write(/etc/**)` | Same as above. |
| `Edit(/usr/**)` | System binaries and libraries — agents must not modify them. |
| `Write(/usr/**)` | Same as above. |

---

## How to add a new deny rule

1. Add the rule to `.claude/settings.local.json` (and to `.claude/settings-wave-mode-profile.json`
   as the canonical restore source of truth).
2. Choose column:
   - **Needs a sanctioned tool?** Create `tools/sanctioned/<tool>.py` that lifts the
     deny, performs the operation, audits via `write_entry`, and restores in `try/finally`.
     Register the mapping in the "Registry" table above.
   - **Permanent no-exceptions?** Add a row to the "No-exceptions-period" table above
     with a clear rationale.
3. The `check_sanctioned_channels_complete` gate in `ms-enforce` will warn if you add
   a deny without updating this file.

---

*Last updated: S-68 Stream E (2026-05-29)*
