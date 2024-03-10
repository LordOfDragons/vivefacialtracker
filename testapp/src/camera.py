import numpy as np
import PIL
import v4l2py as v4l
import v4l2py.device as v4ld
import asyncio as aio
import cv2 as cv
import traceback
import time
import logging
from enum import Enum


class FTCamera:
    """Opens a camera grabbing frames as numpy arrays."""
    class ControlType(Enum):
        """Type of the control."""
        Integer = 'int'
        Boolean = 'bool'
        Select = 'select'

    class Control:
        """Control defined by the hardware."""
        def __init__(self: "FTCamera.ControlInfo",
                     control: v4ld.BaseControl) -> None:
            self._control = control
            self.name = control.name
            self.type = None
            self.minimum: int = 0
            self.maximum: int = 0
            self.step: int = 1
            self.default: int = 0
            self.clipping: bool = False
            self.choices: dict[int: str] = {}
            match control.type:
                case v4ld.ControlType.INTEGER:
                    self.type = FTCamera.ControlType.Integer
                    self.minimum = control.minimum
                    self.maximum = control.maximum
                    self.step = control.step
                    self.default = control.default
                    self.clipping = control.clipping
                case v4ld.ControlType.BOOLEAN:
                    self.type = FTCamera.ControlType.Boolean
                    self.default = control.default

                case v4ld.ControlType.MENU:
                    self.type = FTCamera.ControlType.Select
                    self.choices = dict(control.data)
                    self.default = control.default

        @property
        def value(self: "FTCamera.ControlInfo") -> int | bool:
            return self._control.value

        @value.setter
        def value(self: "FTCamera.ControlInfo", new_value: int | bool):
            self._control.value = new_value

        @property
        def is_writeable(self: "FTCamera.ControlInfo") -> bool:
            return self._control.is_writeable

    _logger = logging.getLogger("evcta.FTCamera")

    def __init__(self: "FTCamera", index: int) -> None:
        """Create camera grabber.

        The camera is not yet opened. Set "callback_frame" then call
        "open()" to open the device and "start_read()" to start capturing.

        Keyword arguments:
        index -- Index of the camera. Under Linux this uses the device
                 file "/dev/video{index}".
        """
        self._index: int = index
        self._device: v4l.Device = None
        self._task_read: aio.Task = None
        self._arr_data: np.ndarray = None
        self._arr_c2: np.ndarray = None
        self._arr_c3: np.ndarray = None
        self._arr_merge: np.ndarray = None

        self.callback_frame = None
        """Callback to send captured frame data to.

        Has to be a callable object with the signature
        "callback(data: np.ndarray) -> None". If callback_frame
        is None no image is grabbed nor processed.

        The image send to the callback is a numpy array of shape
        (height, width, 3). Channel format is YUV.

        Callback function can be changed while capturing.
        """

    def open(self: "FTCamera") -> None:
        """Open device if closed.

        This opens the device using Video4Linux. Finds frame size and
        format to use. Also finds all supported controls.

        This method does not start recording.

        Throws "Exception" if:
        - Device can not be found
        - Device can not be opened
        - Device has no format supporting capturing
        - Device has no YUV format
        - Device has no size with YUV format and at least 30 frame rate
        """
        if self._device:
            return
        FTCamera.logger.info("FTCamera.open: index {}".format(self._index))
        self._device = v4l.Device.from_id(self._index)
        self._device.open()
        self._find_format()
        self._find_frame_size()
        self._set_frame_format()
        self._init_arrays()
        self._find_controls()

    def _find_format(self: "FTCamera") -> None:
        """Logs all formats supported by camera and picks best one.

        Picks the first format which is YUV and supports capturing.

        Throws "Exception" if no suitable format is found.
        """
        FTCamera.logger.info("formats:")
        for x in self._device.info.formats:
            FTCamera.logger.info("- {}".format(x))
        self._format = next(x for x in self._device.info.formats
                            if x.pixel_format == v4l.PixelFormat.YUYV
                            and x.type == v4ld.BufferType.VIDEO_CAPTURE)
        FTCamera.logger.info("using format: {}".format(self._format))

    def _find_frame_size(self: "FTCamera") -> None:
        """Logs all sizes supported by camera and picks best one.

        Picks the first size with YUV format and a minimum FPS of 30.

        Throws "Exception" if no suitable size is found.
        """
        FTCamera.logger.info("sizes:")
        for x in self._device.info.frame_sizes:
            FTCamera.logger.info("- {}".format(x))
        self._frame_size = next(x for x in self._device.info.frame_sizes
                                if x.pixel_format == v4l.PixelFormat.YUYV
                                and x.min_fps >= 30)
        FTCamera.logger.info("using frame size : {}".format(self._frame_size))
        self._frame_width = self._frame_size.width
        self._frame_height = self._frame_size.height
        self._pixel_count = self._frame_width * self._frame_height
        self._half_pixel_count = self._pixel_count // 2
        self._half_frame_width = self._frame_width // 2
        self._half_frame_height = self._frame_height // 2

    def _set_frame_format(self: "FTCamera") -> None:
        """Activates the found format and size."""
        self._device.set_format(
            buffer_type=v4ld.BufferType.VIDEO_CAPTURE,
            width=self._frame_size.width,
            height=self._frame_size.height,
            pixel_format=self._format.pixel_format)

    def _init_arrays(self: "FTCamera") -> None:
        """Create numpy arrays to fill during capturing."""
        self._arr_data = np.zeros([self._pixel_count * 2], dtype=np.uint8)
        self._arr_merge = np.zeros([self._pixel_count, 3], dtype=np.uint8)
        self._arr_c2 = np.empty((self._half_pixel_count), np.uint8)
        self._arr_c3 = np.empty((self._half_pixel_count), np.uint8)

    def _find_controls(self: "FTCamera") -> None:
        """Logs all controls and stores them for use."""
        self._controls: "list[FRCamera.Control]" = []
        FTCamera.logger.info("controls:")
        for x in self._device.controls.values():
            FTCamera.logger.info("- {}".format(x))
            control = FTCamera.Control(x)
            if not control.type:
                continue
            self._controls.append(control)

    @property
    def device(self: "FTCamera") -> v4l.Device:
        """Video4Linux device if open or None if closed."""
        return self._device

    @property
    def frame_width(self: "FTCamera") -> int:
        """Width in pixels of captured frames.

        Only valid if device is open."""
        return self._frame_width

    @property
    def frame_height(self: "FTCamera") -> int:
        """Height in pixels of captured frames.

        Only valid if device is open."""
        return self._frame_height

    @property
    def frame_fps(self: "FTCamera") -> float:
        """Capture frame rate.

        Only valid if device is open."""
        return float(self._frame_size.min_fps)

    @property
    def frame_format(self: "FTCamera") -> str:
        """Capture pixel format.

        Only valid if device is open."""
        return self._frame_size.pixel_format.name

    @property
    def frame_format_description(self: "FTCamera") -> str:
        """Capture pixel format description.

        Only valid if device is open."""
        return self._format.description

    @property
    def controls(self: "FTCamera") -> "list[FTCamera.Control]":
        """List of all supported controls.

        Only valid if device is open."""
        return self._controls

    async def close(self: "FTCamera") -> None:
        """Closes the device if open.

        If capturing stops capturing first.
        """
        await self.stop_read()
        if not self._device:
            return
        FTCamera.logger.info("FTCamera.close: index {}".format(self._index))
        try:
            self._device.close()
        except Exception:
            pass
        self._device = None

    def start_read(self: "FTCamera") -> None:
        """Start capturing frames if not capturing and device is open."""
        if self._task_read or not self._device:
            return
        FTCamera.logger.info("FTCamera.start_read: start read task")
        self._task_read = aio.create_task(self._async_read())

    async def stop_read(self: "FTCamera") -> None:
        """Stop capturing frames if capturing."""
        if not self._task_read or not self._device:
            return
        FTCamera.logger.info("FTCamera.stop_read: stop read task")
        self._task_read.cancel()
        try:
            await self._task_read
        except aio.CancelledError:
            FTCamera.logger.info("FTCamera.stop_read: read task stopped")
        self._task_read = None

    async def _async_read(self: "FTCamera") -> None:
        async for frame in self._device:
            if not await self._process_frame(frame):
                break

    async def _process_frame(self: "FTCamera", frame: v4l.Frame) -> bool:
        """Process captured frames.

        Operates only on YUV422 format right now. Calls _decode_yuv422
        for processing the frame. See _decode_yuv422_y_only for an
        optimized version producing only Y grayscale frame.

        The captured frame is reshaped to (height, width, 3) before
        sending it to "callback_frame".
        """
        if not self.callback_frame or len(frame.data) == 0:
            return True

        try:
            match frame.pixel_format:
                case v4l.PixelFormat.YUYV:
                    self._decode_yuv422(frame)
                case _:
                    FTCamera.logger.error("Unsupported pixel format: {}".
                                          format(frame.pixel_format))
                    return False
            await self.callback_frame(self._arr_merge.reshape(
                [frame.height, frame.width, 3]))

        except aio.CancelledError:
            raise
        except Exception:
            FTCamera.logger.error(traceback.format_exc())
            return False
        return True

    def _decode_yuv422(self: "FTCamera", frame: v4l.Frame) -> None:
        """Decode YUV422 frame into YUV444 frame."""
        self._arr_data[:] = np.frombuffer(frame.data, dtype=np.uint8)

        self._arr_merge[:, 0] = np.array(self._arr_data[0::2])
        self._arr_c2[:] = np.array(self._arr_data[1::4])
        self._arr_c3[:] = np.array(self._arr_data[3::4])

        self._arr_merge[0:self._pixel_count:2, 1] = self._arr_c2
        self._arr_merge[1:self._pixel_count:2, 1] = self._arr_c2
        self._arr_merge[0:self._pixel_count:2, 2] = self._arr_c3
        self._arr_merge[1:self._pixel_count:2, 2] = self._arr_c3

    def _decode_yuv422_y_only(self: "FTCamera", frame: v4l.Frame) -> None:
        """Fast version of _decode_yuv422.

        This version is faster since it only copies the Y channel
        of the image data. The result is thus a single channel
        image (grayscale image). This is suitible for cameras
        like the VIVE that output the same image on all channels
        """
        self._arr_data[:] = np.frombuffer(frame.data, dtype=np.uint8)

        self._arr_merge[:, 0] = np.array(self._arr_data[0::2])
