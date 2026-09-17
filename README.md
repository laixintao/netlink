# netlink
Show the network link information, summary from lshw, lspci, iproute2, ethtool and LLDP.

NIC and bond details include IPv4 and IPv6 addresses with prefix lengths, collected
using `ip -j address show dev <interface>` (iproute2). Multiple addresses are shown
on separate lines. `N/A` means no address was found or address data is unavailable.
