# Proposed persistent Mac open-file caps

This is a **reviewable proposal, not an installed change**. The user approved
temporary caps only. Read-only inspection found macOS **26.3.1(a)**, build
`25D771280a`, and Apple Container CLI **1.4.1**. The approved kernel values
remain `kern.maxfiles=262144` and `kern.maxfilesperproc=131072`. An earlier
sample used 172,097 files; the final read-only sample used 134,485. Both exceed
the old system cap of 122,880.

Use one root-owned administrator LaunchDaemon that runs the same two-value
`sysctl` command at boot. The [proposed plist](test-evidence/proposals/org.copyme2.open-files.plist)
contains no shell, credentials, service restart or per-process limit changes.
It passed local `plutil -lint`. Apple documents administrator LaunchDaemons
and root ownership in its [launchd guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
The installed `man launchd.plist` and `man launchctl` on this exact OS confirm
`ProgramArguments`, `RunAtLoad`, `bootstrap`, `bootout`, root ownership and
disallowing group/world writes. No reliance on `/etc/sysctl.conf` is proposed.

## Three different limits

| Limit | Meaning and scope |
| --- | --- |
| `kern.maxfiles` | Machine-wide kernel file-table capacity; the observed startup failure was system-wide `ENFILE` |
| `kern.maxfilesperproc` | Kernel per-process ceiling, distinct from each process's `RLIMIT_NOFILE` |
| Process soft/hard `RLIMIT_NOFILE` | Inherited process limits; `ulimit -Sn/-Hn` describes the current shell, and `launchctl limit maxfiles` describes that launchd context, not all running processes |

This task shell reports soft 1,048,575/hard unlimited while its launchctl
context reports 256/unlimited. These observations do not establish the
limits of the user's Terminal or existing Container host daemons. Raising
kernel caps does not raise every process's soft limit. The installed plist
manual also warns that `NumberOfFiles` resource keys in system-wide jobs can
change kernel caps as a side effect; they are deliberately absent here.

Apple Container's host API/VM processes have their own inherited Mac limits.
The Linux init process inside each container has separate guest limits;
[`container run/create --ulimit nofile=soft:hard`](https://github.com/apple/container/blob/main/docs/ulimits.md)
controls those guest limits, not Mac kernel capacity. A shell `ulimit` change
does not retroactively change an already-running host service. No Container
guest or host-service limit change is part of this proposal.

## Commands for review

Run these only after separately approving persistent installation. Stop if
the destination or job label already exists; preserve any existing job.
From the isolated integration checkout:

```sh
set -e
test ! -e /Library/LaunchDaemons/org.copyme2.open-files.plist
if sudo launchctl print system/org.copyme2.open-files >/dev/null 2>&1; then
  echo 'Existing launchd job found; preserve it and stop.' >&2
  exit 1
fi
plutil -lint docs/test-evidence/proposals/org.copyme2.open-files.plist
sudo install -o root -g wheel -m 600 \
  docs/test-evidence/proposals/org.copyme2.open-files.plist \
  /Library/LaunchDaemons/org.copyme2.open-files.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/org.copyme2.open-files.plist
sudo launchctl print system/org.copyme2.open-files
sysctl kern.maxfiles kern.maxfilesperproc kern.num_files
```

Verify ownership/mode are `root:wheel` and `600`, the job's last exit code is
zero, and the two actual kernel values match. A successful one-shot job need
not remain running. Repeat the kernel/job checks after the next **planned**
reboot; no reboot was performed or requested for verification here.

## Boot ordering and rollback

`RunAtLoad` launches when the plist is loaded. It does **not** guarantee
completion before Apple Container or another shared stack starts. The
installed manual discourages speculative boot jobs in general; this proposal
uses one short, necessary boot-setting invocation with no keep-alive loop.
As an inference from launchd's lack of explicit dependency ordering, stack
startup should first verify both kernel values and fail/defer if they are
lower. Merely naming this plist earlier alphabetically is not a dependency.
Changing existing stack autostart jobs to enforce that gate would be a
separate reviewed change; none were inspected or modified here.

If this exact proposal is later installed, remove its future boot action with:

```sh
sudo launchctl bootout system/org.copyme2.open-files
sudo rm /Library/LaunchDaemons/org.copyme2.open-files.plist
```

Unloading/removing the job does not undo the current kernel values. Once
workload fits the previous caps, restore them separately:

```sh
sudo sysctl kern.maxfiles=122880 kern.maxfilesperproc=61440
```

**Do not lower the caps under the current workload.** Without the persistent
job, reboot restores defaults and can reintroduce startup failures if the
same workload resumes. Higher caps permit greater kernel-resource use; they
do not correct descriptor leaks or remove the need to bound startup
concurrency. This proposal does not install a daemon, change permissions,
change limits, restart services, or alter shared data.
