import anytree
from loguru import logger
from prtg.exception import ObjectNotFound

from alt_prtg import PrtgController
from alt_prtg.models import Device, Node
from snow import SnowController


class RootMismatchException(Exception):
    "Raise when root does not match"


def sync_trees(expected: Node,
               current: Node,
               expected_controller: SnowController,
               current_controller: PrtgController,
               delete: bool = False) -> tuple[list[Device], list[Device]]:
    """Synchronize a given tree: (1) add missing devices, (2) remove deactivated devices (not yet unsupported),
    and (3) update device with mismatched details

    Args:
        expected (Node): tree as expected from ServiceNow
        current (Node): tree as seen from PRTG
        expected_controller (SnowController): controller to update SNOW, only used to update PRTG ID of device
        current_controller (PrtgController): controller to update PRTG structure
        delete (bool): if set to True, deletes inactive devices from current tree

    Returns:
        tuple[list[Device], list[Device]]: list of new devices added and deleted
    """
    current_devices = anytree.findall(current, filter_=lambda n: isinstance(n.prtg_obj, Device))
    expected_devices = anytree.findall(expected, filter_=lambda n: isinstance(n.prtg_obj, Device))

    # sync all devices, counting new devices added
    devices_added = []
    current_devices_ids = {node.prtg_obj.id for node in current_devices}
    for node in expected_devices:
        device = sync_device(node.path, current_controller, expected_controller, root_group=current.prtg_obj)
        if node.prtg_obj.id is None or node.prtg_obj.id not in current_devices_ids:
            devices_added.append(device)
        node.prtg_obj.id = device.id  # update ID before deleting inactive devices

    if not delete:
        return devices_added, []
    # remove inactive or removed devices
    devices_deleted = []
    expected_devices_ids = {node.prtg_obj.id for node in expected_devices}
    for node in current_devices:
        if node.prtg_obj.id in expected_devices_ids:
            continue
        devices_deleted.append(node.prtg_obj)
        current_parent = current_controller.get_parent(node.prtg_obj)
        logger.info(f'Device {node.prtg_obj.name} is no longer considered active. Deleting device...')
        current_controller.delete_object(node.prtg_obj)

        # remove empty parent group(s), if any
        while True:
            groups = current_controller.get_groups(current_parent)
            devices = current_controller.get_devices(current_parent)
            if groups or devices or current_parent.id == current.prtg_obj.id:
                break
            logger.info(f'Previous group is empty. Deleteing group {current_parent.name}...')
            ancestor = current_controller.get_parent(current_parent)
            current_controller.delete_object(current_parent)
            current_parent = ancestor
    return devices_added, devices_deleted


def sync_device(expected_path: tuple[Node], current_controller: PrtgController, expected_controller: SnowController, root_group = None) -> Device:
    """Synchronize a given device: (1) create groups, if necessary, (2) update device details, (3) move device if necessary, 
    and (4) remove last group if empty. If device does not exist, simply create device and any intermediate groups if necessary.

    Args:
        expected (tuple[Node]): tuple of nodes representing path to device and its updated details
        current_controller (PrtgController): controller to interact with platform to sync
        expected_controller (SnowController): controller to update device ID field, only needed if not already created

    Raises:
        ValueError: root group cannot be found
        ValueError: cannot find device with given ID

    Returns:
        Device
    """
    # get expected device
    expected_device_node = expected_path[-1]  # last node is device
    expected_device = expected_device_node.prtg_obj

    # iterate through groups (exclude device)
    expected_node_iter = iter(expected_path[:-1])

    # require root node to exist
    root_node = next(expected_node_iter)
    # skip querying root if passed
    if root_group:
        root = root_group
    else:
        try:
            root = current_controller.get_group_by_name(root_node.prtg_obj.name)
        except ValueError:
            # could be a probe
            try:
                root = current_controller.get_probe_by_name(root_node.prtg_obj.name)
            except ValueError:
                raise RootMismatchException(f'Cannot find expected root group/probe named "{root_node.prtg_obj.name}".')

    # (1) create any intermediate (non-root) groups as necessary
    groups_to_create = []
    # initialize first group that exists, i.e. root
    existing_group = root
    # find first missing group, if any
    for node in expected_node_iter:
        groups = current_controller.get_groups_by_name(node.prtg_obj.name)
        # groups can have duplicate names. ensure unique group by its parent ID
        try:
            group = next((group for group in groups if existing_group.id == current_controller.get_parent(group).id))
        except StopIteration:
            groups_to_create.append(node.prtg_obj)
            # add the rest of missing groups, if any. This will naturally break out of outer for loop
            groups_to_create.extend([node.prtg_obj for node in expected_node_iter])
        else:
            existing_group = group
    # create intermediate groups, if any
    # replace existing_group variable for when moving device
    for group in groups_to_create:
        logger.info(f'Adding missing, intermediate group {group.name} to {existing_group.name}...')
        new_group = current_controller.add_group(group, existing_group)
        existing_group = new_group

    # get parent group, remove ID if mismatch
    if expected_device.id is not None:
        try:
            current_parent = current_controller.get_parent(expected_device)
        except ObjectNotFound:
            logger.info(f'Cannot find device {expected_device.ci.name} with ID {expected_device.id}. Removing ID...')
            expected_device.id = None

    # simply create device if it does not exist or if ID mismatch
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

        # (4) remove parent group(s) if empty
        while True:
            groups = current_controller.get_groups(current_parent)
            devices = current_controller.get_devices(current_parent)
            if groups or devices or current_parent.id == root.id:
                break
            logger.info(f'Previous group is empty. Deleteing group {current_parent.name}...')
            ancestor = current_controller.get_parent(current_parent)
            current_controller.delete_object(current_parent)
            current_parent = ancestor
    # return updated device (new current device)
    return current_controller.get_device(expected_device.id)
