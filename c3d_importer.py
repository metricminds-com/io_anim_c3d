# ##### BEGIN GPL LICENSE BLOCK #####
#
#  io_anim_c3d is is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# Script copyright (C) Mattias Fredriksson

# pep8 compliancy:
#   flake8 .\c3d_importer.py

import mathutils
import bpy
import os
import numpy as np
from .pyfuncs import islist


def load(operator, context, filepath="",
         use_manual_orientation=False,
         axis_forward='Y',
         axis_up='Z',
         global_scale=1.0,
         create_armature=True,
         bone_shape=True,
         bone_size=0.02,
         resample_frame_rate=False,
         fake_user=True,
         interpolation='BEZIER',
         max_residual=0.0,
         include_event_markers=False,
         include_empty_labels=False,
         apply_label_mask=True,
         print_file=True,
         split_actors=True,
         set_frame_rate=True,
         set_end_frame=True,
         set_playback_mode=True):

    # Load more modules/packages once the importer is used
    from bpy_extras.io_utils import axis_conversion
    from .c3d_parse_dictionary import C3DParseDictionary
    from . perfmon import PerfMon

    # Define the action id from the filename
    file_id = os.path.basename(filepath)
    file_name = os.path.splitext(file_id)[0]

    # Monitor performance
    perfmon = PerfMon()
    perfmon.level_up('Importing: %s ...' % file_id, True)

    unlabeled_armature = None

    # Open file and read .c3d parameter headers
    with C3DParseDictionary(filepath) as parser:
        if print_file:
            parser.print_file()
        if parser.reader.point_used == 0:
            operator.report({'WARNING'}, 'No POINT data in file: %s' % filepath)
            return {'CANCELLED'}
        
        if set_frame_rate:
            bpy.context.scene.render.fps = int(parser.frame_rate)
        if set_end_frame:
            bpy.context.scene.frame_end = parser.last_frame - 1
            bpy.context.scene.frame_start = parser.first_frame
        if set_playback_mode:
            bpy.context.scene.sync_mode = 'FRAME_DROP'

        # Factor converting .
        conv_fac_frame_rate = 1.0
        if resample_frame_rate:
            conv_fac_frame_rate = bpy.context.scene.render.fps / parser.frame_rate

        # Conversion factor for length measurements.
        blend_units = 'm'
        conv_fac_spatial_unit = parser.unit_conversion('POINT', sys_unit=blend_units)

        # World orientation adjustment.
        scale = global_scale * conv_fac_spatial_unit
        if use_manual_orientation:
            global_orient = axis_conversion(from_forward=axis_forward, from_up=axis_up)
            global_orient = global_orient @ mathutils.Matrix.Scale(scale, 3)
            # Convert orientation to a numpy array (3x3 rotation matrix).
            global_orient = np.array(global_orient)
        else:
            global_orient, parsed_screen_param = parser.axis_interpretation([0, 1, 0], [0, 0, 1])
            global_orient *= scale  # Uniformly scale the axis.

            if not parsed_screen_param:
                operator.report({'INFO'}, 'Unable to parse X/Y_SCREEN information for POINT data, ' +
                                          'manual adjustment to orientation may be necessary.')
                
        # Create collection
        collection = bpy.data.collections.new(name=file_name)
        context.scene.collection.children.link(collection)

        # Read labels, remove labels matching hard-coded criteria
        # regarding the software used to generate the file.
        labels = parser.point_labels()

        if apply_label_mask:
            software_mask = parser.generate_label_mask(labels, 'POINT')
        else:
            software_mask = np.ones(np.shape(labels), bool)

        armatures = {}
        if split_actors:
            armatures = get_actor_masks(labels)
        else:
            armatures[file_name] = np.ones(np.shape(labels), bool)

        # Strip actor name from labels
        labels = np.array([item.split(":", 1)[1] if ":" in item else item for item in labels])

        cached_frames = list(parser.reader.read_frames(copy=True))

        # Number of frames [first, last] => +1.
        # first_frame is the frame index to start parsing from.
        # nframes is the number of frames to parse.
        first_frame = parser.first_frame
        nframes = parser.last_frame - first_frame + 1
        perfmon.message('Parsing: %i frames...' % nframes)

        ### NEW: Check if the last frame's 3D point locations are all (0,0,0)
        if cached_frames:
            # Each cached frame is a tuple: (frame_index, points, analog)
            last_frame_points = cached_frames[-1][1]
            if np.allclose(last_frame_points[:, :3], 0.0, atol=1e-6):
                print("Last frame has all zero locations. Skipping its import.")
                cached_frames = cached_frames[:-1]
                if set_end_frame:
                    bpy.context.scene.frame_end = parser.last_frame - 2
                # Note: The scene's frame_end remains as originally set
            nframes = cached_frames[-1][0] - first_frame+ 1

        # Get or create custom bone shape
        custom_bone_shape = get_custom_bone_shape(context, bone_size)

        for armature_name, armature_mask in armatures.items():

            point_mask = np.logical_and(software_mask, armature_mask)

            unique_labels = C3DParseDictionary.make_labels_unique(labels[point_mask])
            # Equivalent to the number of channels used in POINT data.
            nlabels = len(unique_labels)
            if nlabels == 0:
                operator.report({'WARNING'}, 'All POINT data was culled for armature: %s' % armature_name)

            # 1. Create an action to hold keyframe data.
            # 2. Generate location (x,y,z) F-Curves for each label.
            # 3. Format the curve list in sets of 3, each set associate with the x/y/z channels.
            action = create_action(file_name+"."+armature_name, fake_user=fake_user)
            blen_curves_arr = generate_blend_curves(action, unique_labels, 3, 'pose.bones["%s"].location')
            blen_curves = np.array(blen_curves_arr).reshape(nlabels, 3)

            residual_curves = np.array(generate_blend_curves(action, unique_labels, 1, 'pose.bones["%s"]["residual"]'))

            # Load
            read_data(cached_frames, blen_curves, residual_curves, unique_labels, point_mask, global_orient,
                    first_frame, nframes, conv_fac_frame_rate,
                    interpolation, max_residual,
                    perfmon)

            # Remove labels with no valid keyframes.
            if not include_empty_labels:
                clean_empty_fcurves(action)
            # Since we inserted our keyframes in 'FAST' mode, its best to update the fcurves now.
            for fc in action.fcurves:
                fc.update()
            if action.fcurves == 0:
                remove_action(action)
                # All samples were either invalid or was previously culled in regard to the channel label.
                operator.report({'WARNING'}, 'No valid POINT data in file: %s' % filepath)
                return {'CANCELLED'}

            # Parse events in the file (if specified).
            if include_event_markers:
                read_events(operator, parser, action, conv_fac_frame_rate)

            # Create an armature matching keyframed data (if specified).
            arm_obj = None
            bone_radius = bone_size * 0.5
            if create_armature:
                final_labels = [fc_grp.name for fc_grp in action.groups]
                arm_obj = create_armature_object(context, armature_name, 'BBONE')
                if armature_name == "UNLABELED":
                    unlabeled_armature = arm_obj

                collection.objects.link(arm_obj)
                add_empty_armature_bones(context, arm_obj, final_labels, bone_size)

                # Add custom properties to pose bones
                for pose_bone in arm_obj.pose.bones:
                    pose_bone["residual"] = 0

                # Set the width of the bbones.
                for bone in arm_obj.data.bones:
                    bone.bbone_x = bone_radius
                    bone.bbone_z = bone_radius
                    add_driver(arm_obj, bone, 'residual', 'hide', 'residual < 0')

                # Set the created action as active for the armature.
                set_action(arm_obj, action, replace=False)

                if bone_shape: apply_custom_bone_shape(arm_obj, custom_bone_shape)
                
                if action:
                    # Iterate over all the F-Curves in the action
                    for fcurve in action.fcurves:
                        # Iterate over each keyframe point in the F-Curve
                        for keyframe in fcurve.keyframe_points:
                            # Deselect the keyframe
                            keyframe.select_control_point = False
                            keyframe.select_left_handle = False
                            keyframe.select_right_handle = False
                            
                    print("All keyframes deselected.")
                else:
                    print("No action found for the active armature.")

        perfmon.level_down("Import finished.")

        # Metadata
        read_metadata(parser, collection)

        add_filepath(filepath, collection)

        bpy.context.view_layer.update()

        #change_mode('POSE')
        #if unlabeled_armature:
            #unlabeled_armature.hide_set(True)

        return {'FINISHED'}
    
