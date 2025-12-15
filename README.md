# 🚗📹 YOLO Parking Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![YOLOv11](https://img.shields.io/badge/YOLO-v11-00d4ff.svg)](https://github.com/ultralytics/ultralytics)

Advanced parking monitoring system based on YOLOv11, featuring real-time video analysis, collision detection, license plate recognition (ALPR), and person safety features.

## 🌟 Key Features

### Core Functionality
*   **Multi-Camera Monitoring**: Support for multiple RTSP streams (Hikvision, Dahua, etc.)
*   **AI Video Analysis**: Uses YOLOv11 for vehicle and person detection and tracking
*   **Modular Architecture**: Lazy loading of AI models - only load what you need (CPU/GPU friendly)
*   **Interactive Dashboard**: Complete control panel for configuration and real-time monitoring

### Advanced Detection Features
*   **Collision Detection**: Dedicated algorithm to identify vehicle-to-vehicle collisions
*   **License Plate Recognition (ALPR)**: Integration with EasyOCR for automatic license plate reading
*   **Person Safety**:
    *   **Loitering Detection**: Detects people loitering in an area for extended periods
    *   **Fall Detection**: Identifies potential person falls based on aspect ratio and velocity
*   **Person-Vehicle Interaction**: Detects suspicious behavior when people move around multiple vehicles
*   **Person Wall Writing Detection**: Detects when people are writing on walls

### Performance Optimizations
*   **Frame Buffer**: Intelligent frame buffering for smooth RTSP streaming
*   **Lazy Model Loading**: Models loaded only when needed
*   **Automatic Model Selection**: Chooses optimal YOLO model based on enabled features
*   **View-Only Mode**: Zero AI overhead when just viewing streams

## 📂 Project Structure

```
.
├── main_panel.py              # Main entry point: Complete control panel
├── control_panel.py           # Alternative entry point (wrapper)
├── video_analysis.py          # Core video analysis and module orchestration
├── camera_monitor.py          # Continuous camera monitoring script
├── multi_preview_cameras.py   # Multi-camera preview application
│
├── modules/                    # Functional modules
│   ├── core/                   # Always loaded (lightweight)
│   │   ├── statistics.py       # StatisticsCollector
│   │   └── event_logger.py     # EventLogger (JSON logging)
│   ├── detection/              # Optional detection modules
│   │   └── yolo_module.py      # YOLO lazy loading and model selection
│   ├── features/               # Optional feature modules
│   │   ├── collision_module.py         # Vehicle collision detection
│   │   ├── ocr_module.py              # License plate recognition
│   │   ├── person_safety_module.py    # Person loitering & fall detection
│   │   ├── person_vehicle_interaction_module.py  # Person-vehicle interaction
│   │   └── person_wall_writing_module.py         # Wall writing detection
│   └── utils/                  # Utilities
│       └── frame_buffer.py     # Frame buffering for RTSP streams
│
├── config/                     # Configuration files
│   ├── cameras.json            # RTSP camera list
│   ├── collision.json         # Collision detection parameters
│   ├── rtsp.json              # RTSP credentials (create from template)
│   └── zones.json             # Exclusion/interest zones
│
├── tools/                      # Utility scripts and tests
│   ├── setup_cameras.py       # Camera configuration wizard
│   ├── setup_roi.py           # Graphical ROI drawing tool
│   ├── verify_system.py       # System diagnostics
│   ├── quick_test.py          # Quick functionality test
│   ├── test_gui.py            # GUI testing
│   ├── test_rtsp.py           # RTSP connection testing
│   ├── test_scan_logic.py     # Camera scanning logic test
│   └── test_single_camera.py  # Single camera test
│
├── collision_detector/         # Legacy collision detection package
│   ├── detector.py            # Core collision detection logic
│   ├── tracking.py            # Object tracking
│   ├── mask_analysis.py       # Segmentation mask analysis
│   └── utils.py               # Utility functions
│
├── logs/                       # Event logs (JSON format)
├── runs/                       # YOLO output (detections, tracking)
│   ├── detect/                # Detection results
│   └── track/                 # Tracking results
│
└── TEST VIDEO COLLISIONE/      # Standalone collision test application
    ├── main.py                # Test application entry point
    ├── collision_detector.py  # Collision detection module
    └── video_processor.py     # Video processing
```

## 🚀 Installation

### Prerequisites

*   **Python**: 3.8 or higher
*   **Operating System**: Windows, Linux, or macOS
*   **GPU** (optional but recommended): NVIDIA GPU with CUDA support for faster processing
*   **Disk Space**: ~500 MB for models and dependencies

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-username/yolo-parking-monitor.git
cd yolo-parking-monitor
```

### Step 2: Create Virtual Environment (Recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### Step 3: Install Dependencies

**For NVIDIA GPU (Recommended):**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install ultralytics opencv-python-headless easyocr
pip install -r requirements.txt
```

