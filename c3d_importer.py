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
         axis_forward='-Z',
         axis_up='Y',
         global_scale=1.0,
         create_armature=True,
         bone_size=0.02,
         resample_frame_rate=False,
         fake_user=True,
         interpolation='LINEAR',
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
            bpy.context.scene.frame_end = parser.last_frame
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
            global_orient, parsed_screen_param = parser.axis_interpretation([0, 0, 1], [0, 1, 0])
            global_orient *= scale  # Uniformly scale the axis.

            if not parsed_screen_param:
                operator.report({'INFO'}, 'Unable to parse X/Y_SCREEN information for POINT data, ' +
                                          'manual adjustment to orientation may be necessary.')

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

        for armature_name, armature_mask in armatures.items():

            point_mask = np.logical_and(software_mask, armature_mask)

            unique_labels = C3DParseDictionary.make_labels_unique(labels[point_mask])
            # Equivalent to the number of channels used in POINT data.
            nlabels = len(unique_labels)
            if nlabels == 0:
                operator.report({'WARNING'}, 'All POINT data was culled for armature: %s' % armature_name)

            # Number of frames [first, last] => +1.
            # first_frame is the frame index to start parsing from.
            # nframes is the number of frames to parse.
            first_frame = parser.first_frame
            nframes = parser.last_frame - first_frame + 1
            perfmon.message('Parsing: %i frames...' % nframes)

            # 1. Create an action to hold keyframe data.
            # 2. Generate location (x,y,z) F-Curves for each label.
            # 3. Format the curve list in sets of 3, each set associate with the x/y/z channels.
            action = create_action(file_name+"."+armature_name, fake_user=fake_user)
            blen_curves_arr = generate_blend_curves(action, unique_labels, 3, 'pose.bones["%s"].location')
            blen_curves = np.array(blen_curves_arr).reshape(nlabels, 3)

            # Load
            read_data(parser, blen_curves, unique_labels, point_mask, global_orient,
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
            bone_radius = bone_size * 0.5 * 100
            if create_armature:
                final_labels = [fc_grp.name for fc_grp in action.groups]
                arm_obj = create_armature_object(context, armature_name, 'STICK')
                add_empty_armature_bones(context, arm_obj, final_labels, bone_size)

                # Create a custom bone shape (sphere) with the appropriate size
                bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
                sphere = bpy.context.object
                sphere.name = "Bone_Sphere"

                # Scale the sphere to match the desired bone size
                sphere.scale = (bone_radius, bone_radius, bone_radius)
                bpy.ops.object.transform_apply(scale=True)

                # Move the sphere to the appropriate location for the custom bone shape
                bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS', center='BOUNDS')

                # Switch to pose mode to set the custom shape
                bpy.context.view_layer.objects.active = arm_obj
                bpy.ops.object.mode_set(mode='POSE')

                # Assign the custom bone shape to each pose bone in the armature
                for pbone in arm_obj.pose.bones:
                    pbone.custom_shape = sphere
                    pbone.bone.show_wire = False

                # Switch back to object mode
                bpy.ops.object.mode_set(mode='OBJECT')

                # Hide the template sphere in the viewport and disable render visibility
                sphere.hide_set(True)
                sphere.hide_render = True
                sphere.hide_viewport = True

                # Set the created action as active for the armature.
                set_action(arm_obj, action, replace=False)

        perfmon.level_down("Import finished.")

        bpy.context.view_layer.update()

        change_mode('POSE')
        hide_object("UNLABELED")

        return {'FINISHED'}

# Function to hide an armature in the viewport
def hide_object(object_name):
    # Ensure the object exists
    if object_name in bpy.data.objects:
        obj = bpy.data.objects[object_name]
        # Hide the object in the viewport
        obj.hide_set(True)
        print(f"Object '{object_name}' has been hidden in the viewport.")
    else:
        print(f"Object '{object_name}' does not exist.")
        
    bpy.context.view_layer.update()

def get_actor_masks(labels):
    """
    Generates point masks for each actor based on the labels.

    Args:
    labels: A list of strings in the format "actorName:data_point".

    Returns:
    A dictionary where keys are actor names and values are point masks.
    """
    actor_masks = {}

    for item in labels:
        actor, _ = item.split(":", 1) if ":" in item else ("UNLABELED", item)

        if actor not in actor_masks:
            # Create a point mask for this actor
            if actor == "UNLABELED":
                point_mask = [":" not in label for label in labels]
            else:
                point_mask = [label.startswith(actor + ":") for label in labels]
            actor_masks[actor] = point_mask

    return actor_masks

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


def read_data(parser, blen_curves, labels, point_mask, global_orient,
              first_frame, nframes, conv_fac_frame_rate,
              interpolation, max_residual,
              perfmon):
    '''   Read valid POINT data from the file and create action keyframes.
    '''
    nlabels = len(labels)

    # Generate numpy arrays to store POINT data from each frame before creating keyframes.
    point_frames = np.zeros([nframes, 3, nlabels], dtype=np.float32)
    valid_samples = np.empty([nframes, nlabels], dtype=bool)

    ##
    # Start reading POINT blocks (and analog, but analog signals from force plates etc. are not supported).
    perfmon.level_up('Reading POINT data..', True)
    for i, points, analog in parser.reader.read_frames(copy=False):
        index = i - first_frame
        # Apply masked samples.
        points = points[point_mask]
        # Determine valid samples
        valid = points[:, 3] >= 0.0
        if max_residual > 0.0:
            valid = np.logical_and(points[:, 3] < max_residual, valid)
        valid_samples[index] = valid

        # Extract position coordinates from columns 0:3.
        point_frames[index] = points[:, :3].T

    # Re-orient and scale the data.
    point_frames = np.matmul(global_orient, point_frames)

    perfmon.level_down('Reading Done.')

    ##
    # Time to generate keyframes.
    perfmon.level_up('Keyframing POINT data..', True)
    # Number of valid keys for each label.
    nkeys = np.sum(valid_samples, axis=0)
    frame_range = np.arange(0, nframes)
    # Iterate each group (tracker label).
    for label_ind, fc_set in enumerate(blen_curves):
        # Create keyframes.
        nlabel_keys = nkeys[label_ind]
        for fc in fc_set:
            fc.keyframe_points.add(nlabel_keys)

        # Iterate valid frames and insert keyframes.
        frame_indices = frame_range[valid_samples[:, label_ind]]

        for dim, fc in enumerate(fc_set):
            keyframes = np.empty((nlabel_keys, 2), dtype=np.float32)
            keyframes[:, 0] = frame_indices * conv_fac_frame_rate
            keyframes[:, 1] = point_frames[frame_indices, dim, label_ind]
            fc.keyframe_points.foreach_set('co', keyframes.ravel())

    if interpolation != 'BEZIER':  # Bezier is default
        for label_ind, fc_set in enumerate(blen_curves):
            for fc in fc_set:
                for kf in fc.keyframe_points:
                    kf.interpolation = interpolation

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

    # Instance in scene.
    context.view_layer.active_layer_collection.collection.objects.link(arm_obj)
    return arm_obj


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
        b.tail = (0.0, 0.0, length)

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

def create_hidden_sphere(name="Bone_Sphere", radius=1):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, 0))
    sphere = bpy.context.object
    sphere.name = name
    
    # Move the sphere to a new hidden collection
    hidden_collection = bpy.data.collections.get("Hidden Objects")
    if not hidden_collection:
        hidden_collection = bpy.data.collections.new("Hidden Objects")
        bpy.context.scene.collection.children.link(hidden_collection)
    
    # Unlink the sphere from the original collection and link it to the hidden collection
    bpy.context.scene.collection.objects.unlink(sphere)
    hidden_collection.objects.link(sphere)

    # Hide the sphere in the viewport and render
    sphere.hide_set(True)
    sphere.hide_render = True
    
    return sphere
