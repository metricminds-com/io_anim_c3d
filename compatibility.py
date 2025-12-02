import bpy

def is_blender_5_or_newer():
    return bpy.app.version >= (5, 0, 0)

def get_slot(action):
    """
    Helper to get or create the first slot of an action.
    """
    if len(action.slots) == 0:
        print(f"[DEBUG] Creating new slot for action {action.name} with type 'OBJECT'")
        # Blender 5.0+: ActionSlots.new(id_type, name)
        # Using 'OBJECT' as we are animating pose.bones (Object level).
        return action.slots.new("OBJECT", "Slot")
    return action.slots[0]

def get_fcurves(action):
    """
    Returns the fcurves collection for the given action.
    Handles Blender 5.0+ channelbag API.
    """
    if is_blender_5_or_newer():
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot
        slot = get_slot(action)
        try:
            channelbag = action_ensure_channelbag_for_slot(action, slot)
            return channelbag.fcurves
        except Exception as e:
            print(f"[ERROR] Failed to get channelbag for slot {slot}: {e}")
            raise e
    else:
        return action.fcurves

def get_groups(action):
    """
    Returns the groups collection for the given action.
    Handles Blender 5.0+ channelbag API.
    """
    if is_blender_5_or_newer():
        from bpy_extras.anim_utils import action_ensure_channelbag_for_slot
        slot = get_slot(action)
        channelbag = action_ensure_channelbag_for_slot(action, slot)
        return channelbag.groups
    else:
        return action.groups

def create_fcurve(action, data_path, index=0, group=None):
    """
    Creates a new fcurve on the action.
    Handles 'action_group' vs 'group_name' argument change.
    """
    fcurves = get_fcurves(action)
    
    try:
        if is_blender_5_or_newer():
            # Blender 5.0+: use group_name
            fc = fcurves.new(data_path, index=index, group_name=group)
        else:
            # Legacy: use action_group
            fc = fcurves.new(data_path, index=index, action_group=group)
        # print(f"[DEBUG] Created F-Curve: {data_path} [{index}]")
        return fc
    except Exception as e:
        print(f"[ERROR] Failed to create F-Curve {data_path}: {e}")
        raise e

def remove_fcurve(action, fcurve):
    """
    Removes an fcurve from the action.
    """
    fcurves = get_fcurves(action)
    fcurves.remove(fcurve)