**For CPU only:**
```bash
pip install ultralytics opencv-python easyocr
pip install -r requirements.txt
```

### Step 4: Configure RTSP Credentials

1. Copy the example configuration files:
   ```bash
   # For RTSP credentials
   cp rtsp_config.json.template rtsp_config.json
   # Or use the config directory version
   cp config/rtsp.json.example config/rtsp.json
   
   # For camera configuration
   cp config/cameras.json.example config/cameras.json
   ```

2. Edit `config/rtsp.json` (or `rtsp_config.json`) and add your RTSP credentials:
   ```json
   {
     "ip": "192.168.1.124",
     "port": "554",
     "user": "User",
     "password": "your_password_here"
   }
   ```

3. Edit `config/cameras.json` and configure your camera URLs (replace `YOUR_PASSWORD` with actual password).

**⚠️ Security Note**: 
- The `config/rtsp.json` and `config/cameras.json` files are excluded from git for security
- **Never commit files with real passwords!**
- Always use `.example` or `.template` files for version control

## 🎮 Usage

### Quick Start

Launch the main control panel:
```bash
python main_panel.py
```

Or use the alternative entry point:
```bash
python control_panel.py
```

### Command Line Usage

Analyze a video file:
```bash
python video_analysis.py --video path/to/video.mp4
```

Process RTSP stream:
```bash
python video_analysis.py --stream rtsp://user:password@ip:port/stream
```

### Configuration

#### 1. Camera Setup

**Option A: Using the GUI**
- Launch `main_panel.py`
- Use the camera configuration section to add/remove cameras

**Option B: Manual Configuration**
- Edit `config/cameras.json` directly
- Or use the setup wizard:
  ```bash
  python tools/setup_cameras.py
  ```

#### 2. Define Zones (ROI)

Use the graphical ROI tool:
```bash
python tools/setup_roi.py
```

This allows you to:
- Draw exclusion zones (areas to ignore)
- Define interest zones (areas to monitor)
- Save zones to `config/zones.json`

#### 3. Collision Detection Parameters

Edit `config/collision.json` to adjust:
- Collision sensitivity thresholds
- Person safety parameters (loitering, fall detection)
- Movement detection thresholds

## 🧩 Modules and Performance

The system uses lazy loading - AI models are only loaded when needed:

### Model Selection Logic

| Feature Enabled | Model Used | Size | Speed | Use Case |
|----------------|------------|------|-------|----------|
| View Only | None | 0 MB | ⚡⚡⚡ | Just viewing streams |
| Basic Tracking | `yolo11n.pt` | ~6 MB | ⚡⚡⚡ | Fast, lightweight |
| License Plates | `yolo11s.pt` | ~22 MB | ⚡⚡ | Better accuracy for small objects |
| Collision Detection | `yolo11n-seg.pt` | ~6 MB | ⚡⚡ | Segmentation masks required |
| Person Safety | `yolo11n.pt` | ~6 MB | ⚡⚡⚡ | Fast person detection |

**Automatic Selection:**
1. If **Collision Detection** enabled → uses `yolo11n-seg.pt` (segmentation needed)
2. If **License Plates** enabled → uses `yolo11s.pt` (better precision)
3. Otherwise → uses `yolo11n.pt` (fastest)

### Module Loading

```python
# Example: Analyze video with specific features
from video_analysis import analyze_video

analyze_video(
    video_path=Path("video.mp4"),
    model_name="auto",              # Auto-select optimal model
    enable_plates=False,            # License plate recognition
    enable_collision=True,          # Collision detection
    enable_person_safety=True,       # Person safety features
    enable_person_vehicle_interaction=False,  # Person-vehicle interaction
    enable_wall_writing=False,      # Wall writing detection
)
```

### Core Modules (Always Loaded)

- **StatisticsCollector**: Real-time statistics (FPS, object counts, events)
- **EventLogger**: Structured JSON event logging

### Optional Modules

- **YOLOModule**: Lazy-loaded YOLO model
- **OCRModule**: EasyOCR integration (configurable languages, quantization)
- **CollisionModule**: Vehicle collision detection
- **PersonSafetyModule**: Loitering and fall detection (independent from collision)
- **PersonVehicleInteractionModule**: Detects suspicious person-vehicle interactions
- **PersonWallWritingModule**: Detects wall writing behavior

## 🛠️ Utility Tools

The `tools/` directory contains helpful scripts:

