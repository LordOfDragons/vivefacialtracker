import logging
import ctypes
import fcntl
import time
import cv2 as cv
import numpy as np
from timeit import default_timer as timer


_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(dir_, type_, nr, size):
    return (
        ctypes.c_int32(dir_ << _IOC_DIRSHIFT).value
        | ctypes.c_int32(ord(type_) << _IOC_TYPESHIFT).value
        | ctypes.c_int32(nr << _IOC_NRSHIFT).value
        | ctypes.c_int32(size << _IOC_SIZESHIFT).value
    )


def _IOC_TYPECHECK(t):
    return ctypes.sizeof(t)


def _IOWR(type_, nr, size):
    return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, _IOC_TYPECHECK(size))


class ViveTracker:
    """Provides support to activate data steam on VIVE Facial Tracker camera."""
    _XU_TASK_SET = 0x50
    _XU_TASK_GET = 0x51
    _XU_REG_SENSOR = 0xab

    _UVC_SET_CUR = 0x01
    _UVC_GET_CUR = 0x81
    _UVC_GET_MIN = 0x82
    _UVC_GET_MAX = 0x83
    _UVC_GET_RES = 0x84
    _UVC_GET_LEN = 0x85
    _UVC_GET_INFO = 0x86
    _UVC_GET_DEF = 0x87

    class _uvc_xu_control_query(ctypes.Structure):
        _fields_ = [
            ('unit', ctypes.c_uint8),
            ('selector', ctypes.c_uint8),
            ('query', ctypes.c_uint8),
            ('size', ctypes.c_uint16),
            ('data', ctypes.POINTER(ctypes.c_uint8)),
        ]

    _UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, _uvc_xu_control_query)

    _logger = logging.getLogger("evcta.ViveTracker")

    def __init__(self: "ViveTracker", fd: int) -> None:
        """Create VIVE Face Tracker instance.

        Constructor tries first to detect if this is a VIVE Face Tracker.
        Then device parameters are set and the data stream eventually
        activated.

        Make sure to call "dispose()" once the tracker is no more needed
        to deactivate the data stream.

        Keyword arguments:
        fd --- File descriptor of device. Using Video4Linux device use
               "device.fileno()" for this argument. Using FTCamera use
               "ftcamera.device.fileno()" for this argument.
        """
        if not fd:
            raise Exception("Missing camera file descriptor")
        ViveTracker._logger.info("create vive tracker")
        self._fd: int = fd

        self._bufferSend: list[ctypes.c_uint8] = (ctypes.c_uint8 * 384)()
        self._bufferReceive: list[ctypes.c_uint8] = (ctypes.c_uint8 * 384)()
        self._bufferRegister: list[ctypes.c_uint8] = (ctypes.c_uint8 * 17)()

        self._dataTest: list[ctypes.c_uint8] = (ctypes.c_uint8 * 384)()
        self._dataTest[0] = 0x51
        self._dataTest[1] = 0x52
        self._dataTest[254] = 0x53
        self._dataTest[255] = 0x54

        self._debug = False

        self._detect_vive_tracker()
        try:
            self._activate_tracker()
        except Exception:
            self._deactivate_tracker()
            raise

    @staticmethod
    def is_camera_vive_tracker(device: "v4l.Device") -> bool:
        """Detect if this is a VIVE Face Tracker.

        This is done right now by looking at the human readable device
        description which might not be fool proof. Better would be to
        check the vendor-id(0x0bb4) and device-id (0x0321). But these
        can be only found by querying full USB descriptor. Left for
        the reader as excercise.
        """
        check = "HTC Multimedia Camera" in device.info.card
        ViveTracker._logger.info("is_camera_vive_tracker: '{}' -> {}".format(
            device.info.card, check))
        return check

    def dispose(self: "ViveTracker") -> None:
        """Dispose of tracker.

        Deactivates data stream."""
        ViveTracker._logger.info("dispose vive tracker")
        self._deactivate_tracker()

    def process_frame(self: "ViveTracker", data: np.ndarray) -> np.ndarray:
        """Process a captured frame.

        Right now this applies a median blur but other manipulations
        are possible to improve the image if desired.

        Keyword arguments:
        data --- Frame to process
        """
        data = cv.medianBlur(data, 5)
        return data

    def _xu_get_len(self: "ViveTracker", selector: int) -> int:
        """Send GET_LEN command to device extension unit.

        Keyword arguments:
        selector --- Selector
        """
        length = (ctypes.c_uint8 * 2)(0, 0)
        c = ViveTracker._uvc_xu_control_query(
            4, selector, ViveTracker._UVC_GET_LEN, 2, length)
        fcntl.ioctl(self._fd, ViveTracker._UVCIOC_CTRL_QUERY, c)
        return (length[1] << 8) + length[0]

    def _xu_get_cur(self: "ViveTracker", selector: int,
                    data: list[ctypes.c_uint8]) -> None:
        """Send GET_CUR command to device extension unit.

        Keyword arguments:
        selector --- Selector
        data -- Buffer to store response to. Has to be 384 bytes long.
        """
        c = ViveTracker._uvc_xu_control_query(
            4, selector, ViveTracker._UVC_GET_CUR, len(data), data)
        fcntl.ioctl(self._fd, ViveTracker._UVCIOC_CTRL_QUERY, c)

    def _xu_set_cur(self: "ViveTracker", selector: int,
                    data: list[ctypes.c_uint8]) -> None:
        """Send SET_CUR command to device extension unit.

        Keyword arguments:
        selector --- Selector
        data -- Data to send. Has to be 384 bytes long.
        """
        c = ViveTracker._uvc_xu_control_query(
            4, selector, ViveTracker._UVC_SET_CUR, len(data), data)
        fcntl.ioctl(self._fd, ViveTracker._UVCIOC_CTRL_QUERY, c)

    def _get_len(self: "ViveTracker") -> int:
        """Get buffer length of device."""
        return self._xu_get_len(2)

    def _set_cur(self: "ViveTracker", command: list[ctypes.c_uint8],
                 timeout: float = 0.5) -> None:
        """Send SET_CUR command to device extension unit with proper handling.

        Sends SET_CUR command to the device. Then sends GET_CUR commands to
        device until the "command finished" response is found.

        Keyword arguments:
        command --- Command to send.
        timeout -- Timeout in seconds.
        """
        length = len(command)
        self._bufferSend[:length] = command
        self._xu_set_cur(2, self._bufferSend)
        if self._debug:
            ViveTracker._logger.debug("set_cur({})".format(
                [hex(x) for x in command[:16]]))
        lenbuf = len(self._bufferReceive)
        stime = timer()
        while True:
            self._bufferReceive[:] = (ctypes.c_uint8 * lenbuf)(0)
            self._xu_get_cur(2, self._bufferReceive)
            if self._bufferReceive[0] == 0x55:
                # command not finished yet
                if self._debug:
                    ViveTracker._logger.debug("-> getCur: pending")
            elif self._bufferReceive[0] == 0x56:
                # the full command is repeated minus the last byte.
                # we check only the first 16 bytes here
                if self._bufferReceive[1:17] == self._bufferSend[0:16]:
                    if self._debug:
                        ViveTracker._logger.debug("-> getCur: finished")
                    return  # command finished
                else:
                    raise Exception(
                        "set_cur({}): response not matching command".
                        format([hex(x) for x in command[:16]]))
            else:
                raise Exception("set_cur({}): invalid response: {}".format(
                    [hex(x) for x in command[:16]],
                    [hex(x) for x in self._bufferReceive[:16]]))

            elapsed = (timer() - stime)
            if self._debug:
                ViveTracker._logger.debug("-> elasped {:d}ms".format(
                    int(elapsed * 1000)))
            if elapsed > timeout:
                raise Exception("set_cur({}): timeout".format(
                    [hex(x) for x in command[:16]]))

    def _set_cur_no_resp(self: "ViveTracker",
                         command: list[ctypes.c_uint8]) -> None:
        """Send SET_CUR command to device without proper handling.

        Keyword arguments:
        command --- Command to send.
        """
        self._bufferSend[:len(command)] = command
        self._xu_set_cur(2, self._bufferSend)
        if self._debug:
            ViveTracker._logger.debug("set_cur_no_resp({})".format(
                [hex(x) for x in command[:16]]))

    def _init_register(self: "ViveTracker", command: int, reg: int,
                       address: int, address_len: int,
                       value: int, value_len: int) -> None:
        """Init buffer for manipulating a register.

        Keyword arguments:
        command --- Command
        reg --- Register
        address --- Address
        address_len --- Length of address in bytes
        value --- Value
        value_len --- Length of value in bytes
        """
        br = self._bufferRegister
        br[0] = ctypes.c_uint8(command)
        br[1] = ctypes.c_uint8(reg)
        br[2] = ctypes.c_uint8(0x60)
        br[3] = ctypes.c_uint8(address_len)  # address width in bytes
        br[4] = ctypes.c_uint8(value_len)  # data width in bytes

        # address
        br[5] = ctypes.c_uint8((address > 24) & 0xff)
        br[6] = ctypes.c_uint8((address > 16) & 0xff)
        br[7] = ctypes.c_uint8((address > 8) & 0xff)
        br[8] = ctypes.c_uint8(address & 0xff)

        # page address
        br[9] = ctypes.c_uint8(0x90)
        br[10] = ctypes.c_uint8(0x01)
        br[11] = ctypes.c_uint8(0x00)
        br[12] = ctypes.c_uint8(0x01)

        # value
        br[13] = ctypes.c_uint8((value > 24) & 0xff)
        br[14] = ctypes.c_uint8((value > 16) & 0xff)
        br[15] = ctypes.c_uint8((value > 8) & 0xff)
        br[16] = ctypes.c_uint8(value & 0xff)

    def _set_register(self: "ViveTracker", reg: int, address: int,
                      value: int, timeout: float = 0.5) -> None:
        """Set device register.

        Keyword arguments:
        reg --- Register to manipulate
        address --- Address to manipulate
        value --- Value to set
        timeout --- Timeout in seconds. Use 0 to send register without
                    proper request handling
        """
        self._init_register(ViveTracker._XU_TASK_SET, reg, address, 1, value, 1)
        if timeout > 0:
            self._set_cur(self._bufferRegister, timeout)
        else:
            self._set_cur_no_resp(self._bufferRegister)

    def _get_register(self: "ViveTracker", reg: int, address: int,
                      timeout: float = 0.5) -> int:
        """Get device register.

        Keyword arguments:
        reg --- Register to fetch
        address --- Address to fetch
        timeout --- Timeout in seconds
        """
        self._init_register(ViveTracker._XU_TASK_GET, reg, address, 1, 0, 1)
        self._set_cur(self._bufferRegister, timeout)
        return int(self._bufferReceive[17])

    def _set_register_sensor(self: "ViveTracker", address: int, value: int,
                             timeout: float = 0.5) -> None:
        """Set device sensor register.

        Keyword arguments:
        address --- Address to manipulate
        value --- Value to set
        timeout --- Timeout in seconds. Use 0 to send register without
                    proper request handling
        """
        self._set_register(ViveTracker._XU_REG_SENSOR, address, value, timeout)

    def _get_register_sensor(self: "ViveTracker", address: int,
                             timeout: float = 0.5) -> int:
        """Get device sensor register.

        Keyword arguments:
        address --- Address to fetch
        timeout --- Timeout in seconds
        """
        return self._get_register(ViveTracker._XU_REG_SENSOR, address, timeout)

    def _set_enable_stream(self: "ViveTracker", enable: bool) -> None:
        """Enable or disable data stream.

        Keyword arguments:
        enable --- Enable or disable data stream.
        """
        buf = (ctypes.c_uint8 * 4)(ViveTracker._XU_TASK_SET, 0x14, 0x00,
                                   0x01 if enable else 0x00)
        self._set_cur_no_resp(buf)

    def _detect_vive_tracker(self: "ViveTracker") -> None:
        """Try to detect if this is a VIVE Face Tracker device.

        uses GET_LEN to get the data buffer length. VIVE Face Tracker
        uses 384. If this is not the case then this is most probebly
        something else but not a VIVE Face Tracker.
        """
        length = self._get_len()
        if length != 384:
            raise Exception("length check failed: {} instead of 384".
                            format(length))
        ViveTracker._logger.info("vive tracker detected")

    def _activate_tracker(self: "ViveTracker") -> None:
        """Activate tracker.

        Sets parameters and enables data stream."""
        ViveTracker._logger.info("activate vive tracker")

        ViveTracker._logger.info("-> disable stream")
        self._set_cur(self._dataTest)
        self._set_enable_stream(False)
        time.sleep(0.25)

        ViveTracker._logger.info("-> set camera parameters")
        self._set_cur(self._dataTest)
        self._set_register_sensor(0x00, 0x40)
        self._set_register_sensor(0x08, 0x01)
        self._set_register_sensor(0x70, 0x00)
        self._set_register_sensor(0x02, 0xff)
        self._set_register_sensor(0x03, 0xff)
        self._set_register_sensor(0x04, 0xff)
        self._set_register_sensor(0x0e, 0x00)
        self._set_register_sensor(0x05, 0xb2)
        self._set_register_sensor(0x06, 0xb2)
        self._set_register_sensor(0x07, 0xb2)
        self._set_register_sensor(0x0f, 0x03)

        ViveTracker._logger.info("-> enable stream")
        self._set_cur(self._dataTest)
        self._set_enable_stream(True)
        time.sleep(0.25)

    def _deactivate_tracker(self: "ViveTracker") -> None:
        """Deactivate tracker.

        Disables data stream.
        """
        ViveTracker._logger.info("deactivate vive tracker")

        ViveTracker._logger.info("-> disable stream")
        self._set_cur(self._dataTest)
        self._set_enable_stream(False)
        time.sleep(0.25)
