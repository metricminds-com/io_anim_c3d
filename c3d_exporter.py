import os
import mathutils
import numpy as np
from .c3d.c3d import Writer
from . perfmon import PerfMon
import bpy

def get_bone_name(data_path: str) -> str:
    return data_path.split('"')[1]

def get_full_bone_name(armature, fcurve : bpy.types.FCurve) -> str:
    if armature.name == "UNLABELED":
        return get_bone_name(fcurve.data_path)
    else:
        return f"{armature.name}:{get_bone_name(fcurve.data_path)}"

# MODIFIED: Added 'export_scope' parameter
def export_c3d(filepath, context, 
            export_scope='ALL',
            export_timecode=True,
            use_manual_orientation = False,
            axis_forward='-Y',
            axis_up='Z',
            global_scale=1.0):
    
    from bpy_extras.io_utils import axis_conversion

    perfmon = PerfMon()
    perfmon.level_up(f'Exporting: {filepath}', True)

    # Get the scene data from Blender
    scene = context.scene
    frame_start = scene.frame_start
    frame_end = scene.frame_end+1
    frame_rate = scene.render.fps

    writer = Writer(frame_rate,0)
    
    # --- NEW: Determine which objects to export based on the scope ---
    objects_to_export = []
    if export_scope == 'ALL':
        objects_to_export = scene.objects
    elif export_scope == 'SELECTED':
        objects_to_export = context.selected_objects
    # ----------------------------------------------------------------

    perfmon.level_up(f'Collecting labels', True)
    #Initialize a list of bone names to keep track of the order of bones
    labels = []

    # MODIFIED: Use the filtered 'objects_to_export' list
    for obj in objects_to_export:
        if obj.type == 'ARMATURE' and obj.animation_data is not None and obj.animation_data.action is not None:
            for fcu in obj.animation_data.action.fcurves:
                labels.append(get_full_bone_name(obj, fcu))

    if not labels:
        print("Export C3D: No valid armatures found for export. Aborting.")
        perfmon.level_down("Export finished with no data.")
        return {'CANCELLED'}

    labels = list(dict.fromkeys(labels))
    label_count = len(labels)
    labels = list(labels)

    perfmon.level_down(f'Collecting labels finished')
    perfmon.level_up(f'Collecting frame data', True)

    # Create frames data structure and fill it with default values
    frame_count = frame_end-frame_start

    points = np.zeros((label_count, 5), np.float32)
    points[:, 3] = -1  # Set residual to -1
    keyframes = np.array([points.copy() for _ in range(frame_count)])

    # Process each object in the scene
    # MODIFIED: Use the filtered 'objects_to_export' list
    for obj in objects_to_export:
        if obj.type != 'ARMATURE' or obj.animation_data is None or obj.animation_data.action is None:
            continue
        for fcu in obj.animation_data.action.fcurves:
            if not fcu.data_path.endswith('.location'): continue
            
            full_bone_name = get_full_bone_name(obj, fcu)
            if full_bone_name not in labels: continue # Ensure bone belongs to the collected labels
            
            bone_index = labels.index(full_bone_name)

            for kp in fcu.keyframe_points:
                frame_index = int(kp.co[0]) - frame_start
                if 0 <= frame_index < frame_count:
                    # Fill in points with keyframe value at the appropriate position
                    keyframes[frame_index][bone_index, fcu.array_index] = kp.co[1]
                    keyframes[frame_index][bone_index, 3] = 0 # Set residual
        perfmon.step(f"Collected data from {obj.name} Armature")

    perfmon.level_down(f'Collecting frame data finished')
    perfmon.level_up(f'Applying transformation', True)

    # Scale and orientation
    unit_scale = get_unit_scale(scene) * 1000 # Convert to millimeters TODO: Add unit setting
    scale = global_scale * unit_scale

    # Orient and scale point data
    if use_manual_orientation:
        global_orient = axis_conversion(from_forward='Y', from_up='Z', to_forward=axis_forward, to_up=axis_up)
    else:
        global_orient = axis_conversion('Y', 'Z', '-Y', 'Z') # Mirrors default import orientation

    global_orient = global_orient @ mathutils.Matrix.Scale(scale, 3)
    # Convert orientation to a numpy array (3x3 rotation matrix).
    global_orient = np.array(global_orient)
    keyframes[..., :3] = keyframes[..., :3] @ global_orient.T

    analog = np.zeros((0, 0), dtype=np.float32)
    frames = [(keyframes[i], analog) for i in range(frame_count)]

    perfmon.level_down(f'Transformations applied')

    writer.add_frames(frames)

    writer.set_point_labels(labels)
    # writer.set_analog_labels([])

    perfmon.level_up(f'Write metadata', True)

    # This function call handles writing TIMECODE and MANUFACTURER info
    write_metadata(writer, export_timecode=export_timecode)
    perfmon.level_down(f'Done writing metadata')

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Save the C3D file
    with open(filepath, 'w+b') as f:
        writer.write(f, write_analog=False)

    perfmon.level_down("Export finished.")
    return {'FINISHED'}


