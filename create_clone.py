#!/usr/bin/env python
"""

Script to create VM instance on vcenter.

Pip requirements:
-----------------
ecdsa==0.10
netaddr==0.7.10
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
import time
from netaddr import IPNetwork, IPAddress
import argparse
import getpass
from copy import deepcopy
from tools import tasks

# Disable certicat check
requests.packages.urllib3.disable_warnings()

"""
 Waits and provides updates on a vSphere task
"""
def WaitTask(task, actionName='job', hideResult=False):
    #print 'Waiting for %s to complete.' % actionName
    
    while task.info.state == vim.TaskInfo.State.running:
       time.sleep(2)
    
    if task.info.state == vim.TaskInfo.State.success:
       if task.info.result is not None and not hideResult:
          out = '%s completed successfully, result: %s' % (actionName, task.info.result)
       else:
          out = '%s completed successfully.' % actionName
    else:
       out = '%s did not complete successfully: %s' % (actionName, task.info.error)
       print out
       raise task.info.error # should be a Fault... check XXX
    
    # may not always be applicable, but can't hurt.
    return task.info.result

"""
 Get the vsphere object associated with a given text name
"""
def get_obj(content, vimtype, name):
    obj = None
    container = content.viewManager.CreateContainerView(content.rootFolder, vimtype, True)
    for c in container.view:
        if c.name == name:
            obj = c
            break
    return obj


"""
 Connect to vCenter server and deploy a VM from template
