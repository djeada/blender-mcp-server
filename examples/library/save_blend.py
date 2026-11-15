"""Save the current .blend file.

Args:
    filepath (str|None): Path to save to. Default: None (save in place)
        If the file has never been saved and no filepath is given, raises an error.
    compress (bool): Use file compression. Default: True
    relative_remap (bool): Remap relative paths. Default: True

Result:
    filepath (str): Absolute path of the saved file
    compressed (bool): Whether compression was used
"""

import os

import bpy

filepath = args.get("filepath")
compress = args.get("compress", True)
relative_remap = args.get("relative_remap", True)

if filepath:
    abs_path = os.path.abspath(filepath)
    if not abs_path.endswith(".blend"):
        abs_path += ".blend"
    bpy.ops.wm.save_as_mainfile(
        filepath=abs_path,
        compress=compress,
        relative_remap=relative_remap,
    )
else:
    if not bpy.data.filepath:
        raise ValueError("File has never been saved. Provide a 'filepath' argument.")
    bpy.ops.wm.save_mainfile(compress=compress)
    abs_path = bpy.data.filepath

__result__ = {
    "filepath": abs_path,
    "compressed": compress,
}
