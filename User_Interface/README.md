# FDEM TX Controller / Controlador TX FDEM

A standalone Windows 10/11 controller for the FDEM transmitter. It provides the same controls as the web application through either USB serial or Bluetooth Low Energy, requires no internet connection, and can be distributed as a portable application folder.

Controlador independiente para Windows 10/11 del transmisor FDEM. Ofrece los mismos controles que la aplicación web mediante USB serie o Bluetooth Low Energy, no necesita conexión a Internet y se puede distribuir como una carpeta de aplicación portátil.

## English

### Features

- USB serial at 115200 baud and BLE using the transmitter's Nordic UART Service.
- Frequency (1–8,000 Hz), applied output amplitude (0–20 Vpp), sine/triangle waveform, and manual output-offset trim.
- Live +12 V/−12 V rail telemetry, battery estimate, output state, Bluetooth state, and calibration gain/progress.
- Full gain-calibration and calibration-clear commands.
- English/Spanish interface, timestamped raw traffic log, and translated firmware errors.
- Safety-aware disconnect: active or unknown output is muted and confirmed before an orderly disconnect. Disconnect/close is blocked during calibration because the current firmware cannot cancel calibration.

The application never stores or automatically reapplies signal settings. On every connection it reads the actual transmitter state with `STATUS`.

### Development setup

Use 64-bit Python 3.12 on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fdem_controller
```

Run the automated suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The protocol/model tests can also run without GUI dependencies when `src` is placed on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$PWD\src"
py -m unittest discover -s tests -v
```

### Build and distribution

Run:

```powershell
.\build.ps1
```

The script creates a Python 3.12 virtual environment when necessary, installs pinned dependencies, generates the Windows icon, runs all tests, builds with PyInstaller, and smoke-tests the result. The distributable output is:

The script rejects an existing `.venv` created with another Python version; recreate it with `py -3.12 -m venv .venv` before building.

```text
dist\FDEM TX Controller\
    FDEM TX Controller.exe
    _internal\...
```

Distribute the entire `FDEM TX Controller` folder, not only the `.exe`. Test the copied folder on a Windows 10/11 x64 machine without Python installed.

> **Run only `dist\FDEM TX Controller\FDEM TX Controller.exe`.** The similarly named executable that PyInstaller temporarily creates under `build\FDEM_TX_Controller` is an incomplete build intermediate and will report that `python312.dll` or `python314.dll` is missing. The build script removes that intermediate after a successful build.

Use `build.ps1 -SkipInstall` for repeat builds after the virtual environment is prepared.

### Connection workflow

1. Power the transmitter.
2. Select **USB serial** and the ESP32 COM port, or select **Bluetooth**, scan, and choose `FDEM-TX`.
3. Connect and wait for **CONNECTED**. Controls remain locked until a valid `STATUS` response is received.
4. Change controls as required. Displayed amplitude is replaced by the value actually applied by the digital potentiometer after firmware acknowledgement.
5. Use **Disconnect**. If output is active or unknown, confirm the mute request and wait for the device acknowledgement.

USB connections enable one-second telemetry automatically and disable it before an orderly disconnect. BLE telemetry is always delivered while connected.

### Calibration safety

Gain calibration sweeps the configured full output range for approximately 56 seconds. Signal controls, disconnect, and normal application close are blocked until calibration completes or fails. Keep the equipment and load prepared for the full 20 Vpp sweep.

An unexpected cable or radio loss cannot guarantee a mute command. The interface therefore displays a persistent red warning that the transmitter may remain energized.

### Troubleshooting

- **COM port missing:** select **Refresh**, check Device Manager, close serial terminals, and reconnect the USB cable.
- **Access denied:** another program already owns the COM port.
- **BLE device missing:** verify Windows Bluetooth is enabled, the adapter supports BLE, and the transmitter's Bluetooth LED is advertising. Scan again near the device.
- **BLE cannot reconnect after advertising was disabled:** connect through USB and enable **Bluetooth advertising**.
- **Controls remain disabled:** inspect the command log for a missing or invalid `STATUS` response and confirm compatible firmware is installed.
- **Rail telemetry unavailable:** the firmware reports `BAT:UNAVAILABLE` when monitoring pins are not configured.

### Hardware acceptance checklist

- Connect over USB and BLE independently; verify initial status synchronization.
- Exercise 1 Hz/8 kHz, 0 Vpp/20 Vpp, both waveforms, and ±255 trim limits.
- Confirm the UI shows the firmware-applied amplitude rather than only the requested value.
- Verify live rail values and stale indication after telemetry stops.
- Complete gain calibration, observe every sweep/perturb stage, then clear it.
- Confirm the Bluetooth-disable recovery warning.
- Disconnect with active output and verify `A:0` is acknowledged before the link closes.
- Force a cable/radio loss and verify the persistent unknown-output warning.
- Launch the packaged folder on a clean Windows x64 machine without Python.

