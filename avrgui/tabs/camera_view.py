import socket
from threading import Thread

import numpy as np
from PySide6 import QtCore, QtWidgets
from loguru import logger

from avrgui.lib import stream
from avrgui.lib.graphics_label import GraphicsLabel
from avrgui.lib.widgets import IntLineEdit
from avrgui.tabs.base import BaseTabWidget
from avrgui.tabs.connection.mqtt import MQTTConnectionWidget

BUFF_SIZE = 65536
socket.setdefaulttimeout(0.5)

ENDPOINT = ""
DEFAULT_CAMERA = {
    "resolution": "0x0",
    "fov": 0,
    "model": "Unknown",
    "index": -1
}
CAMERAS = {
    "CSI Camera": {
        "resolution": "3840x2160",
        "fov": 160,
        "model": "SeeedStudio IMX219-160",
        "index": 0
    },
    "Stereoscopic Camera Right": {
        "resolution": "4416x1242",
        "fov": 90,
        "model": "Zed Mini",
        "index": 1
    },
    "Stereoscopic Camera Left": {
        "resolution": "4416x1242",
        "fov": 90,
        "model": "Zed Mini",
        "index": 2
    },
    "Stereoscopic Camera Depth": {
        "resolution": "?",
        "fov": 100,
        "model": "Zed Mini",
        "index": 3
    }
}


