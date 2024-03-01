from anytree import LevelOrderIter
from loguru import logger

from alt_prtg import PrtgController
from alt_prtg.models import Device, Node
from snow import SnowController


class RootMismatchException(Exception):
    "Raise when root does not match"

def _sync_groups(expected: Node, current: Node):
    # Update expected tree groups with ID if they exist since
    # SNOW does not store a PRTG group object

    # iterator to get all expected nodes, filtering out device nodes
    expected_groups = LevelOrderIter(expected, filter_=lambda n: not isinstance(n.prtg_obj, Device))
    # iterator to get all current nodes, filtering out device nodes
    current_groups = LevelOrderIter(current, filter_=lambda n: not isinstance(n.prtg_obj, Device))

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

def sync_trees(expected: Node, current: Node, expected_controller: SnowController, current_controller: PrtgController):
    """Synchronize a given tree: (1) add missing devices, (2) remove deactivated devices (not yet unsupported),
    and (3) update device with mismatched details (not yet unsupported)"""

    # Sync group ids
    _sync_groups(expected, current)

    # Add missing devices
    # device is missing if ID is missing
    device_to_add = []
    # map {device_id: node} for quicker access
    current_devices = {node.prtg_obj.id: node for node in LevelOrderIter(current, filter_=lambda n: isinstance(n.prtg_obj, Device))}
    for node in LevelOrderIter(expected, filter_=lambda n: isinstance(n.prtg_obj, Device)):
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
