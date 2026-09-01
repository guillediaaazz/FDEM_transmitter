from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import BooleanVar, StringVar, messagebox
from typing import Any

import customtkinter as ctk

from .constants import (
    ACK_TIMEOUT_SECONDS,
    APP_NAME,
    APP_VERSION,
    MAX_AMPLITUDE_VPP,
    MAX_FREQUENCY_HZ,
    MAX_TRIM_STEPS,
    MIN_AMPLITUDE_VPP,
    MIN_FREQUENCY_HZ,
    MIN_TRIM_STEPS,
    SETTINGS_DEBOUNCE_MS,
    TRIM_DEBOUNCE_MS,
    UI_EVENT_INTERVAL_MS,
)
from .events import (
    BleDeviceInfo,
    BleScanCompleted,
    Connected,
    Disconnected,
    LineReceived,
    SerialPortInfo,
    TransportEvent,
    TransportFailure,
    TransportKind,
)
from .i18n import Translator
from .model import ControllerState, DisconnectRequirement
from .protocol import (
    Acknowledgement,
    BatteryTelemetry,
    BootMessage,
    CalibrationProgress,
    DeviceError,
    DeviceStatus,
    HelpMessage,
    ProtocolValueError,
    RawMessage,
    build_amplitude_command,
    build_settings_command,
    build_trim_command,
    parse_message,
    trim_output_volts,
)
from .settings import AppSettings, SettingsStore
from .transports import BleTransport, SerialTransport, Transport


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

COLORS = {
    "canvas": "#071019",
    "surface": "#0d1926",
    "raised": "#122236",
    "line": "#28405a",
    "text": "#edf5ff",
    "muted": "#9bb0c5",
    "cyan": "#3bd4e8",
    "blue": "#4a8dff",
    "green": "#5ae2a0",
    "amber": "#ffbd5c",
    "red": "#ff7181",
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative


@dataclass
class PendingCommand:
    command: str
    response: str
    sent_at: float


class ChoiceDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, title: str, text: str, choices: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.result = "cancel"
        self.title(title)
        self.geometry("590x230")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        body.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(body, text=text, justify="left", wraplength=520, font=ctk.CTkFont(size=14)).grid(
            row=0, column=0, padx=22, pady=(24, 20), sticky="ew"
        )
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="e")
        for index, (label, value) in enumerate(choices):
            color = COLORS["red"] if value == "unsafe" else COLORS["raised"]
            hover = "#d84f63" if value == "unsafe" else "#1b3551"
            ctk.CTkButton(
                buttons,
                text=label,
                width=130,
                fg_color=color,
                hover_color=hover,
                text_color="#101820" if value == "unsafe" else COLORS["text"],
                command=lambda selected=value: self._choose(selected),
            ).grid(row=0, column=index, padx=5)
        self.after(50, self._activate)

    def _activate(self) -> None:
        self.grab_set()
        self.focus_force()

    def _choose(self, value: str) -> None:
        self.result = value
        self.destroy()

    def _cancel(self) -> None:
        self.result = "cancel"
        self.destroy()

    @classmethod
    def ask(cls, parent: ctk.CTk, title: str, text: str, choices: list[tuple[str, str]]) -> str:
        dialog = cls(parent, title, text, choices)
        parent.wait_window(dialog)
        return dialog.result


class FdemControllerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore()
        self.settings: AppSettings = self.settings_store.load()
        self.t = Translator(self.settings.language)
        self.controller_state = ControllerState()
        self.events: queue.Queue[TransportEvent] = queue.Queue()
        self.serial_transport = SerialTransport(self.events.put)
        self.ble_transport = BleTransport(self.events.put)
        self.active_transport: Transport | None = None
        self.serial_ports: dict[str, SerialPortInfo] = {}
        self.ble_devices: dict[str, BleDeviceInfo] = {}
        self.pending: deque[PendingCommand] = deque()
        self.log_lines: list[str] = []
        self.settings_after: str | None = None
        self.trim_after: str | None = None
        self.mute_after: str | None = None
        self.mute_action: str | None = None
        self._closing = False
        self._updating = False
        self._log_visible = False
        self._persistent_warning = ""
        self._unexpected_disconnect = False

        self.title(self.t("app_title"))
        self.geometry(self.settings.geometry or "1180x780")
        self.minsize(1000, 700)
        self.configure(fg_color=COLORS["canvas"])
        icon = resource_path("assets/fdem.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self._build_ui()
        self._apply_language()
        self._refresh_serial_ports()
        self._log("*", self.t("controller_ready"))
        self.after(UI_EVENT_INTERVAL_MS, self._drain_events)
        self.after(250, self._check_pending)
        self.after(1000, self._tick_telemetry)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=22, pady=(16, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w")
        self.brand_subtitle = ctk.CTkLabel(
            brand, text="", text_color=COLORS["cyan"], font=ctk.CTkFont(size=11, weight="bold")
        )
        self.brand_subtitle.grid(row=0, column=0, sticky="w")
        self.brand_title = ctk.CTkLabel(brand, text="", font=ctk.CTkFont(size=25, weight="bold"))
        self.brand_title.grid(row=1, column=0, sticky="w")
        right_header = ctk.CTkFrame(header, fg_color="transparent")
        right_header.grid(row=0, column=1, sticky="e")
        self.language_label = ctk.CTkLabel(right_header, text="", text_color=COLORS["muted"])
        self.language_label.grid(row=0, column=0, padx=(0, 8))
        self.language_var = StringVar(value="Español" if self.settings.language == "es" else "English")
        self.language_menu = ctk.CTkOptionMenu(
            right_header,
            values=["English", "Español"],
            variable=self.language_var,
            width=120,
            command=self._change_language,
        )
        self.language_menu.grid(row=0, column=1, padx=(0, 12))
        self.connection_badge = ctk.CTkLabel(
            right_header,
            text="",
            width=145,
            height=32,
            corner_radius=16,
            fg_color=COLORS["raised"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.connection_badge.grid(row=0, column=2)

        connection = self._panel(self, row=1, column=0, padx=22, pady=(0, 10))
        connection.grid_columnconfigure(1, weight=1)
        self.connection_eyebrow = self._eyebrow(connection, 0, 0)
        self.connection_title = ctk.CTkLabel(connection, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.connection_title.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="w")
        self.connection_detail = ctk.CTkLabel(
            connection, text="", text_color=COLORS["muted"], anchor="w", wraplength=520
        )
        self.connection_detail.grid(row=2, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")

        selector = ctk.CTkFrame(connection, fg_color="transparent")
        selector.grid(row=0, column=1, rowspan=2, padx=18, pady=14, sticky="e")
        self.transport_var = StringVar(value=self.settings.last_transport)
        self.usb_radio = ctk.CTkRadioButton(
            selector, text="", variable=self.transport_var, value="usb", command=self._transport_changed
        )
        self.usb_radio.grid(row=0, column=0, padx=8)
        self.ble_radio = ctk.CTkRadioButton(
            selector, text="", variable=self.transport_var, value="ble", command=self._transport_changed
        )
        self.ble_radio.grid(row=0, column=1, padx=8)

        target_row = ctk.CTkFrame(connection, fg_color="transparent")
        target_row.grid(row=3, column=0, columnspan=2, padx=18, pady=(0, 18), sticky="ew")
        target_row.grid_columnconfigure(1, weight=1)
        self.target_label = ctk.CTkLabel(target_row, text="")
        self.target_label.grid(row=0, column=0, padx=(0, 10))
        self.target_var = StringVar(value="")
        self.target_menu = ctk.CTkOptionMenu(target_row, values=[""], variable=self.target_var, dynamic_resizing=False)
        self.target_menu.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.refresh_button = ctk.CTkButton(target_row, text="", width=100, command=self._refresh_target)
        self.refresh_button.grid(row=0, column=2, padx=4)
        self.connect_button = ctk.CTkButton(
            target_row, text="", width=110, fg_color=COLORS["blue"], command=self._connect
        )
        self.connect_button.grid(row=0, column=3, padx=4)
        self.disconnect_button = ctk.CTkButton(
            target_row,
            text="",
            width=110,
            fg_color="#542631",
            hover_color="#713343",
            state="disabled",
            command=lambda: self._request_disconnect(False),
        )
        self.disconnect_button.grid(row=0, column=4, padx=(4, 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, padx=22, pady=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=3, uniform="dashboard")
        content.grid_columnconfigure(1, weight=2, uniform="dashboard")
        content.grid_rowconfigure(0, weight=1)
        self._build_controls(content)
        self._build_telemetry(content)
        self._build_log()

    def _panel(self, parent: Any, **grid: Any) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface"],
            border_color=COLORS["line"],
            border_width=1,
            corner_radius=14,
        )
        panel.grid(sticky="nsew", **grid)
        return panel

    def _eyebrow(self, parent: Any, row: int, column: int) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent, text="", text_color=COLORS["cyan"], font=ctk.CTkFont(size=10, weight="bold")
        )
        label.grid(row=row, column=column, padx=18, pady=(14, 0), sticky="w")
        return label

    def _build_controls(self, parent: ctk.CTkFrame) -> None:
        panel = self._panel(parent, row=0, column=0, padx=(0, 5), pady=0)
        panel.grid_columnconfigure(0, weight=1)
        self.signal_eyebrow = self._eyebrow(panel, 0, 0)
        heading = ctk.CTkFrame(panel, fg_color="transparent")
        heading.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        heading.grid_columnconfigure(0, weight=1)
        self.signal_title = ctk.CTkLabel(heading, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.signal_title.grid(row=0, column=0, sticky="w")
        self.output_badge = ctk.CTkLabel(
            heading, text="", corner_radius=14, height=28, padx=12, fg_color=COLORS["raised"]
        )
        self.output_badge.grid(row=0, column=1, sticky="e")

        self.frequency_var = StringVar(value="1000.0")
        self.frequency_label, self.frequency_entry, self.frequency_slider, self.frequency_note = self._number_control(
            panel, 2, self.frequency_var, MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ, 79990, "Hz", self._frequency_slide
        )
        self.frequency_entry.bind("<Return>", lambda _event: self._commit_numeric())
        self.frequency_entry.bind("<FocusOut>", lambda _event: self._commit_numeric())

        self.amplitude_var = StringVar(value="0.0")
        self.amplitude_label, self.amplitude_entry, self.amplitude_slider, self.amplitude_note = self._number_control(
            panel, 3, self.amplitude_var, MIN_AMPLITUDE_VPP, MAX_AMPLITUDE_VPP, 200, "Vpp", self._amplitude_slide
        )
        self.amplitude_entry.bind("<Return>", lambda _event: self._commit_numeric())
        self.amplitude_entry.bind("<FocusOut>", lambda _event: self._commit_numeric())

        waveform_frame = ctk.CTkFrame(panel, fg_color="transparent")
        waveform_frame.grid(row=4, column=0, padx=18, pady=8, sticky="ew")
        waveform_frame.grid_columnconfigure(1, weight=1)
        self.waveform_label = ctk.CTkLabel(waveform_frame, text="", font=ctk.CTkFont(weight="bold"))
        self.waveform_label.grid(row=0, column=0, padx=(0, 15), sticky="w")
        self.waveform_control = ctk.CTkSegmentedButton(
            waveform_frame, values=["Sine", "Triangle"], command=self._waveform_changed
        )
        self.waveform_control.grid(row=0, column=1, sticky="ew")
        self.waveform_control.set("Sine")

        trim_frame = ctk.CTkFrame(panel, fg_color="transparent")
        trim_frame.grid(row=5, column=0, padx=18, pady=8, sticky="ew")
        trim_frame.grid_columnconfigure(1, weight=1)
        self.trim_label = ctk.CTkLabel(trim_frame, text="", font=ctk.CTkFont(weight="bold"))
        self.trim_label.grid(row=0, column=0, sticky="w")
        self.trim_value = ctk.CTkLabel(trim_frame, text="", text_color=COLORS["cyan"])
        self.trim_value.grid(row=0, column=1, columnspan=2, sticky="e")
        self.trim_minus = ctk.CTkButton(trim_frame, text="−", width=38, command=lambda: self._nudge_trim(-1))
        self.trim_minus.grid(row=1, column=0, pady=(5, 0))
        self.trim_slider = ctk.CTkSlider(
            trim_frame,
            from_=MIN_TRIM_STEPS,
            to=MAX_TRIM_STEPS,
            number_of_steps=MAX_TRIM_STEPS - MIN_TRIM_STEPS,
            command=self._trim_slide,
        )
        self.trim_slider.grid(row=1, column=1, padx=8, pady=(5, 0), sticky="ew")
        self.trim_plus = ctk.CTkButton(trim_frame, text="+", width=38, command=lambda: self._nudge_trim(1))
        self.trim_plus.grid(row=1, column=2, pady=(5, 0))
        self.trim_note = ctk.CTkLabel(
            trim_frame, text="", text_color=COLORS["muted"], justify="left", anchor="w", wraplength=580
        )
        self.trim_note.grid(row=2, column=0, columnspan=3, pady=(4, 0), sticky="ew")
        self.trim_slider.set(0)

        ble_row = ctk.CTkFrame(panel, fg_color="transparent")
        ble_row.grid(row=6, column=0, padx=18, pady=8, sticky="ew")
        ble_row.grid_columnconfigure(0, weight=1)
        self.ble_advertising_label = ctk.CTkLabel(ble_row, text="", font=ctk.CTkFont(weight="bold"))
        self.ble_advertising_label.grid(row=0, column=0, sticky="w")
        self.ble_note = ctk.CTkLabel(ble_row, text="", text_color=COLORS["muted"], anchor="w")
        self.ble_note.grid(row=1, column=0, sticky="w")
        self.ble_var = BooleanVar(value=True)
        self.ble_switch = ctk.CTkSwitch(ble_row, text="", variable=self.ble_var, command=self._toggle_ble)
        self.ble_switch.grid(row=0, column=1, rowspan=2, padx=(12, 0))

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=7, column=0, padx=18, pady=(10, 16), sticky="ew")
        for column in range(2):
            actions.grid_columnconfigure(column, weight=1)
        self.calibrate_button = ctk.CTkButton(
            actions, text="", fg_color="#8d5710", hover_color="#a96d1c", command=self._run_calibration
        )
        self.calibrate_button.grid(row=0, column=0, padx=(0, 4), pady=4, sticky="ew")
        self.clear_cal_button = ctk.CTkButton(
            actions, text="", fg_color="#542631", hover_color="#713343", command=self._clear_calibration
        )
        self.clear_cal_button.grid(row=0, column=1, padx=(4, 0), pady=4, sticky="ew")
        self.status_button = ctk.CTkButton(actions, text="", command=lambda: self._send("STATUS", "status"))
        self.status_button.grid(row=1, column=0, padx=(0, 4), pady=4, sticky="ew")
        self.help_button = ctk.CTkButton(actions, text="", command=lambda: self._send("HELP", "help"))
        self.help_button.grid(row=1, column=1, padx=(4, 0), pady=4, sticky="ew")
        self.control_widgets = [
            self.frequency_entry,
            self.frequency_slider,
            self.amplitude_entry,
            self.amplitude_slider,
            self.waveform_control,
            self.trim_minus,
            self.trim_slider,
            self.trim_plus,
            self.ble_switch,
            self.calibrate_button,
            self.clear_cal_button,
        ]

    def _number_control(
        self,
        parent: ctk.CTkFrame,
        row: int,
        variable: StringVar,
        minimum: float,
        maximum: float,
        steps: int,
        unit: str,
        callback: Any,
    ) -> tuple[ctk.CTkLabel, ctk.CTkEntry, ctk.CTkSlider, ctk.CTkLabel]:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, padx=18, pady=7, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(weight="bold"))
        label.grid(row=0, column=0, sticky="w")
        entry_frame = ctk.CTkFrame(frame, fg_color=COLORS["canvas"], corner_radius=7)
        entry_frame.grid(row=0, column=1, sticky="e")
        entry = ctk.CTkEntry(entry_frame, textvariable=variable, width=92, border_width=0, justify="right")
        entry.grid(row=0, column=0)
        ctk.CTkLabel(entry_frame, text=unit, width=42, text_color=COLORS["muted"]).grid(row=0, column=1)
        slider = ctk.CTkSlider(frame, from_=minimum, to=maximum, number_of_steps=steps, command=callback)
        slider.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")
        slider.set(float(variable.get()))
        note = ctk.CTkLabel(frame, text="", text_color=COLORS["muted"])
        note.grid(row=2, column=0, columnspan=2, sticky="w")
        return label, entry, slider, note

    def _build_telemetry(self, parent: ctk.CTkFrame) -> None:
        panel = self._panel(parent, row=0, column=1, padx=(5, 0), pady=0)
        panel.grid_columnconfigure((0, 1), weight=1)
        self.telemetry_eyebrow = self._eyebrow(panel, 0, 0)
        self.telemetry_title = ctk.CTkLabel(panel, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.telemetry_title.grid(row=1, column=0, padx=18, sticky="w")
        self.telemetry_age = ctk.CTkLabel(panel, text="", text_color=COLORS["muted"])
        self.telemetry_age.grid(row=1, column=1, padx=18, sticky="e")

        self.positive_card, self.positive_label, self.positive_value, self.positive_unit = self._metric_card(panel, 2, 0)
        self.negative_card, self.negative_label, self.negative_value, self.negative_unit = self._metric_card(panel, 2, 1)
        battery = ctk.CTkFrame(panel, fg_color=COLORS["raised"], corner_radius=10)
        battery.grid(row=3, column=0, columnspan=2, padx=18, pady=8, sticky="ew")
        battery.grid_columnconfigure(0, weight=1)
        self.battery_label = ctk.CTkLabel(battery, text="", text_color=COLORS["muted"])
        self.battery_label.grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        self.battery_value = ctk.CTkLabel(
            battery, text="—", text_color=COLORS["green"], font=ctk.CTkFont(size=20, weight="bold")
        )
        self.battery_value.grid(row=0, column=1, padx=14, pady=(12, 4), sticky="e")
        self.battery_meter = ctk.CTkProgressBar(battery, progress_color=COLORS["green"])
        self.battery_meter.grid(row=1, column=0, columnspan=2, padx=14, pady=(4, 14), sticky="ew")
        self.battery_meter.set(0)

        status = ctk.CTkFrame(panel, fg_color="transparent")
        status.grid(row=4, column=0, columnspan=2, padx=18, pady=8, sticky="ew")
        status.grid_columnconfigure(1, weight=1)
        self.applied_label, self.applied_value = self._status_row(status, 0)
        self.calibration_label, self.calibration_value = self._status_row(status, 1)
        self.bluetooth_status_label, self.bluetooth_status_value = self._status_row(status, 2)
        self.calibration_progress = ctk.CTkProgressBar(status, progress_color=COLORS["amber"])
        self.calibration_progress.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        self.calibration_progress.set(0)

        self.warning_label = ctk.CTkLabel(
            panel,
            text="",
            text_color="#fff",
            fg_color="#7c2432",
            corner_radius=8,
            wraplength=390,
            justify="left",
        )
        self.warning_label.grid(row=5, column=0, columnspan=2, padx=18, pady=(8, 16), sticky="ew")
        self.warning_label.grid_remove()

    def _metric_card(
        self, parent: ctk.CTkFrame, row: int, column: int
    ) -> tuple[ctk.CTkFrame, ctk.CTkLabel, ctk.CTkLabel, ctk.CTkLabel]:
        card = ctk.CTkFrame(parent, fg_color=COLORS["raised"], corner_radius=10)
        card.grid(row=row, column=column, padx=(18 if column == 0 else 4, 4 if column == 0 else 18), pady=14, sticky="ew")
        label = ctk.CTkLabel(card, text="", text_color=COLORS["muted"])
        label.pack(anchor="w", padx=14, pady=(12, 0))
        value = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(size=26, weight="bold"))
        value.pack(anchor="w", padx=14, pady=(3, 0))
        unit = ctk.CTkLabel(card, text="", text_color=COLORS["muted"])
        unit.pack(anchor="w", padx=14, pady=(0, 12))
        return card, label, value, unit

    def _status_row(self, parent: ctk.CTkFrame, row: int) -> tuple[ctk.CTkLabel, ctk.CTkLabel]:
        label = ctk.CTkLabel(parent, text="", text_color=COLORS["muted"])
        label.grid(row=row, column=0, pady=6, sticky="w")
        value = ctk.CTkLabel(parent, text="—", font=ctk.CTkFont(weight="bold"))
        value.grid(row=row, column=1, pady=6, sticky="e")
        return label, value

    def _build_log(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=10)
        header.grid(row=3, column=0, padx=22, pady=(10, 0), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        self.log_toggle = ctk.CTkButton(header, text="", fg_color="transparent", anchor="w", command=self._toggle_log)
        self.log_toggle.grid(row=0, column=0, padx=8, pady=5, sticky="ew")
        self.copy_log_button = ctk.CTkButton(header, text="", width=80, command=self._copy_log)
        self.copy_log_button.grid(row=0, column=1, padx=4, pady=5)
        self.clear_log_button = ctk.CTkButton(header, text="", width=80, command=self._clear_log)
        self.clear_log_button.grid(row=0, column=2, padx=(4, 8), pady=5)
        self.log_frame = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0)
        self.log_frame.grid(row=4, column=0, padx=22, pady=(0, 12), sticky="ew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(
            self.log_frame,
            height=150,
            fg_color="#030a11",
            text_color="#b4f7d2",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.log_text.grid(row=0, column=0, sticky="ew")
        self.log_text.configure(state="disabled")
        self.log_frame.grid_remove()

    def _apply_language(self) -> None:
        if self._unexpected_disconnect:
            self._persistent_warning = self.t("unexpected_disconnect")
            self.warning_label.configure(text=self._persistent_warning)
            self.warning_label.grid()
        self.title(self.t("app_title"))
        self.brand_subtitle.configure(text=self.t("brand_subtitle"))
        self.brand_title.configure(text=self.t("app_title"))
        self.language_label.configure(text=self.t("language"))
        self.connection_eyebrow.configure(text=self.t("connection"))
        self.connection_title.configure(text=self.t("connect_title"))
        self.usb_radio.configure(text=self.t("usb"))
        self.ble_radio.configure(text=self.t("bluetooth"))
        self.target_label.configure(text=self.t("port"))
        self.refresh_button.configure(text=self.t("scan") if self.transport_var.get() == "ble" else self.t("refresh"))
        self.connect_button.configure(text=self.t("connect"))
        self.disconnect_button.configure(text=self.t("disconnect"))
        self.signal_eyebrow.configure(text=self.t("signal"))
        self.signal_title.configure(text=self.t("signal_controls"))
        self.frequency_label.configure(text=self.t("frequency"))
        self.frequency_note.configure(text=self.t("frequency_range"))
        self.amplitude_label.configure(text=self.t("amplitude"))
        self.amplitude_note.configure(text=self.t("amplitude_note"))
        self.waveform_label.configure(text=self.t("waveform"))
        wave = self.controller_state.waveform
        self.waveform_control.configure(values=[self.t("sine"), self.t("triangle")])
        self.waveform_control.set(self.t("sine") if wave == "S" else self.t("triangle"))
        self.trim_label.configure(text=self.t("trim"))
        self.trim_note.configure(text=self.t("trim_note"))
        self.ble_advertising_label.configure(text=self.t("bluetooth_advertising"))
        self.ble_note.configure(text=self.t("bluetooth_note"))
        self.calibrate_button.configure(text=self.t("calibrate"))
        self.clear_cal_button.configure(text=self.t("clear_calibration"))
        self.status_button.configure(text=self.t("status"))
        self.help_button.configure(text=self.t("help"))
        self.telemetry_eyebrow.configure(text=self.t("telemetry"))
        self.telemetry_title.configure(text=self.t("system_power"))
        self.positive_label.configure(text=self.t("positive_rail"))
        self.negative_label.configure(text=self.t("negative_rail"))
        self.positive_unit.configure(text=self.t("volts"))
        self.negative_unit.configure(text=self.t("volts"))
        self.battery_label.configure(text=self.t("battery"))
        self.applied_label.configure(text=self.t("applied_output"))
        self.calibration_label.configure(text=self.t("calibration"))
        self.bluetooth_status_label.configure(text=self.t("bluetooth_state"))
        self.log_toggle.configure(text=self.t("hide_log") if self._log_visible else self.t("show_log"))
        self.copy_log_button.configure(text=self.t("copy_log"))
        self.clear_log_button.configure(text=self.t("clear_log"))
        if not self.controller_state.connected and not self.controller_state.connecting:
            if self._unexpected_disconnect:
                self._set_connection_display("error", self.t("unexpected_disconnect"))
            else:
                self._set_connection_display("disconnected", self.t("connection_idle"))
        self._render_model()

    def _change_language(self, selected: str) -> None:
        language = "es" if selected == "Español" else "en"
        self.t.set_language(language)
        self.settings.language = language
        self._save_settings()
        self._apply_language()

    def _transport_changed(self) -> None:
        if self.controller_state.connected or self.controller_state.connecting:
            return
        self.settings.last_transport = self.transport_var.get()
        self._save_settings()
        self._apply_language()
        self._refresh_target()

    def _refresh_target(self) -> None:
        if self.transport_var.get() == "ble":
            self.target_var.set(self.t("scanning"))
            self.target_menu.configure(values=[self.t("scanning")])
            self.refresh_button.configure(state="disabled")
            self.ble_transport.scan()
        else:
            self._refresh_serial_ports()

    def _refresh_serial_ports(self) -> None:
        try:
            ports = self.serial_transport.list_ports()
            self.serial_ports = {port.display_name: port for port in ports}
            values = list(self.serial_ports) or [self.t("no_serial_ports")]
            self.target_menu.configure(values=values)
            preferred = next(
                (name for name, port in self.serial_ports.items() if port.device == self.settings.last_serial_port),
                values[0],
            )
            self.target_var.set(preferred)
        except Exception as error:
            self.serial_ports = {}
            self.target_menu.configure(values=[str(error)])
            self.target_var.set(str(error))

    def _connect(self) -> None:
        if self.controller_state.connected or self.controller_state.connecting:
            return
        selected = self.target_var.get()
        if self.transport_var.get() == "usb":
            target = self.serial_ports.get(selected)
            if target is None:
                messagebox.showwarning(self.t("connect_title"), self.t("select_target"), parent=self)
                return
            self.active_transport = self.serial_transport
            self.controller_state.begin_connect(TransportKind.USB, target.device)
            self.settings.last_serial_port = target.device
            worker = threading.Thread(target=self._connect_serial_worker, args=(target.device,), daemon=True)
            worker.start()
        else:
            target = self.ble_devices.get(selected)
            if target is None:
                messagebox.showwarning(self.t("connect_title"), self.t("select_target"), parent=self)
                return
            self.active_transport = self.ble_transport
            self.controller_state.begin_connect(TransportKind.BLE, target.name)
            self.ble_transport.connect(target)
        self._set_connection_display("connecting", self.controller_state.target)
        self._render_model()

    def _connect_serial_worker(self, port: str) -> None:
        try:
            self.serial_transport.connect(port)
        except Exception as error:
            self.events.put(TransportFailure(TransportKind.USB, str(error)))
            self.events.put(Disconnected(TransportKind.USB, str(error), expected=False))

    def _drain_events(self) -> None:
        try:
            while True:
                self._handle_transport_event(self.events.get_nowait())
        except queue.Empty:
            pass
        if not self._closing:
            self.after(UI_EVENT_INTERVAL_MS, self._drain_events)

    def _handle_transport_event(self, event: TransportEvent) -> None:
        if isinstance(event, Connected):
            self.controller_state.mark_connected()
            self._persistent_warning = ""
            self._unexpected_disconnect = False
            self.warning_label.grid_remove()
            self.settings.last_transport = event.transport.value
            self._save_settings()
            self._set_connection_display("synchronizing", self.t("connection_sync"))
            self._log("*", f"{event.transport.value.upper()} connected: {event.target}")
        elif isinstance(event, LineReceived):
            self._handle_line(event.line)
        elif isinstance(event, TransportFailure):
            self.controller_state.last_error = event.message
            self._set_connection_display("error", event.message)
            self._log("!", event.message)
        elif isinstance(event, Disconnected):
            was_live = self.controller_state.connected or self.controller_state.connecting
            self.pending.clear()
            self.controller_state.mark_disconnected("" if event.expected else event.reason)
            self.active_transport = None
            if event.expected:
                self._persistent_warning = ""
                self._unexpected_disconnect = False
                self._set_connection_display("disconnected", self.t("connection_idle"))
                self._log("*", self.t("disconnected"))
            elif was_live:
                self._unexpected_disconnect = True
                self._persistent_warning = self.t("unexpected_disconnect")
                self._set_connection_display("error", self.t("unexpected_disconnect"))
                self.warning_label.configure(text=self._persistent_warning)
                self.warning_label.grid()
                self._log("!", self.t("unexpected_disconnect"))
        elif isinstance(event, BleScanCompleted):
            self.refresh_button.configure(state="normal")
            if event.error:
                self.ble_devices = {}
                values = [event.error]
            else:
                self.ble_devices = {device.display_name: device for device in event.devices}
                values = list(self.ble_devices) or [self.t("no_ble_devices")]
            self.target_menu.configure(values=values)
            self.target_var.set(values[0])
        self._render_model()

    def _handle_line(self, line: str) -> None:
        self._log("<", line)
        message = parse_message(line)
        self.controller_state.apply(message)
        if isinstance(message, DeviceStatus):
            self._pop_pending("status")
            if self.controller_state.synchronized:
                self._set_connection_display("connected", f"{self.controller_state.transport.value.upper()} · {self.controller_state.target}")
            self._check_mute_confirmation(message.amplitude_vpp)
        elif isinstance(message, Acknowledgement):
            self._pop_pending("ack")
            amplitude = message.fields.get("A")
            try:
                self._check_mute_confirmation(float(amplitude) if amplitude is not None else None)
            except ValueError:
                pass
            if message.kind in {"cal_complete", "cal_clear"}:
                self._send("STATUS", "status")
        elif isinstance(message, DeviceError):
            pending = self.pending.popleft() if self.pending else None
            translated = self.t.device_error(message.code)
            self._set_connection_display("error", self.t("protocol_error", error=translated))
            self._log("!", f"{translated} [{message.code}]")
            if self.mute_action is not None:
                self._mute_timeout()
            elif pending is None or pending.command != "STATUS":
                self.after(120, lambda: self._send("STATUS", "status") if self.controller_state.connected else None)
        elif isinstance(message, HelpMessage):
            self._pop_pending("help")
            messagebox.showinfo(self.t("help_title"), message.text, parent=self)
        elif isinstance(message, CalibrationProgress):
            if message.stage == "sweep" and message.point and message.total:
                self.calibration_progress.set(min(5, message.point) / 7)
            elif message.stage == "perturb":
                self.calibration_progress.set(6 / 7)
        elif isinstance(message, BootMessage):
            if not message.ready:
                self._persistent_warning = message.text
                self.warning_label.configure(text=self._persistent_warning)
                self.warning_label.grid()
        elif isinstance(message, (BatteryTelemetry, RawMessage)):
            pass
        self._render_model()

    def _send(self, command: str, response: str = "ack") -> None:
        if not self.controller_state.connected or self.active_transport is None:
            return
        command = command.strip()
        try:
            self._log(">", command)
            self.active_transport.send_line(command)
            self.pending.append(PendingCommand(command, response, time.monotonic()))
        except Exception as error:
            self._log("!", str(error))
            self._set_connection_display("error", self.t("write_failed"))

    def _pop_pending(self, response: str) -> PendingCommand | None:
        for index, pending in enumerate(self.pending):
            if pending.response == response:
                del self.pending[index]
                return pending
        return None

    def _check_pending(self) -> None:
        now = time.monotonic()
        expired = [pending for pending in self.pending if now - pending.sent_at >= ACK_TIMEOUT_SECONDS]
        for pending in expired:
            try:
                self.pending.remove(pending)
            except ValueError:
                continue
            self._log("!", f"Response timeout: {pending.command}")
        if not self._closing:
            self.after(250, self._check_pending)

    def _frequency_slide(self, value: float) -> None:
        if self._updating:
            return
        self.frequency_var.set(f"{value:.1f}")
        self._schedule_settings()

    def _amplitude_slide(self, value: float) -> None:
        if self._updating:
            return
        self.amplitude_var.set(f"{value:.1f}")
        self._schedule_settings()

    def _commit_numeric(self) -> None:
        try:
            frequency = float(self.frequency_var.get())
            amplitude = float(self.amplitude_var.get())
            build_settings_command(frequency, amplitude, self.controller_state.waveform)
        except (ValueError, ProtocolValueError) as error:
            messagebox.showerror(self.t("signal_controls"), str(error).replace("_", " "), parent=self)
            self._render_model()
            return
        self.frequency_slider.set(frequency)
        self.amplitude_slider.set(amplitude)
        self._schedule_settings(immediate=True)

    def _waveform_changed(self, selected: str) -> None:
        if self._updating:
            return
        self.controller_state.waveform = "T" if selected == self.t("triangle") else "S"
        self._schedule_settings(immediate=True)

    def _schedule_settings(self, immediate: bool = False) -> None:
        if not self.controller_state.controls_enabled:
            return
        if self.settings_after:
            self.after_cancel(self.settings_after)
            self.settings_after = None
        if immediate:
            self._send_current_settings()
        else:
            self.settings_after = self.after(SETTINGS_DEBOUNCE_MS, self._send_current_settings)

    def _send_current_settings(self) -> None:
        self.settings_after = None
        try:
            command = build_settings_command(
                float(self.frequency_var.get()), float(self.amplitude_var.get()), self.controller_state.waveform
            )
        except (ValueError, ProtocolValueError):
            return
        self._send(command)

    def _trim_slide(self, value: float) -> None:
        if self._updating:
            return
        steps = max(MIN_TRIM_STEPS, min(MAX_TRIM_STEPS, round(value)))
        self.controller_state.user_trim_steps = steps
        self._render_trim()
        self._schedule_trim()

    def _nudge_trim(self, delta: int) -> None:
        steps = max(MIN_TRIM_STEPS, min(MAX_TRIM_STEPS, self.controller_state.user_trim_steps + delta))
        self.controller_state.user_trim_steps = steps
        self.trim_slider.set(steps)
        self._render_trim()
        self._schedule_trim(immediate=True)

    def _schedule_trim(self, immediate: bool = False) -> None:
        if not self.controller_state.controls_enabled:
            return
        if self.trim_after:
            self.after_cancel(self.trim_after)
            self.trim_after = None
        if immediate:
            self._send_trim()
        else:
            self.trim_after = self.after(TRIM_DEBOUNCE_MS, self._send_trim)

    def _send_trim(self) -> None:
        self.trim_after = None
        self._send(build_trim_command(self.controller_state.user_trim_steps))

    def _toggle_ble(self) -> None:
        enabled = bool(self.ble_var.get())
        if not enabled and self.controller_state.transport == TransportKind.BLE:
            if not messagebox.askyesno(self.t("disable_ble_title"), self.t("disable_ble"), parent=self):
                self.ble_var.set(True)
                return
        self._send(f"BLT:{1 if enabled else 0}")

    def _run_calibration(self) -> None:
        if messagebox.askyesno(self.t("cal_confirm_title"), self.t("cal_confirm"), parent=self):
            self._send("CAL")

    def _clear_calibration(self) -> None:
        if messagebox.askyesno(self.t("cal_confirm_title"), self.t("cal_clear_confirm"), parent=self):
            self._send("CAL:CLEAR")

    def _request_disconnect(self, closing: bool) -> None:
        requirement = self.controller_state.disconnect_requirement
        if requirement == DisconnectRequirement.BLOCKED_CALIBRATION:
            messagebox.showwarning(self.t("cal_block_title"), self.t("cal_block"), parent=self)
            return
        if not self.controller_state.connected:
            if closing:
                self._shutdown_now()
            return
        if requirement == DisconnectRequirement.DIRECT:
            self._finish_disconnect(closing)
            return
        prompt = self.t("mute_active") if requirement == DisconnectRequirement.CONFIRM_ACTIVE else self.t("mute_unknown")
        if messagebox.askyesno(self.t("mute_title"), prompt, parent=self):
            self._begin_mute(closing)

    def _begin_mute(self, closing: bool) -> None:
        self.mute_action = "close" if closing else "disconnect"
        self._set_connection_display("synchronizing", self.t("mute_wait"))
        self._send(build_amplitude_command(0.0))
        if self.mute_after:
            self.after_cancel(self.mute_after)
        self.mute_after = self.after(int(ACK_TIMEOUT_SECONDS * 1000), self._mute_timeout)

    def _check_mute_confirmation(self, amplitude: float | None) -> None:
        if self.mute_action is None or amplitude is None or amplitude > 0:
            return
        if self.mute_after:
            self.after_cancel(self.mute_after)
            self.mute_after = None
        closing = self.mute_action == "close"
        self.mute_action = None
        self._finish_disconnect(closing)

    def _mute_timeout(self) -> None:
        if self.mute_action is None:
            return
        if self.mute_after:
            try:
                self.after_cancel(self.mute_after)
            except Exception:
                pass
            self.mute_after = None
        action = self.mute_action
        choice = ChoiceDialog.ask(
            self,
            self.t("mute_timeout_title"),
            self.t("mute_timeout"),
            [
                (self.t("retry"), "retry"),
                (self.t("cancel"), "cancel"),
                (self.t("continue_unsafe"), "unsafe"),
            ],
        )
        if choice == "retry":
            self._begin_mute(action == "close")
        elif choice == "unsafe":
            self.mute_action = None
            self._finish_disconnect(action == "close")
        else:
            self.mute_action = None
            self._render_model()

    def _finish_disconnect(self, closing: bool) -> None:
        if closing:
            self._shutdown_now()
        elif self.active_transport is not None:
            self.active_transport.disconnect()

    def _request_close(self) -> None:
        self._request_disconnect(True)

    def _shutdown_now(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.settings.geometry = self.geometry()
        self._save_settings()
        try:
            self.serial_transport.shutdown()
        finally:
            self.ble_transport.shutdown()
        self.destroy()

    def _render_model(self) -> None:
        self._updating = True
        try:
            self.frequency_var.set(f"{self.controller_state.frequency_hz:.2f}".rstrip("0").rstrip("."))
            self.amplitude_var.set(f"{self.controller_state.amplitude_vpp:.3f}".rstrip("0").rstrip("."))
            self.frequency_slider.set(self.controller_state.frequency_hz)
            self.amplitude_slider.set(self.controller_state.amplitude_vpp)
            self.waveform_control.set(self.t("sine") if self.controller_state.waveform == "S" else self.t("triangle"))
            self.trim_slider.set(self.controller_state.user_trim_steps)
            self._render_trim()
            if self.controller_state.bluetooth_enabled is not None:
                self.ble_var.set(self.controller_state.bluetooth_enabled)
        finally:
            self._updating = False

        controls_state = "normal" if self.controller_state.controls_enabled else "disabled"
        for widget in self.control_widgets:
            widget.configure(state=controls_state)
        utility_state = "normal" if self.controller_state.connected else "disabled"
        self.status_button.configure(state=utility_state)
        self.help_button.configure(state=utility_state)
        self.disconnect_button.configure(
            state="normal" if self.controller_state.connected and not self.controller_state.calibration_running else "disabled"
        )
        connection_locked = self.controller_state.connected or self.controller_state.connecting
        self.connect_button.configure(state="disabled" if connection_locked else "normal")
        self.refresh_button.configure(state="disabled" if connection_locked else "normal")
        self.target_menu.configure(state="disabled" if connection_locked else "normal")
        self.usb_radio.configure(state="disabled" if connection_locked else "normal")
        self.ble_radio.configure(state="disabled" if connection_locked else "normal")

        output = self.controller_state.output_active
        if output is True:
            self.output_badge.configure(text=self.t("output_active"), text_color=COLORS["amber"])
        elif output is False:
            self.output_badge.configure(text=self.t("output_muted"), text_color=COLORS["green"])
        else:
            self.output_badge.configure(text=self.t("output_unknown"), text_color=COLORS["muted"])

        self.positive_value.configure(
            text=f"{self.controller_state.positive_rail:.2f}" if self.controller_state.positive_rail is not None else "—"
        )
        self.negative_value.configure(
            text=f"{self.controller_state.negative_rail:.2f}" if self.controller_state.negative_rail is not None else "—"
        )
        if self.controller_state.battery_percent is None:
            self.battery_value.configure(text="—", text_color=COLORS["muted"])
            self.battery_meter.set(0)
        else:
            health = self.controller_state.battery_percent
            color = COLORS["red"] if health < 20 else COLORS["amber"] if health < 50 else COLORS["green"]
            self.battery_value.configure(text=f"{health}%", text_color=color)
            self.battery_meter.configure(progress_color=color)
            self.battery_meter.set(health / 100)
        self.applied_value.configure(
            text=f"{self.controller_state.amplitude_vpp:.3f} Vpp · {self.t('sine') if self.controller_state.waveform == 'S' else self.t('triangle')}"
            if self.controller_state.output_known
            else "—"
        )
        gain = f"{self.controller_state.calibration_gain:.5f}" if self.controller_state.calibration_gain is not None else "—"
        detail = self.controller_state.calibration_detail
        if detail.startswith("sweep:"):
            point, total = detail.split(":", 1)[1].split("/", 1)
            cal_text = self.t("cal_sweep", point=point, total=total)
            self.calibration_progress.set(min(5, int(point)) / 7)
        elif detail == "perturb":
            cal_text = self.t("cal_perturb")
        elif self.controller_state.calibration_running:
            cal_text = self.t("cal_running")
        elif detail == "complete":
            cal_text = self.t("cal_complete", gain=gain)
            self.calibration_progress.set(1)
        elif detail.startswith("failed:"):
            error_code = detail.removeprefix("failed:")
            cal_text = self.t("cal_failed", error=self.t.device_error(error_code))
            self.calibration_progress.set(0)
        else:
            cal_text = self.t("cal_idle", gain=gain)
            self.calibration_progress.set(0)
        self.calibration_value.configure(text=cal_text)
        bluetooth = (
            self.t("advertising")
            if self.controller_state.bluetooth_enabled is True
            else self.t("off")
            if self.controller_state.bluetooth_enabled is False
            else self.t("unknown")
        )
        self.bluetooth_status_value.configure(text=bluetooth)
        if self.controller_state.battery_available is False:
            self.telemetry_age.configure(text=self.t("telemetry_unavailable"))
        elif self.controller_state.last_telemetry_at:
            self.telemetry_age.configure(
                text=self.t("stale_telemetry") if self.controller_state.telemetry_stale() else self.t("live_telemetry")
            )
        else:
            self.telemetry_age.configure(text=self.t("awaiting_device"))

    def _render_trim(self) -> None:
        steps = self.controller_state.user_trim_steps
        volts = trim_output_volts(steps)
        self.trim_value.configure(
            text=f"{steps:+d} {self.t('steps')} · {volts:+.3f} V"
        )

    def _tick_telemetry(self) -> None:
        if not self._closing:
            self._render_model()
            self.after(1000, self._tick_telemetry)

    def _set_connection_display(self, state: str, detail: str) -> None:
        color = {
            "connected": COLORS["green"],
            "connecting": COLORS["amber"],
            "synchronizing": COLORS["amber"],
            "error": COLORS["red"],
            "disconnected": COLORS["muted"],
        }.get(state, COLORS["muted"])
        self.connection_badge.configure(text=self.t(state), text_color=color)
        self.connection_detail.configure(text=detail, text_color=color if state == "error" else COLORS["muted"])
        if state != "error" and not self._persistent_warning:
            self.warning_label.grid_remove()

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()
        self.log_toggle.configure(text=self.t("hide_log") if self._log_visible else self.t("show_log"))

    def _log(self, direction: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[{stamp}] {direction} {message}")
        self.log_lines = self.log_lines[-160:]
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("end", "\n".join(self.log_lines))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _copy_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.log_lines))

    def _clear_log(self) -> None:
        self.log_lines.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _save_settings(self) -> None:
        try:
            self.settings_store.save(self.settings)
        except OSError as error:
            self._log("!", f"Settings: {error}")


def main() -> None:
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        return
    app = FdemControllerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
