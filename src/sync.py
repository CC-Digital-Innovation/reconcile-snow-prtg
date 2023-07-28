from anytree import LevelOrderIter
from loguru import logger

from alt_prtg import PrtgController
from alt_prtg.models import Node
from snow import SnowController

def _sync_groups(expected: Node, current: Node):
    # Update expected tree groups with ID if they exist since
    # SNOW does not store a PRTG group object
    
    # Non-leaf nodes are groups
    expected_groups = LevelOrderIter(expected, filter_=lambda n: not n.is_leaf)
    # map {group_id: node} for quicker access
    current_groups = {node.prtg_obj.name: node for node in LevelOrderIter(current, filter_=lambda n: not n.is_leaf or n.is_root)}
    for node in expected_groups:
        if node.prtg_obj.name in current_groups:
            node.prtg_obj.id = current_groups[node.prtg_obj.name].prtg_obj.id

def sync_trees(expected: Node, current: Node, expected_controller: SnowController, current_controller: PrtgController):
    """Synchronize a given tree: (1) add missing devices, (2) remove deactivated devices (not yet unsupported),
    and (3) update device with mismatched details (not yet unsupported)"""

    # Sync group ids    
    _sync_groups(expected, current)

    # Add missing devices
    # device is missing if ID is missing
    to_add = []
    # map {device_id: node} for quicker access
    current_devices = {node.prtg_obj.id: node for node in current.leaves}
    for node in expected.leaves:
        # add if missing PRTG ID field
        # or if ID exists but not device is found
        if node.prtg_obj.id is None or node.prtg_obj.id not in current_devices:
            to_add.append(node)

    logger.debug(f'Number of devices to add: {len(to_add)}')
    for device_node in to_add:
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