"""
def clone(deploy_settings, vlans_settings):
    fqdn = "%s.%s" % (deploy_settings["new_vm_name"],deploy_settings["domain"])

    # connect to vCenter server
    try:
        si = SmartConnect(host=deploy_settings["vserver"], user=deploy_settings["username"], pwd=deploy_settings["password"], port=int(deploy_settings["port"]))
    except IOError, e:
        sys.exit("Unable to connect to vsphere server. Error message: %s" % e)
        
    # add a clean up routine
    atexit.register(Disconnect, si)
    
    content = si.RetrieveContent()

    # get the vSphere objects associated with the human-friendly labels we supply
    datacenter = get_obj(content, [vim.Datacenter], deploy_settings["datacenter"])
    
    # get the folder where VMs are kept for this datacenter
    destfolder = datacenter.vmFolder

    # Create datastore path
    datastore_path = '[' + deploy_settings["datastore"] + '] ' + deploy_settings["new_vm_name"]
    
    cluster = get_obj(content, [vim.ClusterComputeResource], deploy_settings["cluster"])
    resource_pool = cluster.resourcePool # use same root resource pool that my desired cluster uses
    datastore = get_obj(content, [vim.Datastore], deploy_settings["datastore"])
    template_vm = get_obj(content, [vim.VirtualMachine], deploy_settings["template_name"])

    # Relocation spec
    relospec = vim.vm.RelocateSpec()
    relospec.datastore = datastore
    relospec.pool = resource_pool

    '''
     Networking config for VM
    '''
    devices = [] 
    adaptermaps = []

    
    # create a Network device for each VLANs
    for key, ip in enumerate(vlans_settings):

        nic = vim.vm.device.VirtualDeviceSpec()
        nic.operation = vim.vm.device.VirtualDeviceSpec.Operation.add  # or edit if a device exists
        nic.device = vim.vm.device.VirtualVmxnet3()
        nic.device.wakeOnLanEnabled = True
        nic.device.addressType = 'assigned'
        nic.device.key = 4000  # 4000 seems to be the value to use for a vmxnet3 device
        nic.device.deviceInfo = vim.Description()
        nic.device.deviceInfo.label = "Network Adapter %s" % key
        nic.device.deviceInfo.summary = vlans_settings[key]
        
        # Connect virtual adapter 
        nic.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic.device.connectable.startConnected = True
        nic.device.connectable.allowGuestControl = True

        # Get distributed virtual portgroup obj
        pg = get_obj(content, [vim.dvs.DistributedVirtualPortgroup], vlans_settings[key])

        # Get connection information about connection between DVS and PorGroup
        dvs_port_connection = vim.dvs.PortConnection()
        dvs_port_connection.portgroupKey= pg.key
        dvs_port_connection.switchUuid= pg.config.distributedVirtualSwitch.uuid
        nic.device.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
        nic.device.backing.port = dvs_port_connection    
        
        # Add NIC spec to the device    
        devices.append(nic)

    
    # VM config spec
    vmconf = vim.vm.ConfigSpec()
    vmconf.numCPUs = deploy_settings['cpus']
    vmconf.memoryMB = deploy_settings['mem']
    vmconf.cpuHotAddEnabled = True
    vmconf.memoryHotAddEnabled = True
    vmconf.deviceChange = devices

    # Clone spec
    clonespec = vim.vm.CloneSpec()
    clonespec.location = relospec
    clonespec.config = vmconf
    clonespec.powerOn = True
    clonespec.template = False

    # Launch the clone task
    print "Creating VM {}...".format(deploy_settings["new_vm_name"])
    task = template_vm.Clone(folder=destfolder, name=deploy_settings["new_vm_name"], spec=clonespec)
    result = WaitTask(task, 'VM clone task')

    # Once clone is created, we create additionals disks

    for key, size in enumerate(deploy_settings['disks']):
        if int(size) > 0:
            
            # Create VMDK file
            disk_filename = datastore_path + '/' + deploy_settings["new_vm_name"] + '-' + str(key + 1) + '.vmdk'
            capacity_kb = int(size) * 1024 * 1024 # Size in arg is in GB 

            disk_manager = content.virtualDiskManager

            disk_spec = vim.VirtualDiskManager.FileBackedVirtualDiskSpec()
            #disk_spec.diskType = 'eagerZeroedThick'
            disk_spec.diskType = 'preallocated'
            disk_spec.adapterType = 'lsiLogic'
            disk_spec.capacityKb = capacity_kb

            # VMDK Creation 
            print "Creating VMDK {}...".format(disk_filename)
            task2 = disk_manager.CreateVirtualDisk(disk_filename, datacenter, disk_spec)
            tasks.wait_for_tasks(si, [task2])

            # Connect additionals disks  to the VM

            # Get the newly created VM
            vmxfile = datastore_path + '/' + deploy_settings["new_vm_name"] + '.vmx'
            search = content.searchIndex
            vm = search.FindByDatastorePath(datacenter, vmxfile)

            # Get controller SCSI  
            controller = None
            devices = vm.config.hardware.device
            for device in devices:
                if 'SCSI controller 0' in device.deviceInfo.label:
                    controller = device

            # Define the disk
            disk = vim.vm.device.VirtualDisk()
            disk.backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
            disk.backing.diskMode = 'persistent'
            disk.backing.thinProvisioned = False
            #disk.backing.eagerlyScrub = True
            disk.backing.eagerlyScrub = False
            disk.backing.fileName = disk_filename

            disk.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
            disk.connectable.startConnected = True
            disk.connectable.allowGuestControl = False
            disk.connectable.connected = True

            disk.key = -100
            disk.controllerKey = controller.key # id of scsi controller
            disk.unitNumber = len(controller.device) # number of SCSI device
            
            
            # Create disk's spec
            device_spec = vim.vm.device.VirtualDiskSpec()
            device_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
            device_spec.device = disk

            spec = vim.vm.ConfigSpec()
            spec.deviceChange = [device_spec]

            # Reconfigure VM 
            task3 = vm.ReconfigVM_Task(spec)
            tasks.wait_for_tasks(si, [task3])

    # Now customization of guest using a bootstrap script
    # We suppose bootstrap file is generated before 
    # We have to copy this file into the VM 
    # Then we execute it.

    print "VM "+ vm.name + " is created."

    bootstrap_file = '/scripts/vmware/vm-bootstrap.bash'

    # Sleep during the vm tools booting.
    print "Wait during VM tools starting ..."
    time.sleep(25)

    # Call upload file function
    print "Starting customization"
    bootstrap(si, datacenter, bootstrap_file, '/tmp/bootstrap.bash', vmxfile, 'root', 'password')

def bootstrap(si, datacenter, upload_file, upload_file_path, vmxfile, vm_user, vm_pwd):
    """
    Function uploading a file from host to guest
    And execute bootstrap file
    """

    # Upload file

    try:
        content = si.RetrieveContent()
        search = content.searchIndex
       
        vm = search.FindByDatastorePath(datacenter, vmxfile)

        tools_status = vm.guest.toolsStatus
        if (tools_status == 'toolsNotInstalled' or
                tools_status == 'toolsNotRunning'):
            raise SystemExit(
                "VMwareTools is either not running or not installed. "
                "Rerun the script after verifying that VMWareTools "
                "is running")

        creds = vim.vm.guest.NamePasswordAuthentication(
            username=vm_user, password=vm_pwd)
        with open(upload_file, 'r') as myfile:
            args = myfile.read()

        try:
            file_attribute = vim.vm.guest.FileManager.FileAttributes()
            url = content.guestOperationsManager.fileManager.InitiateFileTransferToGuest(vm, creds, upload_file_path, file_attribute, len(args), True)
            resp = requests.put(url, data=args, verify=False)
            if not resp.status_code == 200:
                print "Error while uploading file"
            else:
                print "customization in progress"
        except IOError, e:
            print e
    except vmodl.MethodFault as error:
        print "Caught vmodl fault : " + error.msg
        return -1

    # Excute uploaded file
    bootstrap = vim.vm.guest.ProcessManager.ProgramSpec(arguments='start', programPath='/etc/init.d/bootstrap')
    bootstrap_pid = si.content.guestOperationsManager.processManager.StartProgramInGuest(vm=vm, auth=creds, spec=bootstrap)

    time.sleep(20)
    print "Customization done, " + vm.name + " is ready."

    return 0


def main(**kwargs):
    deploy_settings = dict()
    deploy_settings["new_vm_name"] = kwargs['hostname'].lower()
    deploy_settings['cpus'] = kwargs['cpus']
    deploy_settings['mem'] = kwargs['mem'] * 1024
    deploy_settings['template_name'] = kwargs['template']
    deploy_settings['domain'] = kwargs['domain']
    deploy_settings['vserver'] = kwargs['vserver']
    deploy_settings['username'] = kwargs['username']
    deploy_settings['password'] = kwargs['password']
    deploy_settings['port'] = kwargs['port']
    deploy_settings['datacenter'] = kwargs['datacenter']
    deploy_settings['cluster'] = kwargs['cluster']
    deploy_settings['datastore'] = kwargs['datastore']
    deploy_settings['vlans'] = kwargs['vlans']
    deploy_settings['dns'] = kwargs['dns']
    deploy_settings['disks'] = kwargs['disks']


    # initialize a list to hold our network settings
    ip_settings = list()
    netmask_settings = list()
    vlans_settings = list()

    '''
    Get settings for each VLANs given
    '''
 
    for key, vlan in enumerate(kwargs['vlans']):
        vlans_settings.append(vlan)

    # clone template to a new VM with our specified settings
    clone(deploy_settings, vlans_settings)

"""
 Main program
