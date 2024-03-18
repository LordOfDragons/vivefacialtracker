"""
MIT License

Copyright DragonDreams GmbH 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import platform
import toga
import toga.style.pack as tp
import numpy as np
import PIL
import cv2 as cv
import traceback
import logging
import asyncio as aio
from camera import FTCamera
from vivetracker import ViveTracker
from enum import Enum
from timeit import default_timer as timer

isLinux = platform.system() == 'Linux'


class SelectionHelper:
    """Helper class for Selection widget."""

    @staticmethod
    def from_enum(enums: Enum) -> dict[int: any]:
        return [dict(title=x.name, value=x) for x in enums]


class TestApp(toga.App):
    class ShowType(Enum):
        YUV = 'yuv'
        Y = 'y'
        U = 'u'
        V = 'v'
        RGB = 'rgb'
        SimulateFix = 'simfix'
        SimulateFixY = 'simfixy'

    def __init__(self: "TestApp") -> None:
        super().__init__(
            formal_name="Test App",
            app_id="ch.dragondreams.enablevivefacialtracker.testapp",
            on_exit=self.on_exit_app)
        self.ftcamera: FTCamera = None
        self.vivetracker: ViveTracker = None
        self.logger = logging.getLogger("evcta.TestApp")

    async def on_switch_enable(self: "TestApp",
                               widget: toga.Switch) -> None:
        if widget.value:
            if self.ftcamera:
                return
            self.view_camera.image = PIL.Image.new("L", (400, 400), 40)
            await self.open_ftcamera()
        else:
            if not self.ftcamera:
                return
            self.view_camera.image = PIL.Image.new("L", (400, 400), 40)
            await self.close_ftcamera()

    async def on_button_test(self: "TestApp",
                             widget: toga.Button) -> None:
        """await self.main_window.info_dialog(
            title="Disable", message="Button pressed")"""
        pass

    async def on_selection_show_change(self: "TestApp",
                                       widget: toga.Selection) -> None:
        pass

    async def on_selection_control_change(self: "TestApp",
                                          widget: toga.Selection) -> None:
        self._set_no_update()
        c = widget.value.value if widget.value else None

        if c and c.type == FTCamera.ControlType.Integer:
            self.sld_control.style.update(**self.style_visible)
        else:
            self.sld_control.style.update(**self.style_hidden)

        if c and c.type == FTCamera.ControlType.Boolean:
            self.chk_control.style.update(**self.style_visible)
        else:
            self.chk_control.style.update(**self.style_hidden)

        if c and c.type == FTCamera.ControlType.Select:
            self.sel_control_sel.style.update(**self.style_visible)
        else:
            self.sel_control_sel.style.update(**self.style_hidden)

        self._update_control_slider(c)
        self._update_control_select(c)
        self._update_control_switch(c)
        self._update_control_info(c)

    def _update_control_slider(self: "TestApp",
                               control: "FTCamera.Control | None") -> None:
        minval = 0
        maxval = 1
        value = 0
        stepsize = 1
        is_writeable = False

        if control and control.type == FTCamera.ControlType.Integer:
            minval = control.minimum
            maxval = control.maximum
            stepsize = control.step
            value = control.value
            is_writeable = control.is_writeable

        stepsize = max(stepsize, 1)
        tickcount = (maxval - minval) // stepsize + 1
        tickcount = max(min(tickcount, 21), 2)

        self.sld_control.min = minval
        self.sld_control.max = maxval
        self.sld_control.tick_count = tickcount
        self.sld_control.value = value
        self.sld_control.enabled = is_writeable

    def _update_control_select(self: "TestApp",
                               control: "FTCamera.Control | None") -> None:
        items = []
        value = None
        is_writeable = False

        if control and control.type == FTCamera.ControlType.Select:
            for k, v in control.choices.items():
                items.append(dict(name=v, value=k))
            value = control.value
            is_writeable = control.is_writeable

        self.sel_control_sel.items = items
        try:
            self.sel_control_sel.value = self.sel_control_sel.items.find(
                dict(value=value))
        except Exception:
            pass
        self.sel_control_sel.enabled = is_writeable

    def _update_control_switch(self: "TestApp",
                               control: "FTCamera.Control | None") -> None:
        value = False
        is_writeable = False

        if control and control.type == FTCamera.ControlType.Boolean:
            value = control.value
            is_writeable = control.is_writeable

        self.chk_control.value = value
        self.chk_control.enabled = is_writeable

    async def on_slider_control_changed(self: "TestApp",
                                        widget: toga.Slider) -> None:
        if self._is_no_update:
            return
        c = self.sel_control.value.value if self.sel_control.value else None
        if c and c.type == FTCamera.ControlType.Integer:
            old_val = c.value
            new_val = widget.value
            if new_val != old_val:
                try:
                    c.value = new_val
                except Exception:
                    self._set_no_update()
                    self._update_control_slider(c)
                    return
        self._update_control_info(c)

    async def on_selection_control_sel_changed(self: "TestApp",
                                               widget: toga.Selection) -> None:
        if self._is_no_update:
            return
        c = self.sel_control.value.value if self.sel_control.value else None
        if c and c.type == FTCamera.ControlType.Select\
                and self.sel_control_sel.value:
            old_val = c.value
            new_val = self.sel_control_sel.value.value
            if new_val != old_val:
                try:
                    c.value = new_val
                except Exception:
                    self._set_no_update()
                    self._update_control_select(c)
                    return
        self._update_control_info(c)

    async def on_switch_control(self: "TestApp",
                                widget: toga.Switch) -> None:
        if self._is_no_update:
            return
        c = self.sel_control.value.value if self.sel_control.value else None
        if c and c.type == FTCamera.ControlType.Boolean:
            old_val = c.value
            new_val = self.chk_control.value
            if new_val != old_val:
                try:
                    c.value = new_val
                except Exception:
                    self._set_no_update()
                    self._update_control_switch(c)
                    return
        self._update_control_info(c)

    async def on_button_controlreset(self: "TestApp",
                                     widget: toga.Button) -> None:
        c = self.sel_control.value.value if self.sel_control.value else None
        if c:
            old_val = c.value
            if c.default != old_val:
                try:
                    c.value = c.default
                finally:
                    self._set_no_update()
                    self._update_control_slider(c)
                    self._update_control_select(c)
                    self._update_control_switch(c)
                    self._update_control_info(c)

    def _update_control_info(self: "TestApp",
                             control: FTCamera.Control | None) -> None:
        if control:
            self.lab_control_info.text = \
                "{}: min={} max={} cur={}".format(
                    control.name, control.minimum, control.maximum,
                    control.value)
        else:
            self.lab_control_info.text = "Control: -"

    async def process_frame(self: "TestApp", data: np.ndarray) -> None:
        if self.vivetracker:
            data = self.vivetracker.process_frame(data)
        match self.sel_show.value.value:
            case TestApp.ShowType.YUV:
                pass
            case TestApp.ShowType.Y:
                data = cv.split(data)[0]
            case TestApp.ShowType.U:
                data = cv.split(data)[1]
            case TestApp.ShowType.V:
                data = cv.split(data)[2]
            case TestApp.ShowType.RGB:
                data = cv.cvtColor(data, cv.COLOR_YUV2RGB)
            case TestApp.ShowType.SimulateFix:
                # simulate opencv fix. the vive tracker delivers the image
                # as YYY. opencv automatically converts this to BGR which
                # is wrong. this convers is then reverted to get back to
                # the YYY but considering it RGB
                data = cv.cvtColor(data, cv.COLOR_YUV2BGR)
                data = cv.cvtColor(data, cv.COLOR_BGR2YUV)
            case TestApp.ShowType.SimulateFixY:
                data = cv.cvtColor(data, cv.COLOR_YUV2BGR)
                data = cv.cvtColor(data, cv.COLOR_BGR2YUV)
                data = cv.split(data)[0]
        image = PIL.Image.fromarray(data)

        if isLinux:
            self.view_camera.image = image
        else:
            def do_it():
                self.view_camera.image = image
            aio.get_event_loop().call_later(0, do_it)

    async def open_ftcamera(self: "TestApp") -> None:
        if self.ftcamera:
            return
        try:
            self.ftcamera = FTCamera(int(self.edit_device.value))
            self.ftcamera.open()
            self.ftcamera.callback_frame = self.process_frame
            self.ftcamera.start_read()
            self.chk_enable.value = True
            self.lab_cam_info.text = "Camera: {}x{} @ {:.1f} ({})".format(
                self.ftcamera.frame_width, self.ftcamera.frame_height,
                self.ftcamera.frame_fps, self.ftcamera.frame_format_description)
            self.sel_control.items = [dict(name=x.name, value=x)
                                      for x in self.ftcamera.controls]
        except Exception:
            self.logger.error(traceback.format_exc())
            await self.close_ftcamera()
            await self.main_window.error_dialog(
                title="Open Device", message="Failed opening device")
            return

        if ViveTracker.is_camera_vive_tracker(self.ftcamera.device):
            try:
                if isLinux:
                    self.vivetracker = ViveTracker(self.ftcamera.device.fileno())
                else:
                    self.vivetracker = ViveTracker(self.ftcamera.device,
                                                   self.ftcamera.device_index)
            except Exception:
                self.logger.error(traceback.format_exc())

    async def close_ftcamera(self: "TestApp") -> None:
        if self.vivetracker:
            self.vivetracker.dispose()
            self.vivetracker = None

        if not self.ftcamera:
            return

        await self.ftcamera.stop_read()
        await self.ftcamera.close()
        self.ftcamera = None
        self.chk_enable.value = False
        self.lab_cam_info.text = "Camera: -"
        self.sel_control.items = []

    def _set_no_update(self: "TestApp") -> None:
        self._timer_no_update = timer()

    @property
    def _is_no_update(self: "TestApp") -> bool:
        if self._timer_no_update:
            if (timer() - self._timer_no_update) < 0.25:
                return True
            self._timer_no_update = None
        return False

    def _reset_no_update(self: "TestApp") -> None:
        self._timer_no_update = False

    def startup(self: "TestApp") -> None:
        self._timer_no_update = None
        content = toga.Box(style=tp.Pack(direction=tp.COLUMN))

        # styles
        self.style_visible = dict(visibility=tp.VISIBLE, height=tp.NONE)
        self.style_hidden = dict(visibility=tp.HIDDEN, height=0)

        # line
        box_line = toga.Box(style=tp.Pack(direction=tp.ROW))
        content.add(box_line)

        self.edit_device = toga.NumberInput(
            min=0, max=15, value=2, style=tp.Pack(flex=1))
        box_line.add(self.edit_device)

        self.chk_enable = toga.Switch(
            "Enable", style=tp.Pack(flex=1), value=False,
            on_change=self.on_switch_enable)
        box_line.add(self.chk_enable)

        self.sel_show = toga.Selection(
            items=SelectionHelper.from_enum(TestApp.ShowType),
            style=tp.Pack(flex=2), accessor="title",
            on_change=self.on_selection_show_change)
        self.sel_show.value = self.sel_show.items.find(
            dict(value=TestApp.ShowType.YUV))
        box_line.add(self.sel_show)

        # line
        box_line = toga.Box(style=tp.Pack(direction=tp.ROW))
        content.add(box_line)

        self.lab_cam_info = toga.Label(
            text="Camera: -", style=tp.Pack(text_align=tp.LEFT))
        box_line.add(self.lab_cam_info)

        # line
        box_line = toga.Box(style=tp.Pack(direction=tp.ROW))
        content.add(box_line)

        self.sel_control = toga.Selection(
            items=[], accessor="name",
            on_change=self.on_selection_control_change)
        box_line.add(self.sel_control)

        sub_box = toga.Box(style=tp.Pack(direction=tp.COLUMN, flex=1))

        self.sld_control = toga.Slider(
            min=0, max=1, value=0, tick_count=2,
            on_change=self.on_slider_control_changed)
        sub_box.add(self.sld_control)

        self.sel_control_sel = toga.Selection(
            items=[], style=tp.Pack(flex=1), accessor="name",
            on_change=self.on_selection_control_sel_changed)
        sub_box.add(self.sel_control_sel)

        self.chk_control = toga.Switch(
            "Activate", style=tp.Pack(flex=1), value=False,
            on_change=self.on_switch_control)
        sub_box.add(self.chk_control)

        box_line.add(sub_box)

        self.btn_reset_control = toga.Button(
            "R", on_press=self.on_button_controlreset)
        box_line.add(self.btn_reset_control)

        # line
        box_line = toga.Box(style=tp.Pack(direction=tp.ROW))
        content.add(box_line)

        self.lab_control_info = toga.Label(
            text="Control: -", style=tp.Pack(text_align=tp.LEFT))
        box_line.add(self.lab_control_info)

        # camera view
        box_view = toga.Box(style=tp.Pack(flex=1))
        box_view.add(toga.Box(style=tp.Pack(flex=1)))
        self.view_camera = toga.ImageView(None, style=tp.Pack(
            width=400, height=400, background_color="#404040",
            padding_top=10, padding_bottom=10))
        box_view.add(self.view_camera)
        box_view.add(toga.Box(style=tp.Pack(flex=1)))
        content.add(box_view)

        # main window
        self.main_window = toga.MainWindow(title="Test App", size=(500, 600))
        self.main_window.content = content
        self.main_window.show()

        # visibility
        self.sld_control.style.update(**self.style_hidden)
        self.sel_control_sel.style.update(**self.style_hidden)
        self.chk_control.style.update(**self.style_hidden)

    @staticmethod
    async def on_exit_app(app: "TestApp") -> bool:
        await app.close_ftcamera()
        return True


def main() -> toga.App:
    logging.basicConfig(filename='testapp.log', filemode='w',
                        encoding='utf-8', level=logging.INFO)
    return TestApp()


if __name__ == "__main__":
    main().main_loop()
