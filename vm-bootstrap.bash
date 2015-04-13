#!/usr/bin/bash

# Bootstrap script 
# Generate with fabric information
# Configure hostname, ethX, grains 
# with information given by Fabric / YAML

# Soon we have to make some check to use 
# os depends command or file path 

# Here a check to be sure to execute 
# this script on only on first boot

logfile="/var/log/bootstrap.log"
host_name=`hostname`
salt_master="mysalt-master.local"
salt_minion_config_file="/etc/salt/minion"

if [ $host_name != "template" ]
        then
                echo "La machine est déjà customisee." >>$logfile
                exit 1
fi


# Definition du package salt
salt_pkg="salt-minion"

# Set ifcfg-ethX path
ifcfg_path="/etc/sysconfig/network-scripts"


# Default gw path
gateway_path="/etc/sysconfig/network"



# ip | prefix list for interfaces (provide by fabric)
ip_list=(
	'10.203.2.237'
	)

prefix_list=(
	'24'
	)

# Default gateway value | provide by fabric
def_gateway="10.X.X.X"

# DNS config | provide by fabric
dns_path="/etc/resolv.conf"


# hostname (provide by fabric)
instance_name="d-minion1"

# Get number of ip
length=${#ip_list[@]} 

# Export du proxy 
export HTTP_PROXY=proxy.local:8080
export HTTPS_PROXY=proxy.local:8080

# Start Customisation

# Set hostname
echo "Set hostname" >>$logfile
echo $instance_name > /etc/hostname

# Set default gateway
echo "Set default gateway" >>$logfile
echo "GATEWAY=$def_gateway" >$gateway_path

# Set dns server
>$dns_path
echo "nameserver 192.168.139.1" >> $dns_path
echo "nameserver 192.168.139.2" >> $dns_path



for (( i=0; i<${length}; i++ ));
do
	
	# Get @MAC
	mac=`ifconfig eth$i | grep ether | awk '{print $2}'`

	# Create ifcg-ethX file
	echo "TYPE=\"Ethernet\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "BOOTPROTO=\"static\"" >> "${ifcfg_path}/ifcfg-eth$i"
	#echo "DEFROUTE=\"yes\"" >> ifcfg-eth$i
	echo "IPV4_FAILURE_FATAL=\"no\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "IPV6INIT=\"no\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "ONBOOT=\"yes\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "HWADDR=\"$mac\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "IPADDR=\"${ip_list[$i]}\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "PREFIX0=\"${prefix_list[$i]}\"" >> "${ifcfg_path}/ifcfg-eth$i"
	echo "NM_CONTROLLED=\"no\"" >> "${ifcfg_path}/ifcfg-eth$i"

done

# Network activation
/bin/systemctl restart network

# Installation SALT agent
echo "Installation salt minion"  >>$logfile
yum install -y --nogpgcheck $salt_pkg
echo "status de l'installation : $?" >>$logfile
echo "master: $salt_master" >> $salt_minion_config_file
systemctl enable salt-minion
#/bin/systemctl start salt-minion



# End of bootstrap reboot instance
echo "Reboot ..." >>$logfile
reboot