import requests
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl
import atexit
import sys
import time
import argparse
import getpass

# Disable SSL certificats check
requests.packages.urllib3.disable_warnings()

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


def main(**kwargs):
    deploy_settings = dict()
    deploy_settings["vmname"] = kwargs['vmname'].lower()
    deploy_settings['vserver'] = kwargs['vserver']
    deploy_settings['username'] = kwargs['username']
    deploy_settings['password'] = kwargs['password']
    deploy_settings['port'] = kwargs['port']
    deploy_settings['action'] = kwargs['action']
    deploy_settings['snapshot'] = kwargs['snapshot']
    deploy_settings['recursive'] = kwargs['recursive']
    



    # connect to vCenter server
    try:
        si = SmartConnect(host=deploy_settings["vserver"], user=deploy_settings["username"], pwd=deploy_settings["password"], port=int(deploy_settings["port"]))
    except IOError, e:
        sys.exit("Unable to connect to vsphere server. Error message: %s" % e)
        
    # add a clean up routine
    atexit.register(Disconnect, si)
    
    # Get VM object.
    content = si.RetrieveContent()
    vm = si.content.searchIndex.FindByDnsName(None, deploy_settings["vmname"], True)
    

    # Set recursive flag
    if deploy_settings['recursive'] == 'yes':
        recursive = True
    else:
        recursive = False

    if deploy_settings['action'] == 'create':

        date = time.strftime("%d/%m/%Y-%H:%M:%S")
        description ="Snapshot from api %s" %date
        print 'Create snapshot %s from api %s'%(deploy_settings['snapshot'],date)
        task = vm.CreateSnapshot(deploy_settings['snapshot'], description, True, False)
        result = WaitTask(task, 'VM snapshot in progress')

    elif deploy_settings['action'] == 'delete':
        rootSnapshot = vm.snapshot.rootSnapshotList[0]
        if rootSnapshot.name ==  deploy_settings['snapshot'] :
                print "Delete %s"%deploy_settings['snapshot'] 
                task = rootSnapshot.snapshot.RemoveSnapshot_Task(recursive)
                result = WaitTask(task, 'Deleting snapshot')
        
        # Getting throught the snapshot tree
        
        for i in range(0, len(rootSnapshot.childSnapshotList)):
            child = rootSnapshot.childSnapshotList[i]
            if child.name ==  deploy_settings['snapshot'] :
                print "Delete %s"%deploy_settings['snapshot']
                task = child.snapshot.RemoveSnapshot_Task(recursive)
                result = WaitTask(task, 'Deleting snapshot')
            
            while len(child.childSnapshotList) > 0:
                child = child.childSnapshotList[0]
                if child.name ==  deploy_settings['snapshot'] :
                    print "Delete %s"%deploy_settings['snapshot'] 
                    print type(child.snapshot)
                    snapshot = child.snapshot
                    print snapshot
                    task = snapshot.RemoveSnapshot_Task(recursive)
                    result = WaitTask(task, 'Deleting snapshot')
                


    elif deploy_settings['action'] == 'list':
        
        if vm.snapshot is not None:
            rootSnapshot = vm.snapshot.rootSnapshotList[0]
            print "snapshot : %s"%(rootSnapshot.name)
        
            # Getting throught the snapshot tree
            indent = "=="
            for i in range(0, len(rootSnapshot.childSnapshotList)):
                child = rootSnapshot.childSnapshotList[i]
                print "snapshot : %s > %s" %(indent,child.name)
                indent = indent + "=="
                while len(child.childSnapshotList) > 0:
                    child = child.childSnapshotList[0]
                    print "snapshot : %s > %s" %(indent,child.name)
                    indent = indent + "=="

        else:
            print "No snapshot."
    else:
        print "No action"





"""
 Main program
"""
if __name__ == "__main__":

    # Define command line arguments
    parser = argparse.ArgumentParser(description='Create/Delete a snapshot')
    parser.add_argument('--vserver', type=str, help='fqdn or ip addr for the vcenter', required=True)
    parser.add_argument('--username', type=str, help='Username to use for login into vcenter', required=True)
    parser.add_argument('--password', type=str, help='Username password', required=True)
    parser.add_argument('--port', type=int, help='port for vCenter', default=443)
    parser.add_argument('--vmname', type=str, help='Name of VM', required=True)
    parser.add_argument('--action', type=str, help='Action to do : [create|delete|list]', default='create')
    parser.add_argument('--snapshot', type=str, help='Name of snapshot', default='mysnapshot')
    parser.add_argument('--recursive', type=str, help='[yes|no] Recursive delete', default='no')

    
    # Parse arguments and hand off to main()
    args = parser.parse_args()
    main(**vars(args))