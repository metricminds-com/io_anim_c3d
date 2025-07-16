# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
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
#   flake8 --ignore E402,F821,F722 .\__init__.py

bl_info = {
    "name": "C3D format",
    "author": "Mattias Fredriksson",
    "version": (0, 1, 0),
    "blender": (2, 83, 0),
    "location": "File > Import",
    "description": "Imports C3D Optical Motion Capture (.c3d) files, animated Point Cloud data",
    "warning": "",
    "doc_url": "",
    "tracker_url": "https://github.com/MattiasFredriksson/io_anim_c3d/issues",
    "category": "Import-Export",
}

#######################
# Import & Reload Package
#######################
if "bpy" in locals():
    import importlib
    # Ensure dependency order is correct, to ensure a dependency is updated it must be reloaded first.
    # If imports are done in functions the modules seem to be linked correctly however.
    # ---
    # Reload subdirectory package?
    if "c3d" in locals():
        importlib.reload(c3d)
    # Reload the sub-pacakge modules.
    from .c3d import reload as reload_sub
    reload_sub()
    # ---
    # Reload directory modules.
    if "pyfuncs" in locals():
        importlib.reload(pyfuncs)
    if "perfmon" in locals():
        importlib.reload(perfmon)
    if "c3d_parse_dictionary" in locals():
        importlib.reload(c3d_parse_dictionary)
    if "c3d_importer" in locals():
        importlib.reload(c3d_importer)
    if "c3d_exporter" in locals():
        importlib.reload(c3d_exporter)

import bpy # type: ignore
from bpy.props import ( # type: ignore
    StringProperty,
    BoolProperty,
    IntProperty,
    FloatProperty,
    EnumProperty,
    CollectionProperty,
)
from bpy_extras.io_utils import ( # type: ignore
    ImportHelper,
    # ExportHelper,
    orientation_helper,
)