def add_filepath(filepath, collection):
    metadata = None
    for child in collection.children:
        if child.name == "Metadata":
            metadata = child
            break

    if metadata is None:
        print("Metadata collection not found!")
        return

    filepath_obj = bpy.data.objects.new("FILEPATH", None)
    metadata.objects.link(filepath_obj)
    filepath_obj["FILEPATH"] = filepath

def read_metadata(parser, collection):
    metadata = bpy.data.collections.new(name="Metadata")
    collection.children.link(metadata)

    # Timecode
    group = parser.get_group("TIMECODE");
    if group is not None:
        timecode = bpy.data.objects.new("TIMECODE", None)
        metadata.objects.link(timecode)

        timecode["DROP_FRAMES"] = bool(group.get_int8("DROP_FRAMES"))

        field_numbers = group.get("FIELD_NUMBERS").int_array.flatten()
        field_numbers = [int(num) for num in field_numbers]
        timecode["FIELD_NUMBERS"] = field_numbers

        offsets = group.get("OFFSETS").int_array.flatten()
        offsets = [int(num) for num in offsets]
        timecode["OFFSETS"] = offsets

        timecode["STANDARD"] = group.get_string("STANDARD")

        subframesperframe = group.get("SUBFRAMESPERFRAME").int_array.flatten()
        subframesperframe = [int(num) for num in subframesperframe]
        timecode["SUBFRAMESPERFRAME"] = subframesperframe

        timecodes = group.get("TIMECODES").int_array.flatten()
        timecodes = list(map(str, timecodes))
        timecodes = ':'.join(timecodes)
        timecode["TIMECODES"] = timecodes

        timecode["USED"] = bool(group.get_int16("USED"))