def write_metadata(writer, collection_name="Metadata", export_timecode=True):
    # Find the Metadata collection
    metadata_collection = bpy.data.collections.get(collection_name)

    if metadata_collection is None:
        print(f"Info: Metadata collection '{collection_name}' not found. Skipping metadata export.")
        # Still write manufacturer info even if metadata collection isn't there
        write_manufacturer(writer)
        return
    
    write_manufacturer(writer)

    if not export_timecode:
        return
    # This function is responsible for exporting the TIMECODE data
    write_timecode(writer, metadata_collection)

def write_manufacturer(writer):
    manufacturer = writer.get_create("MANUFACTURER")
    manufacturer.add_str("COMPANY", "", "Blender Foundation")
    manufacturer.add_str("SOFTWARE", "", "Blender")
    version = bpy.app.version
    version_str = f"{version[0]}.{version[1]}.{version[2]}"
    manufacturer.add_str("VERSION_LABEL", "", version_str)

def write_timecode(writer, metadata_collection):
    # Find the timecode object in the Metadata collection
    timecode_object = metadata_collection.objects.get("TIMECODE")

    if timecode_object is None:
        print("Info: TIMECODE object not found in the Metadata collection. Skipping timecode export.")
        return

    print("Exporting TIMECODE metadata...")
    group = writer.get_create("TIMECODE")

    # Write DROP_FRAMES as a signed 8-bit integer
    group.add('DROP_FRAMES', 'Does the timecode drop frames?', 1, '<b', int(timecode_object.get("DROP_FRAMES", 0)))

    # Write FIELD_NUMBERS as an array of signed 16-bit integers
    field_numbers = np.array(timecode_object.get("FIELD_NUMBERS", []), dtype=np.int16).reshape(-1, 1)
    group.add_array('FIELD_NUMBERS', 'Field numbers', field_numbers)

    # Write OFFSETS as an array of signed 16-bit integers
    offsets = np.array(timecode_object.get("OFFSETS", []), dtype=np.int16).reshape(-1, 1)
    group.add_array('OFFSETS', 'Offsets', offsets)

    # Write STANDARD as a string
    group.add_str('STANDARD', 'Timecode standard', timecode_object.get("STANDARD", "SMPTE"))

    # Write SUBFRAMESPERFRAME as an array of signed 16-bit integers
    subframes = np.array(timecode_object.get("SUBFRAMESPERFRAME", []), dtype=np.int16).reshape(-1, 1)
    group.add_array('SUBFRAMESPERFRAME', 'Subframes per frame', subframes)

    # Write TIMECODES as an array of signed 16-bit integers
    timecodes_str = timecode_object.get("TIMECODES", "0:0:0:0")
    timecodes_list = list(map(int, timecodes_str.split(':')))
    timecodes = np.array(timecodes_list, dtype=np.int16).reshape(-1, 1)
    group.add_array('TIMECODES', 'Timecodes', timecodes)

    # Write USED as a signed 16-bit integer
    group.add('USED', 'Is the timecode used?', 2, '<h', int(timecode_object.get("USED", 0)))

def get_unit_scale(scene):
    # Determine the unit scale to convert to meters
    unit_settings = scene.unit_settings
    if unit_settings.system == 'METRIC':
        return unit_settings.scale_length
    elif unit_settings.system == 'IMPERIAL':
        # 1 foot = 0.3048 meters. The scale_length is in feet for imperial.
        return unit_settings.scale_length * 0.3048
    else:
        # Default to Blender Units (meters)
        return unit_settings.scale_length