| Tool | Description |
|------|-------------|
| `setup_cameras.py` | Interactive wizard to configure RTSP cameras |
| `setup_roi.py` | Graphical tool to draw ROI zones |
| `verify_system.py` | Complete system diagnostics and module verification |
| `quick_test.py` | Quick functionality test |
| `test_rtsp.py` | Test RTSP connection without processing |
| `test_single_camera.py` | Test individual camera streams |
| `test_scan_logic.py` | Test camera scanning logic |

### System Verification

Run the comprehensive system check:
```bash
python tools/verify_system.py
```

This verifies:
- Module imports
- Core functionality
- YOLO, OCR, and Person Safety modules
- Configuration files
- Dependencies

## 📊 Configuration Files

### `config/cameras.json`
List of RTSP cameras with URLs, channel numbers, and active status.

### `config/collision.json`
Collision detection parameters:
- Movement thresholds
- IoU thresholds
- Debounce settings
- Person safety parameters (loitering time, fall detection thresholds)

### `config/rtsp.json`
RTSP credentials (create from `rtsp_config.json.template`):
- NVR IP and port
- Username and password

### `config/zones.json`
Defined zones for exclusion or special monitoring.

## 📝 Logging

Events are logged in JSON format to the `logs/` directory:
- Timestamp
- Event type
- Object IDs
- Positions
- Additional metadata

Log files are organized by date and camera for easy analysis.

## 🐛 Troubleshooting

### Common Issues

**1. RTSP Connection Failed**
- Verify credentials in `config/rtsp.json`
- Check camera IP accessibility (ping test)
- Verify firewall settings (port 554)
- Test with VLC: `vlc rtsp://user:pass@ip:port/stream`

**2. Module Import Errors**
```bash
# Verify system
python tools/verify_system.py

# Reinstall dependencies
pip install -r requirements.txt
```

**3. Low Performance**
- Reduce image size (`imgsz` parameter)
- Increase frame skip rate
- Disable unnecessary features
- Use smaller YOLO model (`yolo11n.pt`)

**4. Tkinter Not Found (Linux)**
```bash
sudo apt-get install python3-tk
```

**5. CUDA/GPU Issues**
- Verify CUDA installation: `nvidia-smi`
- Reinstall PyTorch with CUDA support
- Check CUDA version compatibility

### Diagnostic Commands

```bash
# Test RTSP connection
python tools/test_rtsp.py

# Test single camera
python tools/test_single_camera.py

# Quick functionality test
python tools/quick_test.py

# Full system verification
python tools/verify_system.py
```

## 📚 Additional Documentation

- **[ARCHITETTURA_MODULARE.md](ARCHITETTURA_MODULARE.md)**: Detailed modular architecture documentation
- **[GUIDA_TEST.md](GUIDA_TEST.md)**: Complete testing guide (in Italian)
- **[REPORT_ERRORI.md](REPORT_ERRORI.md)**: Known issues and solutions
- **[MODIFICHE_APPLICATE.md](MODIFICHE_APPLICATE.md)**: Recent changes and updates

## 🧪 Testing

See [GUIDA_TEST.md](GUIDA_TEST.md) for comprehensive testing procedures.

Quick test checklist:
- [ ] Control panel launches
- [ ] Video file analysis works
- [ ] Vehicle and person detection works
- [ ] Collision detection works
- [ ] Person safety features work
- [ ] RTSP streaming works
- [ ] Configuration saves/loads correctly

## 🔧 Development

### Project Architecture

The system uses a modular architecture with lazy loading:
- Core modules are always loaded (lightweight)
- Feature modules load on demand
- Models are selected automatically based on enabled features
- Thread-safe statistics and logging

### Adding New Features

1. Create module in `modules/features/`
2. Implement lazy loading pattern
3. Add to `video_analysis.py` orchestration
4. Update configuration files if needed
5. Add tests in `tools/`

## 🔒 Security

**Important Security Notes:**
- Never commit files with real passwords or credentials
- Configuration files with credentials (`config/rtsp.json`, `config/cameras.json`) are excluded from git
- Always use `.example` or `.template` files for version control
- See [SECURITY.md](SECURITY.md) for security best practices and vulnerability reporting

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

Please read our [Contributing Guidelines](CONTRIBUTING.md) for details on:
- Code style and standards
- How to report bugs
- How to suggest features
- The pull request process

For major changes:
1. Open an issue first to discuss what you would like to change
2. Ensure tests pass (`python tools/verify_system.py`)
3. Update documentation as needed
4. Follow the security guidelines (never commit credentials!)

## 🙏 Acknowledgments

- [Ultralytics](https://github.com/ultralytics/ultralytics) for YOLOv11
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) for license plate recognition
- OpenCV community for computer vision tools

## 📧 Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check existing documentation in the repository
- Review `REPORT_ERRORI.md` for known issues

---

**Made with ❤️ for parking monitoring and security**