def get_actor_masks(labels):
    """
    Generates point masks for each actor based on the labels.

    Args:
    labels: A list of strings in the format "actorName:data_point".

    Returns:
    A dictionary where keys are actor names and values are point masks.
    """
    actor_masks = {}
    actors = get_actors(labels)

    for actor in actors:
        if actor == "UNLABELED":
            point_mask = [":" not in label for label in labels]
        else:
            point_mask = [label.startswith(actor + ":") for label in labels]
        actor_masks[actor] = point_mask

    return actor_masks

def get_actors(labels):
    unique_actors = set()
    for item in labels:
        actor, _ = item.split(":", 1) if ":" in item else ("UNLABELED", item)
        unique_actors.add(actor)
    return unique_actors


def read_events(operator, parser, action, conv_fac_frame_rate):
    ''' Read events from the loaded c3d file and add them as 'pose_markers' to the action.
    '''
    try:
        for (frame, label) in parser.events():
            marker = action.pose_markers.new(label)
            marker.frame = int(np.round(frame * conv_fac_frame_rate))
    except ValueError as e:
        operator.report({'WARNING'}, str(e))
    except TypeError as e:
        operator.report({'WARNING'}, str(e))


def read_data(frames, blen_curves, residual_curves, labels, point_mask, global_orient,
              first_frame, nframes, conv_fac_frame_rate,
              interpolation, max_residual,
              perfmon):
    '''   Read valid POINT data from the file and create action keyframes.
    '''
    nlabels = len(labels)

    # Generate numpy arrays to store POINT data from each frame before creating keyframes.
    point_frames = np.zeros([nframes, 3, nlabels], dtype=np.float32)
    valid_samples = np.empty([nframes, nlabels], dtype=bool)
    residual = np.zeros([nframes, nlabels], dtype=np.float32)

    ##
    # Start reading POINT blocks (and analog, but analog signals from force plates etc. are not supported).
    perfmon.level_up('Reading POINT data..', True)
    for i, points, analog in frames:
        index = i - first_frame
        # Apply masked samples.
        points = points[point_mask]
        # Determine valid samples
        residual[index] = points[:, 3]
        valid = points[:, 3] >= 0.0
        if max_residual > 0.0:
            valid = np.logical_and(points[:, 3] < max_residual, valid)
        valid_samples[index] = valid

        # Extract position coordinates from columns 0:3.
        point_frames[index] = points[:, :3].T

    # Create residual curves
    frame_indices = np.arange(first_frame, first_frame + nframes) * conv_fac_frame_rate
    constant_enum = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items["CONSTANT"].value

    for i, fc in enumerate(residual_curves):
        fc.lock = True # Lock residual curves to prevent manual changes
        keyframe_data = []
        previous_value = None
        for frame_index, value in zip(frame_indices, residual[:, i]):
            if previous_value is None or value != previous_value:
                keyframe_data.append((frame_index, value))
                previous_value = value

        if keyframe_data:
            fc.keyframe_points.add(len(keyframe_data))
            flat_keyframe_data = [item for sublist in keyframe_data for item in sublist]
            fc.keyframe_points.foreach_set('co', flat_keyframe_data)
            fc.keyframe_points.foreach_set('interpolation', [constant_enum] * len(keyframe_data))

    # Re-orient and scale the data.
    point_frames = np.matmul(global_orient, point_frames)

    perfmon.level_down('Reading Done.')

    ##
    # Time to generate keyframes.
    perfmon.level_up('Keyframing POINT data..', True)

    # Number of valid keys for each label.
    nkeys = np.sum(valid_samples, axis=0)
    frame_range = np.arange(0, nframes)

    # Pre-compute frame indices for each label
    frame_indices_all = [frame_range[valid_samples[:, label_ind]] for label_ind in range(len(blen_curves))]

    # Iterate each group (tracker label).
    for label_ind, fc_set in enumerate(blen_curves):
        # Create keyframes.
        nlabel_keys = nkeys[label_ind]
        for fc in fc_set:
            fc.keyframe_points.add(nlabel_keys)

        # Get the frame indices for this label
        frame_indices = frame_indices_all[label_ind]

        # Prepare keyframe data for all dimensions at once
        keyframes = np.empty((nlabel_keys, len(fc_set), 2), dtype=np.float32)
        keyframes[:, :, 0] = frame_indices[:, np.newaxis] * conv_fac_frame_rate

        for dim, fc in enumerate(fc_set):
            keyframes[:, dim, 1] = point_frames[frame_indices, dim, label_ind]

        # Set the keyframe points for each fcurve
        for dim, fc in enumerate(fc_set):
            fc.keyframe_points.foreach_set('co', keyframes[:, dim].ravel())

    # Set interpolation if needed
    if interpolation != 'BEZIER':  # Bezier is default
        for fc_set in blen_curves:
            for fc in fc_set:
                interpolation_enum_arr = [bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items[interpolation].value] * len(fc.keyframe_points)
                fc.keyframe_points.foreach_set('interpolation', interpolation_enum_arr)
                # for kf in fc.keyframe_points:
                #     kf.interpolation = interpolation

    perfmon.level_down('Keyframing Done.')


