This diagnostic consumer is the unmodified `userspace/src/nm.c` and `nm.h`
from maxsteeel/nomount commit bf1847f98fed382369c43bfd652cd93774b9b8e3.
It uses the packed 4096-byte pointer-through-add_key protocol, not Netlink.
Source license text: the pinned repository's GPL version 3 (fs/nomount/LICENSE),
copied unchanged. The kernel's existing MODULE_LICENSE("GPL") is retained.

The RMX3997 increment accepts regular-file rules below existing writable ext4
parents, with regular unencrypted/unverified backing on the same superblock.
Rule flags, directory overlays, virtual parent creation, symlink/special-file
backing and other filesystems return errors. Synthetic link/unlink/rename also
return EOPNOTSUPP before the real filesystem callback. No copy-up is supplied. Filesystem ioctl and splice forwarding return EOPNOTSUPP; generic VFS fd ioctls retain their normal behavior.
Backing changes after rule creation keep the pinned object; path-rebinding and
parent rename semantics are outside this diagnostic contract.

The CLI intentionally reports command success via payload.status. add_key
returns ECANCELED after processing. Transport, keyring/SELinux, capability and
seccomp denials leave the sentinel status unchanged and must not be treated as
feature success. An Android root shell must have CAP_SYS_ADMIN, add_key allowed
by seccomp, and write access to its thread keyring under the actual LSM domain.
No policy change, daemon, metamodule, startup or installation script is included.

The paired nomount-runtime.inc is a disposable guest fixture, never a phone
startup program. Physical phone boot and deployed Android NoMount remain UNKNOWN.