#######################
# Operator definition
#######################


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportC3D(bpy.types.Operator, ImportHelper):
    """Load a C3D file
    """
    bl_idname = "import_anim.c3d"
    bl_label = "Import C3D"
    bl_options = {'UNDO', 'PRESET'}

    # -----
    # Parameters received from the file selection window through the ImportHelper.
    # -----
    directory: StringProperty() # type: ignore

    # File extesion specification and filter.
    filename_ext = ".c3d"
    filter_glob: StringProperty(default='*' + filename_ext, options={'HIDDEN'}) # type: ignore

    # Properties
    files: CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
    ) # type: ignore

    # -----
    # Primary import settings
    # -----
    fake_user: BoolProperty(
        name="Fake User",
        description="Set the fake user flag for imported action sequence(s) " +
                    "(fake user flag ensures imported sequences will be saved in the .blend file)",
        default=False,
    ) # type: ignore

    include_event_markers: BoolProperty(
        name="Include event markers",
        description="Add labeled events as 'pose markers' to the action sequence. Markers are only visible" +
                    "if the setting: Marker > Show Pose Markers is enabled in the Action Editor",
        default=True,
    ) # type: ignore

    include_empty_labels: BoolProperty(
        name="Include empty labels",
        description="Include channels for POINT labels without valid keyframes",
        default=False,
    ) # type: ignore

    split_actors: BoolProperty(
        name = "Split actors",
        description="Creates armature for each actor or prop",
        default=True,
    )# type: ignore

    # Interpolation settings (link below), there is such thing as to many settings so ignored ones
    # seemingly redundant.
    # https://docs.blender.org/api/current/bpy.types.Keyframe.html#bpy.types.Keyframe.interpolation
    interpolation: EnumProperty(items=(
        ('CONSTANT', "Constant", "Constant (or no interpolation)"),
        ('LINEAR', "Linear", "Linear interpolation"),
        ('BEZIER', "Bezier", "Smooth interpolation between A and B, with some control over curve shape"),
        # ('SINE', "Sinusoidal", "Sinusoidal easing (weakest, almost linear but with a slight curvature)"),
        ('QUAD', "Quadratic", "Quadratic easing"),
        ('CUBIC', "Cubic", "Cubic easing"),
        # ('QUART', "Quartic", "Quartic easing"),
        # ('QUINT', "Quintic", "Quintic easing"),
        ('CIRC', "Circular", "Circular easing (strongest and most dynamic)"),
        # ('BOUNCE', "Bounce", "Exponentially decaying parabolic bounce, like when objects collide"),
        #  Options with specific settings
        # ('BACK', "Back", "Cubic easing with overshoot and settle"),
        # ('ELASTIC', "Elastic", "Exponentially decaying sine wave, like an elastic band"),
    ),
        name="Interpolation",
        description="Keyframe interpolation",
        default='BEZIER'
    ) # type: ignore

    # It should be noted that the standard states two custom representations:
    # 0:  'indicates that the 3D point coordinate is the result of modeling
    #      calculations, interpolation, or filtering'
    # -1: 'is used to indicate that a point is invalid'
    max_residual: FloatProperty(
        name="Max. Residual", default=0.0,
        description="Ignore samples with a residual greater then the specified value. If the value is equal " +
                    "to 0, all valid samples will be included. Not all files record marker residuals",
        min=0., max=1000000.0,
        soft_min=0., soft_max=100.0,
    ) # type: ignore

    # -----
    # Armature settings
    # -----
    create_armature: BoolProperty(
        name="Create Armature",
        description="Generate an armature to display the animated point cloud",
        default=True,
    ) # type: ignore

    bone_shape: BoolProperty(
        name = "Bone Shape",
        description = "Generate sphere shape for bones",
        default=True,
    ) # type: ignore

    bone_size: FloatProperty(
        name="Marker Size", default=0.02,
        description="Define the width of each marker bone",
        min=0.001, max=10.0,
        soft_min=0.01, soft_max=1.0,
    ) # type: ignore

    # -----
    # Transformation settings (included to allow manual modification of spatial data in the loading process).
    # -----
    global_scale: FloatProperty(
        name="Scale",
        description="Scaling factor applied to geometric (spatial) data, multiplied with other embedded factors",
        min=0.001, max=1000.0,
        default=1.0,
    ) # type: ignore

    use_manual_orientation: BoolProperty(
        name="Manual Orientation",
        description="Specify orientation manually rather then use information embedded in the file",
        default=False,
    ) # type: ignore

    # -----
    # Debug settings.
    # -----
    print_file: BoolProperty(
        name="Print metadata",
        description="Print file metadata to console",
        default=False,
    ) # type: ignore

    # -----
    # Frame Rate Settings
    # -----
    resample_frame_rate: BoolProperty(
        name="Resample frame rate",
        description="Adjust keyframes to match the sample rate of the current Blender scene. " +
                    "If False, frames will be inserted in 1 frame increments",
        default=False,
    ) # type: ignore

    set_frame_rate: BoolProperty(
        name="Set frame rate",
        description="Sets the animation frame rate",
        default=True,
    ) # type: ignore

    set_end_frame: BoolProperty(
        name="Set end frame",
        description="Sets the animation timeline end frame",
        default=True,
    ) # type: ignore

    set_playback_mode: BoolProperty(
        name="Set playback sync mode",
        description="Sets the animation playback mode to Frame Drop",
        default=True,
    ) # type: ignore

    def draw(self, context):
        pass

    def invoke(self, context, event):
        # Redraw the 3D View to prevent potential crashes from other addons
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        keywords = self.as_keywords(ignore=("filter_glob", "directory", "ui_tab", "filepath", "files"))

        from . import c3d_importer
        import os

        if self.files:
            failed = []
            for file in self.files:
                path = os.path.join(self.directory, file.name)
                try:
                    msg = c3d_importer.load(self, context, filepath=path, **keywords)
                    if msg != {'FINISHED'}:
                        failed.append(path)
                except Exception as e:
                    import traceback
                    print('')
                    traceback.print_exc()
                    print('')
                    failed.append(path)

            # Report any file issue(s)
            if failed:
                failed_files = ''
                for path in failed:
                    failed_files += '\n' + path
                if len(failed) == len(self.files):
                    self.report(
                        {'ERROR'},
                        'Failed to load any of the .bvh files(s):%s' % failed_files
                        )
                    return {'CANCELLED'}
                else:
                    self.report(
                        {'WARNING'},
                        'Failed loading .bvh files(s):%s' % failed_files
                        )
            return {'FINISHED'}
        else:
            return c3d_importer.load(self, context, filepath=self.filepath, **keywords)
        
# Exporter
@orientation_helper(axis_forward='Y', axis_up='Z')
class ExportC3D(bpy.types.Operator):
    bl_idname = "export_scene.c3d"
    bl_label = "Export C3D"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # type: ignore

    filename_ext = ".c3d"
    filter_glob: StringProperty(default='*' + filename_ext, options={'HIDDEN'})  # type: ignore

    # -----
    # Transformation settings (included to allow manual modification of spatial data in the loading process).
    # -----
    global_scale: FloatProperty(
        name="Scale",
        description="Scaling factor applied to geometric (spatial) data, multiplied with other embedded factors",
        min=0.001, max=1000.0,
        default=1.0,
    ) # type: ignore

    use_manual_orientation: BoolProperty(
        name="Manual Orientation",
        description="Specify orientation manually rather then use blenders defaults",
        default=False,
    ) # type: ignore

    def draw(self, context):
        pass

    def execute(self, context):
        keywords = self.as_keywords(ignore=("filter_glob", "directory", "ui_tab", "filepath", "files", "filename_ext"))

        from . import c3d_exporter
        c3d_exporter.export_c3d(self.filepath, context, **keywords)
        return {'FINISHED'}

    def invoke(self, context, event):
        import os
        if bpy.data.filepath:
            default_path = os.path.splitext(bpy.data.filepath)[0] + self.filename_ext
        else:
            default_path = "untitled" + self.filename_ext
        self.filepath = default_path
        
        # Redraw the 3D View to prevent potential crashes from other addons
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