"""
if __name__ == "__main__":
    if getpass.getuser() != 'root':
        sys.exit("You must be root to run this.  Quitting.")

    

    # Define command line arguments
    parser = argparse.ArgumentParser(description='Deploy a new VM in vSphere')
    parser.add_argument('--template', type=str, help='VMware template to clone', default='Centos7-x86')
    parser.add_argument('--hostname', type=str, required=True, help='New host name',)
    parser.add_argument('--vlans', type=str, help='VLAN labels for NIC, separated by a space', nargs='+', required=True)
    parser.add_argument('--cpus', type=int, help='Number of CPUs', default=1)
    parser.add_argument('--mem', type=int, help='Memory in GB', default=1)
    parser.add_argument('--domain', type=str, help='domain name', default='prod.dmd')
    parser.add_argument('--vserver', type=str, help='fqdn or ip addr for the vcenter', required=True)
    parser.add_argument('--username', type=str, help='Username to use for login into vcenter', required=True)
    parser.add_argument('--password', type=str, help='Username password', required=True)
    parser.add_argument('--port', type=int, help='port for vCenter', default=443)
    parser.add_argument('--datacenter', type=str, help='Datacenter in Vcenter', default='MyDC')
    parser.add_argument('--cluster', type=str, help='Cluster in Vcenter', default='prod')
    parser.add_argument('--datastore', type=str, help='Datastore for the VM', default='svc1_esx_poc-55')
    parser.add_argument('--dns', type=str, help='Dns server for the VM', default='192.168.139.1')
    parser.add_argument('--disks', type=str, help='Size in GB for additional disk, separated by a space', nargs='+', default='0')
    
    # Parse arguments and hand off to main()
    args = parser.parse_args()
    main(**vars(args))