def create_action(action_name, object=None, fake_user=False):
    ''' Create new action.

    Params:
    -----
    action_name:    Name for the action
    object:         Set the action as the active animation data for the object.
    fake_user:      Set the 'Fake User' flag for the action.
    '''

    action = bpy.data.actions.new(action_name)
    action.use_fake_user = fake_user

    # If none yet assigned, assign this action to id_data.
    if object:
        set_action(object, action, replace=False)
    return action


def remove_action(action):
    ''' Delete a specific action.
    '''
    bpy.data.actions.remove(action)


def set_action(object, action, replace=True):
    ''' Set the action associated with the object.
    -----
    object:    Object for which the animation should be set.
    action:    Action to set for the object.
    replace:   If False, existing action set for the object will not be replaced.
    '''
    if not object.animation_data:
        object.animation_data_create()
    if replace or not object.animation_data.action:
        object.animation_data.action = action


def create_armature_object(context, name, display_type='OCTAHEDRAL'):
    ''' Create an 'ARMATURE' object and add to active layer

    Params:
    -----
    context:        Blender Context
    name:           Name for the object
    display_type:   Display type for the armature bones.
    '''
    arm_data = bpy.data.armatures.new(name=name)
    arm_data.display_type = display_type

    arm_obj = bpy.data.objects.new(name=name, object_data=arm_data)

    return arm_obj

def get_custom_bone_shape(context,bone_size):
    ''' Retrives the custom bone shape or creates it if it does not exist
    '''
    custom_shape_name = "BoneCustomShape"

    custom_shape_collection_name = "CustomShapes"

    # Create a new collection for custom shapes if it doesn't exist
    if custom_shape_collection_name not in bpy.data.collections:
        custom_shape_collection = bpy.data.collections.new(custom_shape_collection_name)
        context.scene.collection.children.link(custom_shape_collection)
    else:
        custom_shape_collection = bpy.data.collections[custom_shape_collection_name]

    # Create a custom shape object if it doesn't exist
    if custom_shape_name not in bpy.data.objects:
        mesh = bpy.data.meshes.new(custom_shape_name)
        custom_shape = bpy.data.objects.new(custom_shape_name, mesh)
        custom_shape_collection.objects.link(custom_shape)

        # Create a simple mesh for the custom shape (e.g., a sphere)
        context.view_layer.objects.active = custom_shape
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.primitive_uv_sphere_add(radius=bone_size * 5, segments=16, ring_count=8)
        bpy.ops.object.mode_set(mode='OBJECT')
    else:
        custom_shape = bpy.data.objects[custom_shape_name]

    # Hide the custom shape collection
    for view_layer in context.scene.view_layers:
        layer_collection = view_layer.layer_collection.children[custom_shape_collection_name]
        layer_collection.exclude = True
    
    return custom_shape

def custom_bone_shape(context, bone_size):
    custom_shape = get_custom_bone_shape(context,bone_size)

    for obj in context.scene.objects:
        if obj.type == 'ARMATURE':
            apply_custom_bone_shape(obj,custom_shape)
            context.view_layer.objects.active = obj # TODO: Fix bug in mm_mocap to remove this line