## Español

### Funciones

- USB serie a 115200 baudios y BLE mediante el servicio Nordic UART del transmisor.
- Frecuencia (1–8.000 Hz), amplitud de salida aplicada (0–20 Vpp), onda senoidal/triangular y ajuste manual del offset.
- Telemetría en directo de los raíles +12 V/−12 V, estimación de batería, estado de salida, Bluetooth y progreso/ganancia de calibración.
- Comandos para ejecutar y borrar la calibración de ganancia.
- Interfaz en inglés/español, registro de tráfico con hora y errores del firmware traducidos.
- Desconexión segura: si la salida está activa o se desconoce, se solicita y confirma el silencio antes de desconectar. La desconexión y el cierre se bloquean durante la calibración porque el firmware actual no puede cancelarla.

La aplicación nunca guarda ni vuelve a aplicar automáticamente los ajustes de señal. En cada conexión lee el estado real del transmisor mediante `STATUS`.

### Preparación para desarrollo

Use Python 3.12 de 64 bits en Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fdem_controller
```

Ejecute las pruebas con:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Compilación y distribución

Ejecute:

```powershell
.\build.ps1
```

El script crea el entorno Python 3.12, instala las versiones fijadas, genera el icono, ejecuta las pruebas, compila con PyInstaller y comprueba el ejecutable. Distribuya la carpeta completa `dist\FDEM TX Controller`, no solo el archivo `.exe`. Compruebe la copia en Windows 10/11 x64 sin Python instalado.

> **Ejecute únicamente `dist\FDEM TX Controller\FDEM TX Controller.exe`.** El ejecutable de nombre parecido que PyInstaller crea temporalmente en `build\FDEM_TX_Controller` está incompleto y mostrará que falta `python312.dll` o `python314.dll`. El script de compilación elimina ese archivo intermedio después de compilar correctamente.

Si `.venv` se creó con otra versión de Python, el script detendrá la compilación; vuelva a crearlo con `py -3.12 -m venv .venv`.

### Uso

1. Encienda el transmisor.
2. Elija **Serie USB** y el puerto COM del ESP32, o seleccione **Bluetooth**, busque y elija `FDEM-TX`.
3. Conecte y espere a **CONECTADO**. Los controles permanecen bloqueados hasta recibir un `STATUS` válido.
4. Modifique los controles. La amplitud mostrada se sustituye por la que el firmware aplicó realmente con el potenciómetro digital.
5. Pulse **Desconectar**. Si la salida está activa o es desconocida, confirme la solicitud de silencio y espere su reconocimiento.

USB habilita automáticamente la telemetría de un segundo y la deshabilita al desconectar ordenadamente. BLE entrega telemetría mientras exista conexión.

### Seguridad de calibración

La calibración de ganancia recorre todo el rango durante unos 56 segundos. Los controles de señal, la desconexión y el cierre normal quedan bloqueados hasta que termine o falle. Prepare el equipo y la carga para el barrido completo de 20 Vpp.

Una pérdida inesperada del cable o de la radio no permite garantizar el silencio. La interfaz muestra entonces un aviso rojo persistente indicando que el transmisor puede seguir energizado.

### Solución de problemas

- **No aparece el puerto COM:** pulse **Actualizar**, revise el Administrador de dispositivos, cierre otros terminales serie y reconecte el cable.
- **Acceso denegado:** otro programa está utilizando el puerto COM.
- **No aparece BLE:** active Bluetooth en Windows, compruebe que el adaptador admite BLE y que el LED Bluetooth del transmisor anuncia. Repita la búsqueda cerca del equipo.
- **BLE no reconecta tras desactivar la publicidad:** conecte por USB y active **Publicidad Bluetooth**.
- **Los controles siguen bloqueados:** abra el registro, busque una respuesta `STATUS` ausente/no válida y compruebe la versión del firmware.
- **Telemetría no disponible:** el firmware informa `BAT:UNAVAILABLE` si los pines de monitorización no están configurados.

### Lista de aceptación con hardware

- Conectar por USB y BLE por separado y verificar la sincronización inicial.
- Probar 1 Hz/8 kHz, 0 Vpp/20 Vpp, ambas ondas y los límites ±255 del ajuste.
- Confirmar que la interfaz presenta la amplitud aplicada por el firmware.
- Verificar los raíles en directo y el aviso de telemetría desactualizada.
- Completar y borrar la calibración observando el barrido y la perturbación.
- Comprobar el aviso al desactivar la publicidad Bluetooth.
- Desconectar con salida activa y verificar que se reconoce `A:0` antes de cerrar el enlace.
- Forzar la pérdida del cable/radio y comprobar el aviso persistente de salida desconocida.
- Ejecutar la carpeta compilada en Windows x64 sin Python instalado.