def menu_func_export(self, context):
    self.layout.operator(ExportC3D.bl_idname, text="C3D (.c3d)")

def register():
    bpy.utils.register_class(ExportC3D)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.utils.unregister_class(ExportC3D)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


#######################
# Panels
######################

## Export

class C3D_PT_export_transform(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Transform"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "EXPORT_SCENE_OT_c3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "global_scale")


class C3D_PT_export_transform_manual_orientation(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Manual Orientation"
    bl_parent_id = "C3D_PT_export_transform"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "EXPORT_SCENE_OT_c3d"

    def draw_header(self, context):
        sfile = context.space_data
        operator = sfile.active_operator

        self.layout.prop(operator, "use_manual_orientation", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.enabled = operator.use_manual_orientation

        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")

## Import

class C3D_PT_action(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Import Action"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "fake_user")
        layout.prop(operator, "include_event_markers")
        layout.prop(operator, "include_empty_labels")
        layout.prop(operator, "interpolation")
        layout.prop(operator, "max_residual")


class C3D_PT_marker_armature(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Create Armature"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw_header(self, context):
        sfile = context.space_data
        operator = sfile.active_operator

        self.layout.prop(operator, "create_armature", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.enabled = operator.create_armature

        layout.prop(operator, "bone_shape")
        layout.prop(operator, "bone_size")
        layout.prop(operator, "split_actors")


class C3D_PT_import_transform(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Transform"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "global_scale")


class C3D_PT_import_transform_manual_orientation(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Manual Orientation"
    bl_parent_id = "C3D_PT_import_transform"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw_header(self, context):
        sfile = context.space_data
        operator = sfile.active_operator

        self.layout.prop(operator, "use_manual_orientation", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.enabled = operator.use_manual_orientation

        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")

class C3D_PT_import_frame_rate(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Frame Rate"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "resample_frame_rate")
        layout.prop(operator, "set_frame_rate")
        layout.prop(operator, "set_end_frame")
        layout.prop(operator, "set_playback_mode")

class C3D_PT_debug(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Console"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_ANIM_OT_c3d"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "print_file")

# This operator is used to display a custom options dialog when dropping a .c3d file.
@orientation_helper(axis_forward='Y', axis_up='Z')
class IMPORT_OT_C3D_DropDialog(bpy.types.Operator):
    bl_idname = "import_anim.c3d_drop_dialog"
    bl_label = "Import C3D Options"

    # File path property – the file dropped will populate this.
    filepath: StringProperty(subtype="FILE_PATH") #type:ignore

    # The following properties mirror those in your original import operator.
    fake_user: BoolProperty(
        name="Fake User",
        description="Set the fake user flag for imported action sequence(s)",
        default=False,
    ) #type:ignore
    include_event_markers: BoolProperty(
        name="Include Event Markers",
        description="Add labeled events as 'pose markers' to the action sequence",
        default=True,
    ) #type:ignore
    include_empty_labels: BoolProperty(
        name="Include Empty Labels",
        description="Include channels for POINT labels without valid keyframes",
        default=False,
    ) #type:ignore
    split_actors: BoolProperty(
        name="Split Actors",
        description="Creates armature for each actor or prop",
        default=True,
    ) #type:ignore
    interpolation: EnumProperty(
        name="Interpolation",
        description="Keyframe interpolation",
        items=(
            ('CONSTANT', "Constant", "No interpolation"),
            ('LINEAR', "Linear", "Linear interpolation"),
            ('BEZIER', "Bezier", "Smooth interpolation"),
            ('QUAD', "Quadratic", "Quadratic easing"),
            ('CUBIC', "Cubic", "Cubic easing"),
            ('CIRC', "Circular", "Circular easing"),
        ),
        default='BEZIER',
    ) #type:ignore
    max_residual: FloatProperty(
        name="Max. Residual",
        description="Ignore samples with a residual greater than this value",
        default=0.0,
        min=0.0,
        max=1000000.0,
    ) #type:ignore
    create_armature: BoolProperty(
        name="Create Armature",
        description="Generate an armature to display the animated point cloud",
        default=True,
    ) #type:ignore
    bone_shape: BoolProperty(
        name="Bone Shape",
        description="Generate sphere shape for bones",
        default=True,
    ) #type:ignore
    bone_size: FloatProperty(
        name="Marker Size",
        description="Define the width of each marker bone",
        default=0.02,
        min=0.001,
        max=10.0,
    ) #type:ignore
    global_scale: FloatProperty(
        name="Scale",
        description="Scaling factor applied to geometric data",
        default=1.0,
        min=0.001,
        max=1000.0,
    ) #type:ignore
    use_manual_orientation: BoolProperty(
        name="Manual Orientation",
        description="Specify orientation manually rather than using file data",
        default=False,
    ) #type:ignore
    print_file: BoolProperty(
        name="Print Metadata",
        description="Print file metadata to console",
        default=False,
    ) #type:ignore
    resample_frame_rate: BoolProperty(
        name="Resample Frame Rate",
        description="Adjust keyframes to match the scene’s sample rate",
        default=False,
    ) #type:ignore
    set_frame_rate: BoolProperty(
        name="Set Frame Rate",
        description="Set the animation frame rate",
        default=True,
    ) #type:ignore
    set_end_frame: BoolProperty(
        name="Set End Frame",
        description="Set the animation timeline end frame",
        default=True,
    ) #type:ignore
    set_playback_mode: BoolProperty(
        name="Set Playback Sync Mode",
        description="Set the animation playback mode to Frame Drop",
        default=True,
    ) #type:ignore

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(self, "fake_user")
        col.prop(self, "include_event_markers")
        col.prop(self, "include_empty_labels")
        col.prop(self, "interpolation")
        col.prop(self, "max_residual")

        box = col.box()
        box.prop(self, "create_armature")
        if self.create_armature:
            box.prop(self, "bone_shape")
            box.prop(self, "bone_size")
            box.prop(self, "split_actors")
        
        layout.prop(self, "global_scale")
        layout.prop(self, "use_manual_orientation")
        if self.use_manual_orientation:
            layout.prop(self, "axis_forward")
            layout.prop(self, "axis_up")

        header, body = layout.panel("group_framerate", default_closed=True)
        header.label(text="Frame Rate")
        if body:
            body.prop(self, "resample_frame_rate")
            body.prop(self, "set_frame_rate")
            body.prop(self, "set_end_frame")
            body.prop(self, "set_playback_mode")

        header, body = layout.panel("group_console", default_closed=True)
        header.label(text="Console")
        if body:
            body.prop(self, "print_file")

        

    def invoke(self, context, event):
        # Redraw the 3D View to prevent potential crashes from other addons
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        # Call the actual import operator, passing these dialog settings.
        # The original operator 'import_anim.c3d' is expected to accept these properties.
        return bpy.ops.import_anim.c3d(
            'EXEC_DEFAULT',
            filepath=self.filepath,
            fake_user=self.fake_user,
            include_event_markers=self.include_event_markers,
            include_empty_labels=self.include_empty_labels,
            split_actors=self.split_actors,
            interpolation=self.interpolation,
            max_residual=self.max_residual,
            create_armature=self.create_armature,
            bone_shape=self.bone_shape,
            bone_size=self.bone_size,
            global_scale=self.global_scale,
            use_manual_orientation=self.use_manual_orientation,
            print_file=self.print_file,
            resample_frame_rate=self.resample_frame_rate,
            set_frame_rate=self.set_frame_rate,
            set_end_frame=self.set_end_frame,
            set_playback_mode=self.set_playback_mode,
        )


# Update the drag-and-drop file handler to use the new operator.
class WM_FH_C3D_PT_drag_and_drop(bpy.types.FileHandler):
    bl_idname = "WM_FH_drag_and_drop"
    bl_label = "Import C3D"
    bl_import_operator = "import_anim.c3d_drop_dialog"
    bl_file_extensions = ".c3d"

    @classmethod
    def poll_drop(cls, context):
        return context.space_data.type == "VIEW_3D"

#######################
# Register Menu Items
#######################


def menu_func_import(self, context):
    self.layout.operator(ImportC3D.bl_idname, text="C3D (.c3d)")

def menu_func_export(self, context):
   self.layout.operator(ExportC3D.bl_idname, text="C3D (.c3d)")

#######################
# Register Operator
#######################


classes = (
    ImportC3D,
    C3D_PT_action,
    C3D_PT_marker_armature,
    C3D_PT_import_transform,
    C3D_PT_import_transform_manual_orientation,
    C3D_PT_import_frame_rate,
    C3D_PT_debug,
    ExportC3D,
    C3D_PT_export_transform,
    C3D_PT_export_transform_manual_orientation,
    IMPORT_OT_C3D_DropDialog,
    WM_FH_C3D_PT_drag_and_drop,
)


def register():
    for cl in classes:
        bpy.utils.register_class(cl)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    for cl in classes:
        bpy.utils.unregister_class(cl)


if __name__ == "__main__":
    register()
