# io_anim_c3d
Blender add-on for importing and exporting .c3d motion capture files.

This is the [metricminds](https://www.metricminds.com) fork of
[io_anim_c3d](https://github.com/MattiasFredriksson/io_anim_c3d) by
**Mattias Fredriksson**, who authored the original importer and the
underlying [py-c3d](https://github.com/MattiasFredriksson/py-c3d) parser -
all credit for the foundation goes to him. We use this add-on in our
motion capture pipeline and maintain the fork on the `metricminds` branch
(the `main` branch mirrors the upstream repository).

# Features added in this fork

- **C3D export** (File > Export > C3D): writes marker animation back to .c3d,
  with point labels, selectable export scope (all or selected armatures),
  unit scale conversion, axis orientation settings and timecode metadata.
- **Actor splitting**: subjects in a multi-actor file import as separate
  armatures instead of one merged marker cloud.
- **Residual import**: each marker's residual is imported as an extra channel,
  and drivers hide markers automatically on frames where they carry no valid
  data.
- **Drag and drop**: dropping a .c3d into the viewport opens the import
  dialog (with undo support).
- **Robust parameter parsing**: reads files whose declared parameter section
  size is wrong (written by some capture software), which previously lost
  parameters such as POINT:UNITS and silently broke the automatic unit
  conversion.
- **Frame rate options**: the scene frame rate can be set from the file or
  kept, and the scene frame range adapts to the imported data.
- Quality-of-life: one collection per imported file, timecode and
  manufacturer metadata round-trip, marker display shapes, faster import of
  large files, current Blender releases supported (4.x / 5.x).

# How to Install

Download
-------
This repository uses a git submodule for the c3d parser, so the GitHub
"Download ZIP" button does **not** produce a working add-on. Clone instead:

    git clone --recurse-submodules https://github.com/metricminds-com/io_anim_c3d.git

Then zip the `io_anim_c3d` folder (or copy it directly into a Blender add-on
folder).

Install from Blender
-------
1. Open Blender
2. Open the Edit->Preferences window.
3. Go to the 'Add-ons' tab.
4. Click the 'Install...' button.
5. Navigate to the folder containing the .zip file and double-click the file.
6. Enable the addon 'Import-Export: C3D format' in the addon window.

Install in a Blender add-on folder
-------
1. Move the 'io_anim_c3d' folder to an add-on folder used by Blender.
2. Go to the Add-on section in the Edit->Preferences menu.
3. Enable the addon named Import-Export: C3D format (or search the Import-Export add-on section).
4. Not there? Use the refresh button, restart blender, google how to install add-ons or visit [docs.blender.org](https://docs.blender.org/manual/en/latest/editors/preferences/addons.html).

# How to Use

Import
-------
1. Go to File->Import->C3D (.c3d) to open the import window, or drag a .c3d
   file into the viewport.
2. Change the import settings (if needed).
3. Navigate to the folder containing the .c3d file, and...
    1. Double-click to import a single file or
    2. Select file(s) to import and click the 'Import C3D' button.

Export
-------
1. Select the marker armature(s) to export.
2. Go to File->Export->C3D (.c3d), choose the export scope, orientation and
   scale, and click 'Export C3D'.
