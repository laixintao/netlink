#!/bin/bash

# This shell only reads, it won't change anything on your system, so it is
# safe to run.

lldp_info=$(lldpcli show neighbor)
bond_info=$(cat /proc/net/bonding/*)
lshw_short_info=$(lshw -class net -short)
lldp_connected_interfaces=$(echo $lldp_info | grep -P -o 'Interface:\s+\K[^,]+')
bond_interfaces=$(ls /proc/net/bonding/)
ip_addresses=$(ip -br a)


find_physical_hardware() {
    interface_hardware=$(echo "$lshw_short_info" | awk '$2 ~ /'$1'/ { for (i=4; i<=NF; i++) printf "%s ", $i;}')
    echo $interface_hardware
}

find_lldp_neighbor() {
    neighbor=$(echo "$lldp_info" | sed -n '/'$1'/,/SysName/p' | grep -P -o 'SysName: \s+\K.*' )
    echo "connected==> $neighbor"
}

find_driver() {
    driver=$(ethtool -i $1 | grep "driver:")
    echo $driver
}

find_address() {
    address=$(echo "$ip_addresses" | grep $1 | grep -E -o '[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}')
    echo $address
}

find_bonding_slave() {
    for interface in $bond_interfaces; do
        if grep  "Slave Interface: $1" /proc/net/bonding/$interface ; then
            echo "{ Slave of $interface }"
        fi
    done
}


main() {
    for interface in $bond_interfaces; do
        echo "[$interface] (bond) $(find_address $interface)"
        echo ""
    done

    for interface in $lldp_connected_interfaces; do
        echo "[$interface] $(find_address $interface)"
        find_driver $interface
        find_physical_hardware $interface
        find_lldp_neighbor $interface
        find_bonding_slave $interface
        echo ""
    done
}

main
