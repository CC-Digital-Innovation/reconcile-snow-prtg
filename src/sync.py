import anytree
from loguru import logger
from prtg.exception import ObjectNotFound

from alt_prtg import PrtgController
from alt_prtg.models import Device, Node
from snow import SnowController


class RootMismatchException(Exception):
    "Raise when root does not match"

def _sync_groups(expected: Node, current: Node):
    """ServiceNow does not store a PRTG group object so they are instantiated 
    with no ID. This function compares existing groups and updates the expected 
    tree with populated IDs.

    Args:
        expected (Node): expected tree node as viewed from ServiceNow
        current (Node): current tree node as viewed from PRTG

    Raises:
        RootMismatchException: when root name and/or ID input does not match 
        the expected root
    """
    # iterator to get all expected nodes, filtering out device nodes
    expected_groups = anytree.LevelOrderIter(expected, filter_=lambda n: not isinstance(n.prtg_obj, Device))
    # iterator to get all current nodes, filtering out device nodes
    current_groups = anytree.LevelOrderIter(current, filter_=lambda n: not isinstance(n.prtg_obj, Device))

    # expected root group is short and could match multiple groups
    # grab and compare root first
    expected_root = next(expected_groups)
    current_root = next(current_groups)

    # confirm root matches
    if not current_root.prtg_obj.name.startswith(expected_root.prtg_obj.name):
        raise RootMismatchException(f'PRTG root \"{current_root.prtg_obj.name}\" does not start with \"{expected_root.prtg_obj.name}\".')
    # set expected root group id
    expected_root.prtg_obj.id = current_root.prtg_obj.id

    # map {group_id: node} for quicker access
    current_groups_map = {node.prtg_obj.name: node for node in current_groups}
    # update non-root group ids
    for node in expected_groups:
        # compare groups by name
        # current group name must as least start with expected group name
        group_name = next((name for name in current_groups_map.keys() if name.startswith(node.prtg_obj.name)), None)
        if group_name is not None:
            node.prtg_obj.id = current_groups_map.pop(group_name).prtg_obj.id

def sync_trees(expected: Node, current: Node, expected_controller: SnowController, current_controller: PrtgController) -> list[Device]:
    """Synchronize a given tree: (1) add missing devices, (2) remove deactivated devices (not yet unsupported),
    and (3) update device with mismatched details (not yet unsupported)

    Args:
        expected (Node): tree as expected from ServiceNow
        current (Node): tree as seen from PRTG
        expected_controller (SnowController): controller to update SNOW, only used to update PRTG ID of device
        current_controller (PrtgController): controller to update PRTG structure

    Returns:
        list[Device]: list of new devices added
    """

    # Sync group ids
    _sync_groups(expected, current)

    # Add missing devices
    # device is missing if ID is missing
    device_to_add = []
    # map {device_id: node} for quicker access
    current_devices = {node.prtg_obj.id: node for node in anytree.LevelOrderIter(current, filter_=lambda n: isinstance(n.prtg_obj, Device))}
    for node in anytree.LevelOrderIter(expected, filter_=lambda n: isinstance(n.prtg_obj, Device)):
        # add if missing PRTG ID field
        # or if ID exists but not device is found
        if node.prtg_obj.id is None or node.prtg_obj.id not in current_devices:
            device_to_add.append(node)

    logger.debug(f'Number of devices to add: {len(device_to_add)}')
    for device_node in device_to_add:
        logger.info(f'Adding device {device_node.prtg_obj.name}...')
        try:
            new_device = current_controller.add_device(device_node.prtg_obj, device_node.parent.prtg_obj)
        except ValueError:
            # Parent node does not have an ID, i.e. group is missing
            groups_to_add = [device_node.parent]
            # Find the closest, existing ancestor and push any missing groups to stack
            # This ensures creating groups in proper order
            # Index slice excludes the root, parent of leaf, and leaf node
            for node in reversed(device_node.path[1:-2]):
                if node.prtg_obj.id is not None:
                    break
                groups_to_add.append(node)
            # Create groups
            for group_node in reversed(groups_to_add):
                logger.info(f'Adding group {group_node.prtg_obj.name} to {group_node.parent.prtg_obj.name}...')
                new_group = current_controller.add_group(group_node.prtg_obj, group_node.parent.prtg_obj)
                # Update node's group ID
                group_node.prtg_obj.id = new_group.id
                logger.info(f'Created group {new_group.name}')
            new_device = current_controller.add_device(device_node.prtg_obj, device_node.parent.prtg_obj)
        logger.info(f'Created device {new_device.name}')
        # Update node's device ID
        device_node.prtg_obj.id = new_device.id
        # Update prtg ID record in SNOW
        device_node.prtg_obj.ci.prtg_id = new_device.id
        expected_controller.update_config_item(device_node.prtg_obj.ci)
    return [node.prtg_obj for node in device_to_add]


