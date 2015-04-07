#!/usr/bin/env python


"""
vSphere SDK for Python program for creating  VMs
"""

import atexit
import hashlib
import json

import random
import time

import requests
from pyVim import connect
from pyVmomi import vim

from tools import cli
from tools import tasks

# Disable certicat check
requests.packages.urllib3.disable_warnings()



def get_args():
    """
    Use the tools.cli methods and then add a few more arguments.
    """
    parser = cli.build_arg_parser()

    parser.add_argument('-d', '--datastore',
                        required=True,
                        action='store',
                        help='Name of Datastore to create VM in')

    parser.add_argument('-cs', '--sockets',
                        required=True,
                        action='store',
                        help='Numbers of CPU sockets')

    parser.add_argument('-c', '--cores',
                        required=True,
                        action='store',
                        help='Numbers of core by CPUs sockets')

    parser.add_argument('-m', '--memory',
                        required=True,
                        action='store',
                        help='Memory size in MB')

    parser.add_argument('-n', '--name',
                        required=True,
                        action='store',
                        help='VM name')

    parser.add_argument('-v', '--vlan',
                        required=True,
                        action='store',
                        help='Name of VLAN')

    args = parser.parse_args()

    return cli.prompt_for_password(args)

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


def create_vm(name, service_instance, vm_folder, resource_pool,
                    datastore,memSize, nbSockets, nbCores, vlan):
    """Creates a VirtualMachine.

    :param name: String Name for the VirtualMachine
    :param service_instance: ServiceInstance connection
    :param vm_folder: Folder to place the VirtualMachine in
    :param resource_pool: ResourcePool to place the VirtualMachine in
    :param datastore: DataStrore to place the VirtualMachine on
    :param memSize: Desired size of memory for the VirtualMachine
    :param nbSockets: Desired number of sockets for the VirtualMachine
    :param nbCores: Desired number of core by sockets for the VirtualMachine
    :param vlan: Name of Network to connect the VirtualMachine on

    """
    content = service_instance.RetrieveContent()

    vm_name = name

    dc = get_obj(content, [vim.Datacenter], 'FARMAN')

    datastore_path = '[' + datastore + '] ' + vm_name

    disk_filename = datastore_path + '/' + vm_name + '.vmdk'

    devices = [] 

    adaptermaps = []

    vmx_file = vim.vm.FileInfo(logDirectory=None,
                               snapshotDirectory=None,
                               suspendDirectory=None,
                               vmPathName=datastore_path)

    config = vim.vm.ConfigSpec(name=vm_name, memoryMB=int(memSize), numCPUs=int(nbSockets),
                               numCoresPerSocket=int(nbCores), files=vmx_file, guestId='centos64Guest',
                               version='vmx-10')

    # Configuring network interface
    nic = vim.vm.device.VirtualDeviceSpec()
    nic.operation = vim.vm.device.VirtualDeviceSpec.Operation.add # Add device
    nic.device = vim.vm.device.VirtualVmxnet3() # Define device type
    nic.device.wakeOnLanEnabled = True
    nic.device.addressType = 'assigned' # Vcenter assigne a MAC address
    nic.device.key = 4000  # 4000 seems to be the value to use for a vmxnet3 device
    nic.device.deviceInfo = vim.Description()
    nic.device.deviceInfo.label = "Network Adapter 0"
    nic.device.deviceInfo.summary = vlan
    nic.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
    nic.device.backing.network = get_obj(content, [vim.Network], vlan) # Connect to the correct network
    nic.device.backing.deviceName = vlan # Set name of the interface
    nic.device.backing.useAutoDetect = False
    nic.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
    nic.device.connectable.startConnected = True
    nic.device.connectable.allowGuestControl = True
    devices.append(nic) # Add the nic to the device config


    # Create SCSI controller
    lsi = vim.vm.device.VirtualDeviceSpec()
    lsi.operation = vim.vm.device.VirtualDeviceSpec.Operation.add # Add device
    lsi.device = vim.vm.device.VirtualLsiLogicController() # Define device type
    lsi.device.sharedBus = vim.vm.device.VirtualSCSIController.Sharing.noSharing # Set sharing mode
    lsi.device.scsiCtlrUnitNumber = 0 # Set SCSI Ctrl unit number
    devices.append(lsi) # Add the SCSI controller to the device config


    # Apply change configuration NIC + SCSI controller
    config.deviceChange = devices

    # Vm Creation
    print "Creating VM {}...".format(vm_name)
    task = vm_folder.CreateVM_Task(config=config, pool=resource_pool)
    tasks.wait_for_tasks(service_instance, [task])


    # Create VMDK file
    disk_path = datastore_path + '/' + vm_name + '.vmdk'
    capacity_kb = 1 * 1024 * 1024 # 10Go
    
    disk_manager = content.virtualDiskManager

    disk_spec = vim.VirtualDiskManager.FileBackedVirtualDiskSpec()
    #disk_spec.diskType = 'eagerZeroedThick'
    disk_spec.diskType = 'preallocated'
    disk_spec.adapterType = 'lsiLogic'
    disk_spec.capacityKb = capacity_kb

    # VMDK Creation 
    print "Creating VMDK {}...".format(disk_path)
    task2 = disk_manager.CreateVirtualDisk(disk_path, dc, disk_spec)
    tasks.wait_for_tasks(service_instance, [task2])


    # Connect VMDK  to the VM

    # Get the newly created VM
    vmxfile = datastore_path + '/' + vm_name + '.vmx'
    search = content.searchIndex
    vm = search.FindByDatastorePath(dc, vmxfile)

    # Get controller SCSI  
    controller = None
    devices = vm.config.hardware.device
    for device in devices:
        if 'SCSI' in device.deviceInfo.label:
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
    tasks.wait_for_tasks(service_instance, [task3])
    

    

def main():
    """
    Simple command-line program for creating  VM
    """

    args = get_args()


    service_instance = connect.SmartConnect(host=args.host,
                                            user=args.user,
                                            pwd=args.password,
                                            port=int(args.port))
    if not service_instance:
        print("Could not connect to the specified host using specified "
              "username and password")
        return -1

    atexit.register(connect.Disconnect, service_instance)

    content = service_instance.RetrieveContent()
    datacenter = content.rootFolder.childEntity[0]
    vmfolder = datacenter.vmFolder
    hosts = datacenter.hostFolder.childEntity
    resource_pool = hosts[0].resourcePool


    create_vm(args.name, service_instance, vmfolder, resource_pool, args.datastore, args.memory, args.sockets, args.cores, args.vlan)



# Start program
if __name__ == "__main__":
    main()
