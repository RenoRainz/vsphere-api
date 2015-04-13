#!/usr/bin/env python

"""

Script to destroy VM instance on vcenter.

Pip requirements:
-----------------
ecdsa==0.10
pycrypto==2.6.1
pyvmomi==5.5.0
wsgiref==0.1.2
"""

import requests
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl
import atexit
import os
import sys
from pprint import pprint, pformat
import argparse
import getpass
from copy import deepcopy
from tools import tasks

# Disable SSL certificats check
requests.packages.urllib3.disable_warnings()


def destroy_vm(**kwargs):

    deploy_settings = dict()
    vm_list = dict()
    deploy_settings['vserver'] = kwargs['vserver']
    deploy_settings['username'] = kwargs['username']
    deploy_settings['password'] = kwargs['password']
    deploy_settings['port'] = kwargs['port']
    deploy_settings['datacenter'] = kwargs['datacenter']



    # Connection to vcenter
    try:
        si = SmartConnect(host=deploy_settings["vserver"], user=deploy_settings["username"], pwd=deploy_settings["password"], port=int(deploy_settings["port"]))
    except IOError, e:
        sys.exit("Unable to connect to vsphere server. Error message: %s" % e)
    
    # Loop on vm name
    for key, vm_name in enumerate(kwargs['vmname']):
    	# Get VM object
    	vm = si.content.searchIndex.FindByDnsName(None, vm_name.lower(), True)

		
    	print("vm found: {0}".format(vm.name))
    	power_state = vm.runtime.powerState
    	print "The current powerState is: "  + power_state

	    # If vm is up
    	if power_state == 'poweredOn':
			print("Attempting to power off {0}".format(vm.name))
			task = vm.PowerOffVM_Task()
			tasks.wait_for_tasks(si, [task])
			print("VM is {0}".format(vm.runtime.powerState))

		# Lauching destruction
    	task2 = vm.Destroy_Task()
    	#task.wait_for_tasks(si, [task2])
    	print "VM " + vm_name +  " is destroyed" 


"""
 Main program
"""
if __name__ == "__main__":
    if getpass.getuser() != 'root':
        sys.exit("You must be root to run this.  Quitting.")

    

    # Define command line arguments
    parser = argparse.ArgumentParser(description='Destroy a VM in vSphere')
    parser.add_argument('--vmname', type=str, help='DNS name of VM', nargs='+', required=True)
    parser.add_argument('--vserver', type=str, help='fqdn or ip addr for the vcenter', required=True)
    parser.add_argument('--username', type=str, help='Username to use for login into vcenter', required=True)
    parser.add_argument('--password', type=str, help='Username password', required=True)
    parser.add_argument('--port', type=int, help='port for vCenter', default=443)
    parser.add_argument('--datacenter', type=str, help='Datacenter in Vcenter', default='MYDC')
    
    # Parse arguments and hand off to main()
    args = parser.parse_args()
    destroy_vm(**vars(args))