bl_info = {
    "name": "WebSocket Auto Import",
    "author": "ahujasid",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > WS Import",
    "description": "Connects to the Camera to 3D relay server and auto-imports GLB/OBJ models",
    "category": "Import-Export",
}

import bpy
import threading
import time
import json
import tempfile
import os
import urllib.request
from urllib.parse import urlparse

from websocket import WebSocketApp

from . import outfit


def download_file(url: str) -> str:
    """Download a file to a temp path and return the file path."""
    # Parse URL to get path component (before query parameters)
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    
    # Determine file extension from path, not full URL
    if path_lower.endswith(".glb"):
        suffix = ".glb"
    elif path_lower.endswith(".obj"):
        suffix = ".obj"
    else:
        suffix = ".glb"  # Default to GLB
    
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    urllib.request.urlretrieve(url, path)
    return path


class WSImportState:
    def __init__(self):
        self.ws_thread = None
        self.ws_app = None
        self.connected = False
        self.queue = []
        self.garments = []  # last outfit sent from the catalogue; re-applied to new avatars

    def start(self, ws_url: str):
        if self.ws_thread and self.ws_thread.is_alive():
            return

        def on_message(_, message):
            print(f"[WSImport] Received message: {message[:200]}...")
            try:
                data = json.loads(message)
                print(f"[WSImport] Parsed JSON: type={data.get('type')}, has_url={bool(data.get('url'))}")
            except Exception as e:
                print(f"[WSImport] JSON parse error: {e}")
                return
            if data.get("type") == "model" and data.get("url"):
                print(f"[WSImport] Queuing model URL: {data['url'][:50]}...")
                self.queue.append(data)
            elif data.get("type") == "outfit":
                print(f"[WSImport] Queuing outfit: {data.get('garments')}")
                self.queue.append(data)

        def on_open(_):
            self.connected = True

        def on_close(_, __, ___):
            self.connected = False

        self.ws_app = WebSocketApp(ws_url, on_message=on_message, on_open=on_open, on_close=on_close)
        self.ws_thread = threading.Thread(target=self.ws_app.run_forever, daemon=True)
        self.ws_thread.start()
        bpy.app.timers.register(self._tick, first_interval=1.0)

    def stop(self):
        if self.ws_app:
            self.ws_app.close()
        self.connected = False
        self.ws_app = None
        self.ws_thread = None
        self.queue.clear()

    def _tick(self):
        if not self.queue:
            return 1.0
        msg = self.queue.pop(0)
        if msg["type"] == "outfit":
            self.garments = [str(g) for g in msg.get("garments") or []]
            self.dress()
            return 0.1

        url = msg["url"]
        print(f"[WSImport] Processing URL: {url[:80]}...")
        try:
            print(f"[WSImport] Downloading from URL...")
            path = download_file(url)
            print(f"[WSImport] Downloaded to: {path}")
            if path.lower().endswith(".glb"):
                print(f"[WSImport] Importing GLB...")
                bpy.ops.import_scene.gltf(filepath=path)
                print(f"[WSImport] ✓ GLB imported successfully!")
            elif path.lower().endswith(".obj"):
                print(f"[WSImport] Importing OBJ...")
                bpy.ops.wm.obj_import(filepath=path)
                print(f"[WSImport] ✓ OBJ imported successfully!")
            # The importer leaves the new objects selected: that's the avatar
            outfit.tag_avatar(bpy.context.selected_objects)
            if self.garments:
                self.dress()
        except Exception as e:
            print(f"[WSImport] ✗ Failed to import {url[:50]}: {e}")
        return 0.1

    def dress(self):
        """Put the current outfit on the avatar (or just undress if it's empty)."""
        try:
            if not self.garments:
                print(f"[WSImport] Removed {outfit.remove_outfit()} garment(s)")
                return
            dressed, skipped = outfit.dress(self.garments)
            print(f"[WSImport] ✓ Dressed avatar in: {', '.join(dressed)}")
            if skipped:
                print(f"[WSImport] ⚠ No 3D pattern for: {', '.join(skipped)}")
        except Exception as e:
            print(f"[WSImport] ✗ Failed to dress avatar: {e}")


state = WSImportState()


class WSImportPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    ws_url: bpy.props.StringProperty(
        name="WebSocket URL",
        default="ws://localhost:8000/ws?client=blender",
        description="WebSocket URL for Blender connection. Use wss:// for ngrok HTTPS, ws:// for local"
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "ws_url")


class WSImportOperator(bpy.types.Operator):
    bl_idname = "wm.ws_auto_import_toggle"
    bl_label = "Toggle WS Auto Import"
    bl_description = "Connect/disconnect WebSocket auto importer"

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        if state.connected:
            state.stop()
            self.report({"INFO"}, "WebSocket import stopped")
        else:
            state.start(prefs.ws_url)
            self.report({"INFO"}, f"Connecting to {prefs.ws_url}")
        return {"FINISHED"}


class WSDressOperator(bpy.types.Operator):
    bl_idname = "wm.ws_dress_avatar"
    bl_label = "Dress Avatar"
    bl_description = "Put the last outfit from the catalogue on the avatar again"

    def execute(self, context):
        if not state.garments:
            self.report({"WARNING"}, "No outfit yet. Press 'Dress in Blender' in the catalogue.")
            return {"CANCELLED"}
        try:
            dressed, skipped = outfit.dress(state.garments)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        note = f" (no 3D pattern for {', '.join(skipped)})" if skipped else ""
        self.report({"INFO"}, f"Dressed in {len(dressed)} garment(s){note}")
        return {"FINISHED"}


class WSUndressOperator(bpy.types.Operator):
    bl_idname = "wm.ws_undress_avatar"
    bl_label = "Remove Outfit"
    bl_description = "Delete the garments from the avatar"

    def execute(self, context):
        self.report({"INFO"}, f"Removed {outfit.remove_outfit()} garment(s)")
        return {"FINISHED"}


class WSFlipOperator(bpy.types.Operator):
    bl_idname = "wm.ws_flip_outfit"
    bl_label = "Flip Front/Back"
    bl_description = "Use if the cape ended up on the avatar's chest: rebuilds the outfit facing the other way"

    def execute(self, context):
        scene = context.scene
        scene[outfit.FLIP_PROP] = not scene.get(outfit.FLIP_PROP, False)
        if state.garments:
            return bpy.ops.wm.ws_dress_avatar()
        return {"FINISHED"}


class WSImportPanel(bpy.types.Panel):
    bl_label = "WS Auto Import"
    bl_idname = "VIEW3D_PT_ws_auto_import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WS Import"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        
        # WebSocket connection
        layout.prop(prefs, "ws_url")
        layout.operator(WSImportOperator.bl_idname, text="Connect/Disconnect")
        
        # Status indicator
        if state.connected:
            layout.label(text="Status: Connected", icon="LINKED")
        else:
            layout.label(text="Status: Disconnected", icon="UNLINKED")

        # Outfit from the catalogue
        box = layout.box()
        box.label(text=f"Outfit: {len(state.garments)} garment(s)", icon="MOD_CLOTH")
        for name in state.garments:
            box.label(text=name)
        row = box.row()
        row.operator(WSDressOperator.bl_idname, text="Dress")
        row.operator(WSUndressOperator.bl_idname, text="Remove")
        box.operator(WSFlipOperator.bl_idname, icon="ARROW_LEFTRIGHT")


classes = (WSImportPreferences, WSImportOperator, WSDressOperator, WSUndressOperator, WSFlipOperator, WSImportPanel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    state.stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