def apply_custom_bone_shape(armature, custom_shape):
    ''' Assign a custom shape to all bones of the armature
    '''
    with bpy.context.temp_override(active_object=armature, mode='OBJECT'):
        
        shape_scale = 0.08
        for bone in armature.pose.bones:
            bone.custom_shape = custom_shape
            bone.custom_shape_scale_xyz = (shape_scale, shape_scale, shape_scale)
            bone.use_custom_shape_bone_size = False
        
        for bone in armature.data.bones:
            bone.bbone_segments = 1  # B-Bone segments to 1 effectively makes it a stick
            bone.show_wire = False

            bone.color.palette = 'CUSTOM'      
            bone.color.custom.normal = (0.780392, 0.913726, 1)
            bone.color.custom.select = (1, 0.62, 0.16)
            bone.color.custom.active = (1, 1, 0)

        armature.data.display_type = 'STICK'


def change_mode(mode_state):
    ''' Enter object mode and clear any selection.
    '''
    # Try to enter object mode, polling active object is unreliable since an object can be in edit mode but not active!
    try:
        bpy.ops.object.mode_set(mode=mode_state, toggle=False)
        # Clear any selection
        bpy.ops.object.select_all(action='DESELECT')
    except RuntimeError:
        pass


def add_empty_armature_bones(context, arm_obj, bone_names, length=0.1):
    '''
    Generate a set of named bones

    Params:
    ----
    context:    bpy.context
    arm_obj:    Armature object
    length:     Length of each bone.
    '''

    assert arm_obj.type == 'ARMATURE', "Object passed to 'add_empty_armature_bones()' must be an armature."

    # Enter object mode.
    change_mode('OBJECT')
    # Enter edit mode for the armature.
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)

    edit_bones = arm_obj.data.edit_bones

    if not islist(bone_names):
        bone_names = [bone_names]

    for name in bone_names:
        # Create a new bone with name.
        b = edit_bones.new(name)
        b.head = (0.0, 0.0, 0.0)
        b.tail = (0.0, length, 0.0)

    bpy.ops.object.mode_set(mode='OBJECT')


def generate_blend_curves(action, labels, grp_channel_count, fc_data_path_str):
    '''
    Generate F-Curves for the action.

    Parameters
    ----
    action:             bpy.types.Action object to generate F-curves for.
    labels:             String label(s) for generated F-Curves, an action group is generated for each label.
    grp_channel_count:  Number of channels generated for each label (group).
    fc_data_path_str:   Unformated data path string used to define the F-Curve data path. If a string format
                        operator (%s) is contained within the string it will be replaced with the label.

                        Valid args are:
                        ----
                        Object anim:
                        'location', 'scale', 'rotation_quaternion', 'rotation_axis_angle', 'rotation_euler'
                        Bone anim:
                        'pose.bones["%s"].location'
                        'pose.bones["%s"].scale'
                        'pose.bones["%s"].rotation_quaternion'
                        'pose.bones["%s"].rotation_axis_angle'
                        'pose.bones["%s"].rotation_euler'

    '''

    # Convert a single label to an iterable tuple (list).
    if not islist(labels):
        labels = (labels)

    # Generate channels for each label to hold location information.
    if '%s' not in fc_data_path_str:
        # No format operator found in the data_path_str used to define F-curves.
        blen_curves = [action.fcurves.new(fc_data_path_str, index=i, action_group=label)
                       for label in labels for i in range(grp_channel_count)]
    else:
        # Format operator found, replace it with label associated with the created F-Curve.
        blen_curves = [action.fcurves.new(fc_data_path_str % label, index=i, action_group=label)
                       for label in labels for i in range(grp_channel_count)]
    return blen_curves


def clean_empty_fcurves(action):
    '''
    Remove any F-Curve in the action with no keyframes.

    Parameters
    ----
    action:             bpy.types.Action object to clean F-curves.

    '''
    empty_curves = []
    for curve in action.fcurves:
        if len(curve.keyframe_points) == 0:
            empty_curves.append(curve)

    for curve in empty_curves:
        action.fcurves.remove(curve)

def add_driver(armature, bone, source, target, expression):

    driver = bone.driver_add(target).driver
    
    driver.type = 'SCRIPTED'
    
    var = driver.variables.new()
    var.name = 'residual'
    var.targets[0].id_type = 'OBJECT'
    var.targets[0].id = armature
    var.targets[0].data_path = f'pose.bones["{bone.name}"]["{source}"]'
    
    driver.expression = expression