class CameraViewWidget(BaseTabWidget):
    update_signal = QtCore.Signal(np.ndarray)
    change_streaming = QtCore.Signal(bool)
    streaming_changed = QtCore.Signal(bool)
    send_status_message = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)

        self.shutting_down = False
        self._disconnect_toast = None
        self._connect_toast = None
        self.update_thread = None
        self.port_line_edit = None
        self.streaming_camera = None
        self.is_connected = False
        self.connect_button = None
        self.camera_picker = None
        self.resolution_text = None
        self.fov_text = None
        self.streaming_text = None
        self.model_text = None
        self.view = None

        self.setWindowTitle("Camera View")

    def build(self) -> None:
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        # Viewer

        viewer_groupbox = QtWidgets.QGroupBox("Viewer")
        viewer_layout = QtWidgets.QVBoxLayout()
        viewer_groupbox.setLayout(viewer_layout)

        self.view = GraphicsLabel((16, 9))
        self.view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.MinimumExpanding)
        self.view.sizePolicy().setHeightForWidth(True)
        self.update_signal.connect(self.update_image)

        viewer_layout.addWidget(self.view)

        layout.addWidget(viewer_groupbox, 0, 0)

        # Options

        options_groupbox = QtWidgets.QGroupBox("Options")
        options_layout = QtWidgets.QFormLayout()
        options_groupbox.setLayout(options_layout)
        options_groupbox.setFixedWidth(250)
        options_groupbox.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)

        spacer = QtWidgets.QSpacerItem(0, 5)
        options_layout.addItem(spacer)

        self.camera_picker = QtWidgets.QComboBox()
        for camera in CAMERAS:
            self.camera_picker.addItem(camera)
        self.camera_picker.currentTextChanged.connect(self.camera_selected)
        options_layout.addRow("Camera", self.camera_picker)

        self.port_line_edit = IntLineEdit()
        self.port_line_edit.setText("9999")
        options_layout.addRow(QtWidgets.QLabel("Port: "), self.port_line_edit)
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.connect_button.clicked.connect(lambda: self.set_streaming())
        options_layout.addWidget(self.connect_button)

        layout.addWidget(options_groupbox, 0, 1)

        # Information

        info_groupbox = QtWidgets.QGroupBox("Information")
        info_layout = QtWidgets.QGridLayout()
        info_groupbox.setLayout(info_layout)
        info_groupbox.setFixedHeight(150)
        info_groupbox.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self.resolution_text = QtWidgets.QLabel("Resolution: None")
        info_layout.addWidget(self.resolution_text, 0, 0)

        self.fov_text = QtWidgets.QLabel("FOV: None")
        info_layout.addWidget(self.fov_text, 1, 0)

        self.model_text = QtWidgets.QLabel("Model: None")
        info_layout.addWidget(self.model_text, 0, 1)

        self.streaming_text = QtWidgets.QLabel("Streaming: False")
        info_layout.addWidget(self.streaming_text, 1, 1)

        layout.addWidget(info_groupbox, 1, 0, 1, 0)

        self.set_camera_info(list(CAMERAS.values())[0])

        self.change_streaming.connect(self.set_streaming)

        # self._connect_toast = Toast(text = 'Attempting to connect to the frame server', duration = 3, parent = self)
        # self._disconnect_toast = Toast(text = 'Disconnected from the frame server', duration = 3, parent = self)

    def update_image(self, frame: np.ndarray):
        self.view.setPixmap(stream.convert_cv_qt(frame, (self.view.width(), self.view.height())))

    def camera_selected(self, name: str):
        camera = CAMERAS.get(name, DEFAULT_CAMERA)
        index = camera.get("index", -1)
        if index >= 0:
            self.set_camera_info(camera)
            self.send_message("avr/camera/select", index)

    def set_camera_info(self, camera: dict):
        resolution = camera.get("resolution", DEFAULT_CAMERA["resolution"])
        fov = camera.get("fov", DEFAULT_CAMERA["fov"])
        model = camera.get("model", DEFAULT_CAMERA["model"])

        self.resolution_text.setText(f"Resolution: { resolution }")
        self.fov_text.setText(f"FOV: { fov }º")
        self.model_text.setText(f"Model: { model }")

    def set_streaming(self, enabled: bool = None) -> bool:
        return_value = False
        if enabled is None:
            enabled = not self.is_connected
        if enabled:
            hostname = MQTTConnectionWidget.current_host
            try:
                port = int(self.port_line_edit.text())
            except ValueError:
                logger.debug("Invalid port specified")
                return return_value
            self.is_connected = True
            self.connect_button.setText("Disconnect")
            self.port_line_edit.setReadOnly(True)
            self.update_thread = Thread(target = lambda: self._update_loop((hostname, port))).start()
            self.streaming_changed.emit(True)
            return_value = True
        else:
            self.connect_button.setText("Connect")
            self.port_line_edit.setReadOnly(False)
            self.is_connected = False
            self.streaming_changed.emit(False)
            return_value = True
        self.streaming_text.setText("Streaming: " + str(self.is_connected))
        return return_value

    def _update_loop(self, host):
        logger.info(f"Socket client connecting to { host[0] }:{ host[1] }")
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFF_SIZE)
        client_socket.sendto(b"connect", host)
        while self.is_connected:
            try:
                if not stream.is_socket_open(client_socket):
                    logger.debug("Socket closed")
                    if not self.shutting_down:
                        self.change_streaming.emit(False)
                    break
                packet, _ = client_socket.recvfrom(5)
                message_count = int.from_bytes(packet, "big")

                if message_count == 1:
                    full_encoded_frame, _ = client_socket.recvfrom(BUFF_SIZE)
                    client_socket.sendto(b"ping", host)
                else:
                    full_encoded_frame = b""
                    for i in range(message_count):
                        fragment, _ = client_socket.recvfrom(BUFF_SIZE)
                        full_encoded_frame += fragment
                        client_socket.sendto(b"ping", host)

                success, frame = stream.decode_frame(full_encoded_frame)
                if self.shutting_down:
                    break
                if success:
                    self.update_signal.emit(frame)
            except TimeoutError as e:
                logger.debug("Socket timed out")
                logger.exception(e)
                if not self.shutting_down:
                    self.change_streaming.emit(False)
                break
        logger.info("Disconnected socket")
        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except (OSError, TimeoutError):
            pass
        client_socket.close()
        # self.send_disconnect_toast.emit()

    def process_message(self, topic: str, payload: str) -> None:
        pass

    def show_disconnect_toast(self):
        pass# self._disconnect_toast.show()

    def mqtt_connection_state(self, state: bool):
        if state:
            if self.set_streaming(True):
                pass# self._connect_toast.show()

    def clear(self) -> None:
        self.is_connected = False
        self.connect_button.setText("Connect")
        self.streaming_text.setText("Streaming: " + str(self.is_connected))

    def on_close(self):
        self.shutting_down = True
        self.is_connected = False
        if self.update_thread is not None:
            self.update_thread.join()