def sync_device(expected: Node, current_controller: PrtgController, expected_controller: SnowController) -> Device:
    """Synchronize a given device: (1) create groups, if necessary, (2) update device details, (3) move device if necessary, 
    and (4) remove last group if empty. If device does not exist, simply create device and any intermediate groups if necessary.

    Args:
        expected (Node): tree representing path to device and its updated details
        current_controller (PrtgController): controller to interact with platform to sync
        expected_controller (SnowController): controller to update device ID field, only needed if not already created

    Raises:
        ValueError: root group cannot be found
        ValueError: cannot find device with given ID

    Returns:
        Device
    """
    # get expected device
    expected_device_node = anytree.search.find(expected, filter_=lambda n: isinstance(n.prtg_obj, Device))
    expected_device = expected_device_node.prtg_obj

    # check for device ID match early to avoid creating groups first
    if expected_device.id is not None:
        try:
            _, current_parent = current_controller.get_device(expected_device.id, get_parent=True)  # do not need current device details
        except ObjectNotFound:
            raise ValueError(f'Cannot find device {expected_device.ci.name} with ID {expected_device.id}.')

    # iterate through groups (exclude device)
    expected_node_iter = anytree.LevelOrderIter(expected, filter_=lambda n: not isinstance(n.prtg_obj, Device))
    
    # require root node to exist
    root_node = next(expected_node_iter)
    root = current_controller.get_group_by_name(root_node.prtg_obj.name)
    existing_group = root

    # (1) create any intermediate (non-root) groups as necessary
    groups_to_create = []
    # find first missing group, if any
    for node in expected_node_iter:
        try:
            existing_group = current_controller.get_group_by_name(node.prtg_obj.name)
        except ValueError:
            groups_to_create.append(node.prtg_obj)
            # break early because subsequent groups may match incorrect sub groups,
            # i.e., 'Prod -> Server' could match with 'DR -> Server'
            break
    # add the rest of missing groups, if any
    groups_to_create.extend([node.prtg_obj for node in expected_node_iter])
    # create intermediate groups, if any
    # replace existing_group variable for when moving device
    for group in groups_to_create:
        logger.info(f'Adding missing, intermediate group {group.name} to {existing_group.name}...')
        new_group = current_controller.add_group(group, existing_group)
        existing_group = new_group

    # simply create device if it does not exist
    if expected_device.id is None:
        logger.info(f'ID not found for device {expected_device.name}. Creating new device {expected_device.name}...')
        new_device = current_controller.add_device(expected_device, existing_group)
        expected_device.ci.prtg_id = new_device.id
        expected_controller.update_config_item(expected_device.ci)
        return new_device

    # (2) update device details
    logger.info(f'Updating {expected_device.name} details...')
    current_controller.update_device(expected_device)

    # (3) move device if necessary
    if current_parent.id != existing_group.id:
        logger.info(f'Device {expected_device.name} is in incorrect group. Moving to {existing_group.name}...')
        current_controller.move_object(expected_device, existing_group)

        # (4) remove last empty group if empty
        groups = current_controller.get_groups(current_parent)
        devices = current_controller.get_devices(current_parent)
        if not groups and not devices:
            logger.info(f'Previous group is empty. Deleteing group {current_parent.name}...')
            current_controller.delete_object(current_parent)
    # return updated device (new current device)
    return current_controller.get_device(expected_device.id)
