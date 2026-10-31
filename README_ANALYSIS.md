# 🚦 TrafficSentinel AI — Next-Generation Intelligent Transportation System (ITS) & Decision Support System (DSS)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19.0-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![Tailwind CSS v4](https://img.shields.io/badge/Tailwind_CSS-v4.0-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Ultralytics YOLO26/v8](https://img.shields.io/badge/YOLO-v8_/_v26-FF6F00?style=for-the-badge&logo=yolo&logoColor=white)](https://ultralytics.com/)
[![ByteTrack](https://img.shields.io/badge/Tracker-ByteTrack-8A2BE2?style=for-the-badge)](https://github.com/ifzhang/ByteTrack)
[![EasyOCR](https://img.shields.io/badge/OCR-EasyOCR_AIS--015-4CAF50?style=for-the-badge)](https://github.com/JaidedAI/EasyOCR)
[![OpenVINO](https://img.shields.io/badge/Inference-OpenVINO_2024.3-00549F?style=for-the-badge&logo=intel&logoColor=white)](https://www.intel.com/content/www/us/en/developer/tools/openvino-toolkit/overview.html)
[![Tests Passing](https://img.shields.io/badge/Tests-31%2F31_Passed_(100%25)-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](./tests)

---

## 📑 Table of Contents
1. [Executive Summary & Project Overview](#-executive-summary--project-overview)
2. [Non-Technical Overview & Civic Value Proposition](#-non-technical-overview--civic-value-proposition)
   - [The Problem with Modern Traffic Enforcement](#the-problem-with-modern-traffic-enforcement)
   - [How TrafficSentinel AI Solves This](#how-trafficsentinel-ai-solves-this)
   - [Legal Defensibility & Explainability](#legal-defensibility--explainability)
   - [Two-Tier Enforcement Model](#two-tier-enforcement-model)
   - [Urban Mobility & Safety Impact](#urban-mobility--safety-impact)
3. [System Architecture & Concurrency Model](#-system-architecture--concurrency-model)
   - [High-Level Architectural Diagram](#high-level-architectural-diagram)
   - [Latency Budget & Thread Decoupling](#latency-budget--thread-decoupling)
4. [Technical Modules & Core Algorithms](#-technical-modules--core-algorithms)
   - [1. Real-Time Object Detection & Tracking](#1-real-time-object-detection--tracking)
   - [2. Semantic Spatial Scene Graph](#2-semantic-spatial-scene-graph)
   - [3. Calibrated Ground-Plane Homography](#3-calibrated-ground-plane-homography)
   - [4. Rule Engine & Deterministic Violation Logic](#4-rule-engine--deterministic-violation-logic)
   - [5. Indian-Standard ANPR Engine (AIS-015 / MoRTH)](#5-indian-standard-anpr-engine-ais-015--morth)
   - [6. Multi-Camera Corridor Tracking with Branch Prediction](#6-multi-camera-corridor-tracking-with-branch-prediction)
   - [7. Spatio-Temporal Route Anomaly & Cloned Plate Detection](#7-spatio-temporal-route-anomaly--cloned-plate-detection)
   - [8. Real-Time Telegram Mobile Alerting Engine](#8-real-time-telegram-mobile-alerting-engine)
   - [9. Video & Image Evidence Writer](#9-video--image-evidence-writer)
   - [10. High-Performance SQLite Asynchronous Storage](#10-high-performance-sqlite-asynchronous-storage)
5. [Complete File-by-File & Codebase Directory Walkthrough](#-complete-file-by-file--codebase-directory-walkthrough)
6. [Technology Stack Matrix](#-technology-stack-matrix)
7. [Tri-Interface Frontend Architecture](#-tri-interface-frontend-architecture)
   - [1. Modern Dahua-Style DSS Ops-Center (React 19 + TypeScript)](#1-modern-dahua-style-dss-ops-center-react-19--typescript)
   - [2. Standalone Monitoring Center (`static/index.html`)](#2-standalone-monitoring-center-staticindexhtml)
   - [3. Interactive Prototyping Dashboard (`app.py` via Streamlit)](#3-interactive-prototyping-dashboard-apppy-via-streamlit)
   - [4. Pure CLI Headless Benchmarking Engine (`run_headless.py`)](#4-pure-cli-headless-benchmarking-engine-run_headlesspy)
8. [Backend REST API & WebSocket Specifications](#-backend-rest-api--websocket-specifications)
9. [Camera Calibration & Mathematical Grounding Guide](#-camera-calibration--mathematical-grounding-guide)
10. [Installation, Setup & Quickstart Guide](#-installation-setup--quickstart-guide)
11. [Testing, Verification & Quality Assurance](#-testing-verification--quality-assurance)

---

## 🌟 Executive Summary & Project Overview

**TrafficSentinel AI** is an industrial-grade, edge-to-cloud **Intelligent Transportation System (ITS)** and **Decision Support System (DSS)** designed for automated municipal traffic law enforcement, real-time safety monitoring, and urban mobility intelligence.

Built on computer vision and geometric spatial modeling, the platform continuously analyzes multi-camera CCTV video streams to detect moving traffic violations, read Indian High Security Registration Plates (HSRP), reconstruct vehicle trajectories across road networks, identify cloned license plates, and dispatch instant legal evidence packages to traffic police authorities.

Unlike black-box end-to-end neural networks that hallucinate offenses or systems that guess speed from pixel counts, TrafficSentinel AI combines **state-of-the-art neural object detection (YOLO26 / YOLOv8)** with **rigorous ground-plane metric geometry (Homography perspective projection)**, **auditable rule-based reasoning graphs**, and a **two-tier human-in-the-loop review architecture**.

---

## 🏛️ Non-Technical Overview & Civic Value Proposition

### The Problem with Modern Traffic Enforcement
1. **Manual Traffic Policing is Unsustainable:** Cities have thousands of intersections; human traffic officers can physically monitor only a tiny fraction of them. Manual stops also cause congestion and introduce safety risks and corruption.
2. **Flawed First-Generation "Smart" Cameras:**
   - **False Red-Light Violations:** Naive cameras trigger a violation whenever a car's bounding box is horizontally aligned with a red lamp—fining every law-abiding driver properly stopped at the line.
   - **Erroneous Speeding Fines:** Using a single "pixels-per-meter" conversion ignores 3D optical perspective. Vehicles 10 meters away move far more pixels than vehicles 60 meters away, leading to speed errors of 300% to 500%.
   - **Unreliable Helmet/Seatbelt Heuristics:** Guessing helmet compliance from fixed skin-tone HSV thresholds fails across varied human skin tones and misidentifies black hair as a black helmet.
   - **Lack of Legal Evidence:** An isolated photo crop rarely proves that a motorist ran a red light or drove against the flow of traffic. Without synchronized video proof, citations are routinely dismissed in court.

### How TrafficSentinel AI Solves This
* **Physically Grounded Measurement:** The system performs actual metric calibration per camera using a $3 \times 3$ perspective transformation matrix ($H$). Distance and speed are measured in real-world meters and km/h, not pixels.
* **Stop-Line Crossing Verification:** A red-light violation requires mathematical proof that the vehicle's road-contact point physically crossed the stop-line vector between frames while the traffic light HSV spectrum confirmed RED.
* **Fail-Safe Integrity ("Abstain Rather than Guess"):** If a camera has not been calibrated for speed or stop lines, those specific rules disable themselves automatically rather than producing fabricated fines.
* **Synchronized Video Proof:** Every citation includes a high-resolution plate crop, an overview scene crop, and a 4-second synchronized H.264 video clip ($\pm 2$ seconds around the event).

```
                      ┌──────────────────────────────────────────┐
                      │    TrafficSentinel AI Enforcement Flow   │
                      └──────────────────────────────────────────┘
                                           │
                           Vehicle Infraction Detected
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
      Composite Conf >= 0.65                         Composite Conf < 0.65
      & Verified License Plate                       OR Plate Unread / Ambiguous
                    │                                             │
                    ▼                                             ▼
       ┌────────────────────────┐                    ┌─────────────────────────┐
       │   TIER 1: AUTO-ISSUE   │                    │  TIER 2: REVIEW QUEUE   │
       │   Automated e-Challan  │                    │ Human Officer Auditing  │
       │   Telegram Alert Sent  │                    │ Approve (Challan) / Drop│
       └────────────────────────┘                    └─────────────────────────┘
```

### Legal Defensibility & Explainability
Every violation generated by TrafficSentinel AI attaches a human-readable **Reasoning Chain** (e.g. `person#7 ON motorcycle#3 (assoc 0.61) -> head crop classified NO_HELMET (0.84)`). If a citizen challenges a challan in court, the transport department can produce:
1. The mathematical ground-plane coordinates and velocities.
2. The exact detection confidence scores.
3. The video clip demonstrating the complete event sequence.
4. The full auditable rule decision path.

### Two-Tier Enforcement Model
* **Tier 1 (Auto-Issue):** When a violation exceeds the strict composite confidence threshold (default: $\ge 0.65$) AND has a validated license plate, an e-challan is automatically filed and dispatched.
* **Tier 2 (Review Queue):** Borderline cases, uncertain helmet classifications, or partially occluded plates land in an interactive **Officer Review Queue**. A human officer reviews the high-res crop, plays the 4-second clip, edits or verifies the plate, and makes the final legal determination.

### Urban Mobility & Safety Impact
* **Near-Miss & Conflict Analytics:** Evaluates inter-vehicle time-to-collision ($TTC$) in world coordinates. Junctures with frequent near-misses highlight dangerous road geometry before fatal accidents occur.
* **Congestion & Flow Telemetry:** Logs average passage speeds, vehicle counts, and queue lengths per camera every 5 seconds.
* **Blacklist & Stolen Vehicle Interception:** Instantly matches scanned plates against police databases and flags stolen or wanted vehicles in sub-second time.

---

## ⚡ System Architecture & Concurrency Model

### High-Level Architectural Diagram

```mermaid
flowchart TD
    subgraph Video Input
        SRC["Video Source (RTSP / MP4 / Webcam)"]
        VT["VideoSource Thread (Drop Stale Frames)"]
        SRC --> VT
    end

    subgraph Main Real-Time Loop (25-30 FPS)
        VT -->|"Latest Frame"| DET["YOLO26 / YOLOv8 Detection"]
        DET -->|"BBoxes + Conf"| TRK["ByteTrack Assignment (Stable TrackIDs)"]
        TRK -->|"Kinematics + Foot"| HOM["Ground-Plane Homography (Meters/Speed)"]
        HOM --> SG["Spatial Scene Graph (person ON vehicle)"]
        SG --> RE["Rule Engine (6 Violation Checks)"]
    end

    subgraph Asynchronous Worker Queues (Non-Blocking)
        RE -->|"Plate Crop"| Q_OCR["OCR Queue (maxsize=8)"]
        RE -->|"Violation Event"| Q_EV["Evidence Queue (maxsize=32)"]
        RE -->|"DB Record"| Q_DB["DB Write Queue (maxsize=512)"]
        RE -->|"Alert Job"| Q_AL["Telegram Queue (maxsize=100)"]

        Q_OCR --> WORK_OCR["OCRWorker (EasyOCR + AIS-015 Disambiguation)"]
        Q_EV --> WORK_EV["EvidenceWriter (JPEG Crop + Ring-Buffer MP4 Clip)"]
        Q_DB --> WORK_DB["Database Worker (SQLite WAL Mode)"]
        Q_AL --> WORK_AL["Telegram Worker (Instant Police Mobile Alerts)"]
    end

    subgraph Corridors & City Scale
        WORK_OCR -->|"Plate Sighting"| NET["RoadNetwork Graph + MultiCameraTracker"]
        NET -->|"Fork Splitting"| DEAD["Dead-Reckoning Prediction"]
        NET -->|"Cross-Cam Speed > 160km/h"| ANOM["Route Anomaly / Cloned Plate Alert"]
    end

    subgraph Client Presentation Layer
        WORK_DB --> API["FastAPI Backend (server.py:8765)"]
        API -->|"MJPEG /stream"| UI1["Dahua DSS React Ops-Center"]
        API -->|"WebSocket /ws/events"| UI1
        API --> UI2["HTML5/Leaflet Standalone Dashboard"]
        API --> UI3["Streamlit Prototyping GUI"]
    end
```

### Latency Budget & Thread Decoupling

Measured on standard 4-Core Intel CPU / 16GB RAM / 720p Input (`imgsz=480`):

| Pipeline Stage | Execution Latency | Concurrency Domain | Latency Decoupling Mechanism |
|---|---|---|---|
| **Frame Decode** | 6 – 12 ms | Dedicated Worker Thread | Drops stale frames; always serves latest reality |
| **YOLO26/v8 Inference** | 24 – 38 ms | Main Pipeline Thread | OpenVINO CPU acceleration / CUDA FP16 |
| **ByteTrack Assignment** | ~1 ms | Main Pipeline Thread | Linear Assignment via LAPX solver |
| **Scene Graph & Rules** | 2 – 4 ms | Main Pipeline Thread | Vectorized NumPy math, dot products, rays |
| **HUD & Annotation** | 3 – 5 ms | Main Pipeline Thread | In-place OpenCV drawing routines |
| **ANPR (EasyOCR)** | 250 – 550 ms | **Async Background Thread** | Bounded queue (8); drops oldest; skips locked plates |
| **Evidence Crop & MP4 Clip** | 180 – 450 ms | **Async Background Thread** | Bounded queue (32); rolling ring buffer (`deque`) |
| **Database I/O** | 5 – 15 ms | **Async Background Thread** | SQLite WAL mode; zero fsync stalls on main loop |
| **Telegram Alert Dispatch** | 400 – 900 ms | **Async Background Thread** | Bounded queue (100); rate-limited cooldown |

**Main-Loop Total: 35 – 50 ms per frame $\rightarrow$ Solid 20 – 28 FPS on CPU (60+ FPS on GPU).**

---

## 🔬 Technical Modules & Core Algorithms

### 1. Real-Time Object Detection & Tracking
* **Architecture (`core/detector.py`):** Wraps Ultralytics YOLO26 / YOLOv8. Automatically selects the optimal execution engine (`openvino` on Intel CPUs, `cuda` on NVIDIA GPUs, `tensorrt` on Jetson boards, or `pytorch` fallback).
* **Target Classes:** Filters COCO classes to relevant traffic entities:
  - Vehicles: `car`, `motorcycle`, `bus`, `truck`, `bicycle`
  - Pedestrians: `person`
  - Infrastructure: `traffic light`
* **Persistent Identity (`core/tracks.py`):** Integrates ByteTrack. Computes track history, spatial bounding boxes, velocity vectors, ground contact foot coordinates, and plate association. Includes IoU identity-stitching to maintain track continuity across brief occlusions.

### 2. Semantic Spatial Scene Graph
* **Architecture (`core/scene_graph.py`):** Transforms a raw list of bounding boxes into a semantic directed graph representing entity relationships:
  - `SceneNode`: Objects with spatial coordinates and attributes.
  - `SceneEdge`: Relationships such as `person ON motorcycle` or `person IN car`.
* **Spatial Association Gates:**
  1. Foot containment: Person's bottom bounding box coordinate must sit inside the vehicle's upper boundary.
  2. Normalized horizontal distance: Normalizes person-to-vehicle center offset by vehicle width, clamping between $[0, 1]$.
  3. Greedy 1-to-1 matching: Associates riders to vehicles by descending confidence, preventing a single person from being assigned to multiple motorcycles.

### 3. Calibrated Ground-Plane Homography
* **Mathematics (`core/geometry.py`):** Maps 2D camera coordinates $(u, v)$ to real-world ground coordinates $(X, Y)$ in meters via perspective transformation:
  $$\begin{bmatrix} X' \\ Y' \\ W' \end{bmatrix} = \mathbf{H} \begin{bmatrix} u \\ v \\ 1 \end{bmatrix}, \quad X = \frac{X'}{W'}, \quad Y = \frac{Y'}{W'}$$
* **Why This Matters:** Under camera perspective, a vehicle traversing 40 pixels near the bottom edge might move 0.4 meters, whereas 40 pixels near the horizon represents 3.5 meters. Homography ensures speed and distance calculations remain physically accurate.

### 4. Rule Engine & Deterministic Violation Logic
* **Architecture (`core/violations.py`):** Evaluates 6 deterministic traffic safety rules:

```
┌─────────────────┬───────────────────────────────┬────────────────────────────────────────────────────────┐
│ Violation Type  │ Fine (INR) & Severity         │ Trigger Condition & Physical Proof                     │
├─────────────────┼───────────────────────────────┼────────────────────────────────────────────────────────┤
│ OVERSPEEDING    │ ₹ 2,000  (CRITICAL)           │ Median ground speed > limit over >= 6 track frames     │
│ RED_LIGHT       │ ₹ 5,000  (CRITICAL)           │ Vehicle foot point crosses stop line while light=RED   │
│ WRONG_WAY       │ ₹ 5,000  (CRITICAL)           │ Displacement vector dot product with lane <= -0.55     │
│ TRIPLE_RIDING   │ ₹ 1,000  (HIGH)               │ Associated riders ON motorcycle >= 3                   │
│ NO_HELMET       │ ₹ 1,000  (HIGH)               │ Classifier scores head crop as NO_HELMET (or HSV test) │
│ ILLEGAL_PARKING │ ₹   500  (LOW)                │ Dwell time inside no-parking polygon >= 20 seconds     │
└─────────────────┴───────────────────────────────┴────────────────────────────────────────────────────────┘
```

* **Traffic Light Hue Masking:** Analyzes traffic signal bounding boxes using HSV color thresholding (Red: $[0, 110, 140]\cup[170, 110, 140]$, Yellow: $[18, 110, 150]$, Green: $[45, 90, 120]$). Avoids nighttime saturation bloom errors.
* **Stop-Line Crossing Geometry:** Evaluates line orientation segments:
  $$\text{side}(A, B, P) = (B_x - A_x)(P_y - A_y) - (B_y - A_y)(P_x - A_x)$$
  A violation triggers only when consecutive frame positions $(P_{t-1}, P_t)$ flip signs across the calibrated segment.

### 5. Indian-Standard ANPR Engine (AIS-015 / MoRTH)
* **Architecture (`core/ocr_worker.py`):** 1,285-line high-precision OCR pipeline built specifically for Indian vehicular plates:
  - **MoRTH AIS-015 Standard Compliance:** Enforces format `[State (2L)] [District (1-2D)] [Series (0-3L)] [Serial (4D)]` across all 36 Indian States and Union Territories (plus `BH` Bharat series).
  - **Two-Stage Detection:**
    - Stage 1 (Fast GPU): Runs YOLO plate detector on full frame (~3ms), crops plate, thresholds, and matches parent vehicle via `get_car()` bounding box containment.
    - Stage 2 (Async Fallback): Submits lower-bumper vehicle crops to background EasyOCR worker thread.
  - **Plate Background Color Handling:**
    - White BG / Black Text: Private Passenger Vehicles
    - Yellow BG / Black Text: Commercial Taxis & Buses
    - Green BG / White Text: Electric Vehicles (EV)
    - Black BG / Yellow Text: Rental / Self-Drive Vehicles
    - Blue BG / White Text: Diplomatic Corps
  - **HSRP Prefix Stripping:** Cleans embossed country identifiers (`IND`, `1ND`, `TND`).
  - **Alphanumeric Disambiguation Map:**
    - Digit positions: $\text{O, D, Q}\rightarrow 0$, $\text{I, L}\rightarrow 1$, $\text{Z}\rightarrow 2$, $\text{A}\rightarrow 4$, $\text{S}\rightarrow 5$, $\text{G}\rightarrow 6$, $\text{B}\rightarrow 8$.
    - Letter positions: $0\rightarrow \text{O}$, $1\rightarrow \text{I}$, $2\rightarrow \text{Z}$, $4\rightarrow \text{A}$, $5\rightarrow \text{S}$, $8\rightarrow \text{B}$.
  - **Two-Line Plate Handling:** Line-bins character boxes top-to-bottom and left-to-right to support motorcycle and commercial truck formats.

### 6. Multi-Camera Corridor Tracking with Branch Prediction
* **Architecture (`core/road_network.py` & `core/tracking_engine.py`):** Reconstructs vehicle movement across distributed city camera corridors:
  - **Road Network Graph (`NetworkX`):** Camera intersections represent nodes; connecting roads represent directed edges parameterized with real-world distance (meters), speed limits, and OpenStreetMap GPS polylines.
  - **Dead-Reckoning Simulation:** Estimates vehicle progress along road polylines using calibrated entry speed.
  - **Fork Branch Spawning:** When a vehicle crosses a fork junction (e.g. CAM-03 into CAM-08 and CAM-09), the system spawns multiple hypothesis instances with equal split probability ($50\% / 50\%$).
  - **Downstream Fuzzy Confirmation:** When the downstream camera detects the vehicle, it confirms the matching branch using Levenshtein distance ($\text{dist} \le 2$ to tolerate OCR character noise) and prunes unchosen ghost branches.
  - **Compass Heading Calculation:** Computes continuous vehicle bearing angles ($0^\circ - 360^\circ$) along polylines for map marker rotations.

### 7. Spatio-Temporal Route Anomaly & Cloned Plate Detection
* **Architecture (`core/anomaly.py`):** Detects duplicate / cloned license plates and impossible travel times:
  - Computes geodesic Haversine distance between camera coordinates:
    $$d = 2R \arcsin \left( \sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos\phi_1\cos\phi_2\sin^2\left(\frac{\Delta \lambda}{2}\right)} \right)$$
  - Calculates inter-camera passage speed:
    $$V_{\text{corridor}} = \frac{d}{\Delta t}$$
  - If a plate appears at two distinct cameras with an implied speed $> 160\text{ km/h}$, the engine flags a `PLATE_CLONE_OR_IMPOSSIBLE_SPEED` alert and dispatches an immediate critical notice.

### 8. Real-Time Telegram Mobile Alerting Engine
* **Architecture (`core/alerts.py`):** Non-blocking alerting worker dispatching structured Markdown messages and photo attachments to designated police control room channels.
* **Features:**
  - Severity badges (`🚨 CRITICAL`, `⚠️ HIGH`, `ℹ️ LOW`).
  - Google Maps hyperlink for checkpoint GPS coordinates.
  - Automated 5-second per-plate cooldown to prevent duplicate alerts.

### 9. Video & Image Evidence Writer
* **Architecture (`core/evidence.py`):** Maintains a rolling in-memory ring buffer (`collections.deque`, default: 75 frames $\approx 3$ seconds) on a background thread.
* **Outputs:**
  - Full-resolution overview JPEG crop centered on the violator with border margin.
  - Isolated clean license plate image crop.
  - Synchronized 4-second MP4 video clip (2 seconds pre-violation + 2 seconds post-violation) encoded via H.264.

### 10. High-Performance SQLite Asynchronous Storage
* **Architecture (`core/database.py`):** Manages SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`). All insertions run asynchronously over an internal queue (`maxsize=512`), ensuring database writes never stall the video feed.
* **Database Schema Overview:**
  - `violations`: Infraction records, fine amounts, rule confidence, review status, file paths.
  - `sightings`: ANPR passage history, camera ID, timestamp, speed.
  - `flow_stats`: Junction traffic density, vehicle counts, average speed, queue length.
  - `blacklist`: Stolen / flagged vehicles, severity level, alert reason.
  - `ocr_accuracy_log`: Raw OCR text vs regex-validated plates for tracking ANPR precision.
  - `cameras`: Registered camera nodes, latitude/longitude, operational state.

---

## 📂 Complete File-by-File & Codebase Directory Walkthrough

```
-TrafficSentinel-AI-main/
├── core/                                   # The AI & Algorithmic Core Package
│   ├── __init__.py                         # Package initialization
│   ├── alerts.py                           # Telegram mobile bot alerting worker (289 lines)
│   ├── annotator.py                        # Low-latency HUD & bounding box renderer (128 lines)
│   ├── anomaly.py                          # Spatio-temporal plate clone & speed anomaly detector (88 lines)
│   ├── config.py                           # Dataclasses & system tuning parameters (158 lines)
│   ├── database.py                         # Asynchronous SQLite storage engine with WAL mode (519 lines)
│   ├── detector.py                         # YOLO26/v8 detection wrapper & auto-backend picker (228 lines)
│   ├── engine.py                           # TrafficSentinel main pipeline orchestrator (594 lines)
│   ├── evidence.py                         # Rolling ring-buffer evidence crop & MP4 writer (156 lines)
│   ├── geometry.py                         # 3x3 Homography, line crossing, point-in-poly math (132 lines)
│   ├── helmet.py                           # Head crop CLAHE & helmet classification (176 lines)
│   ├── ocr_worker.py                       # Indian AIS-015 ANPR engine & character fixer (1,285 lines)
│   ├── road_network.py                     # NetworkX road graph, OSRM polylines, Haversine (199 lines)
│   ├── scene_graph.py                      # Spatial entity relationship scene graph (174 lines)
│   ├── tracking_engine.py                  # Dead-reckoning corridor tracker & fork predictor (568 lines)
│   ├── tracks.py                           # ByteTrack track lifecycle & velocity estimation (194 lines)
│   ├── video_source.py                     # Threaded frame grabber with automatic reconnect (161 lines)
│   └── violations.py                       # Deterministic violation rule evaluator (301 lines)
│
├── Dark-Themed Surveillance Dashboard/     # Dahua DSS-Style React 19 Frontend
│   ├── package.json                        # Node dependencies (React 19, Vite 8, Tailwind v4)
│   ├── tsconfig.json                       # TypeScript compiler configuration
│   ├── vite.config.ts                      # Vite build configuration with Tailwind plugin
│   ├── index.html                          # HTML5 shell for React app
│   └── src/
│       ├── main.tsx                        # React application mounting entrypoint
│       ├── App.tsx                         # 4-pane surveillance layout & tab controllers (370 lines)
│       ├── index.css                       # Obsidian dark palette & font styling
│       └── components/
│           ├── TopNav.tsx                  # Surveillance header, live UTC clock, tab navigation (285 lines)
│           ├── LeftSidebar.tsx             # Camera tree, electronic PTZ, rule toggles (426 lines)
│           ├── VideoViewport.tsx           # MJPEG stream, 1x1/2x2/3x3 grid, live HUD stats (704 lines)
│           └── RightSidebar.tsx            # Live ANPR card feed & WebSocket receiver (452 lines)
│
├── static/
│   └── index.html                          # Standalone single-page ops-center with Leaflet & Chart.js (2,835 lines)
│
├── data/
│   └── road_network.json                   # Park Street Corridor topology, camera nodes, polylines (743 lines)
│
├── models/
│   ├── .gitkeep                            # Git placeholder
│   └── license_plate_detector.pt           # Fine-tuned YOLO license plate detection model
│
├── scripts/
│   └── build_road_network.py               # Generates road topology via OSRM routing API (183 lines)
│
├── tests/                                  # Comprehensive Test Suite (31 Tests Passing)
│   ├── conftest.py                         # Pytest configuration & fixtures
│   ├── test_anpr_deduplication.py          # ANPR deduplication, HSRP prefix, character tests (133 lines)
│   ├── test_live_logs.py                   # Real-time event queue & plate update tests (117 lines)
│   ├── test_road_network.py                # Graph node, edge, and fork topology tests (56 lines)
│   ├── test_server_tracking_api.py         # FastAPI TestClient endpoint integration tests (74 lines)
│   ├── test_simulation_scenarios.py        # End-to-end multi-car fork & confirmation tests (86 lines)
│   └── test_tracking_engine.py             # Dead-reckoning, bearing, Levenshtein distance tests (131 lines)
│
├── app.py                                  # Streamlit prototyping dashboard with Folium & Plotly (457 lines)
├── server.py                               # FastAPI DSS backend with 25+ REST & WebSocket routes (1,858 lines)
├── calibrate.py                            # Interactive OpenCV camera calibration tool (181 lines)
├── run_headless.py                         # Benchmark CLI runner for measuring raw pipeline FPS (91 lines)
├── train_helmet.py                         # YOLOv8n-cls fine-tuning script for helmet detection (76 lines)
├── camera.json                             # Active camera spatial calibration & configuration
├── camera_template.json                    # Template calibration file for deploying new cameras
├── requirements.txt                        # Python dependencies
├── setup.bat / setup.sh                    # One-click environment installer & PyTorch CPU/GPU setup
├── run.bat / run.sh                        # Streamlit dashboard launcher
├── run_server.bat                          # FastAPI DSS backend launcher
└── trafficsentinel.db                      # SQLite production database (with WAL journal)
```

---

## 🛠️ Technology Stack Matrix

```
┌─────────────────────────┬────────────────────────────────────────────────────────────────────────┐
│ Domain                  │ Technology / Library & Version                                         │
├─────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Computer Vision & AI    │ Ultralytics YOLO26 / YOLOv8, OpenCV 4.9+, ByteTrack (lapx), EasyOCR    │
│ Deep Learning Runtimes  │ Intel OpenVINO 2024.3, PyTorch 2.3+ (CPU-optimized or CUDA), ONNX      │
│ Backend Server          │ FastAPI 0.111+, Uvicorn 0.29+, WebSockets, Pydantic, HTTPX             │
│ Graph & Geospatial      │ NetworkX 3.0+, Haversine geodesic math, OSRM Polyline Routing          │
│ Primary Desktop UI      │ React 19, TypeScript 5.7, Tailwind CSS v4, Vite 8, Lucide Icons        │
│ Standalone Web Center   │ Vanilla ES6+ HTML5/CSS3, Leaflet 1.9, Leaflet-Heat, Chart.js 4.4       │
│ Rapid Prototype UI      │ Streamlit 1.36+, Plotly 5.20+, Folium 0.16+, Pandas 2.2                │
│ Multimedia & Video      │ ImageIO, FFMPEG (H.264 MP4 encoding), MJPEG live stream protocol       │
│ Database & Persistence  │ SQLite 3 with Write-Ahead Logging (WAL) and indexed schemas            │
│ Testing & Verification  │ Pytest 8.0+, FastAPI TestClient, Unittest                              │
└─────────────────────────┴────────────────────────────────────────────────────────────────────────┘
```

---

## 🖥️ Tri-Interface Frontend Architecture

TrafficSentinel AI offers three distinct interfaces tailored for different operational roles:

### 1. Modern Dahua-Style DSS Ops-Center (React 19 + TypeScript)
Located in `Dark-Themed Surveillance Dashboard/`. Built for command-and-control surveillance centers:
* **Dark Obsidian Aesthetic:** `#0d1117` base, `#161c28` panels, `#00d2ff` neon cyan highlights.
* **Left Navigation:** Expandable camera tree (`CAM-01` through `CAM-04`), Electronic PTZ controls, violation rule toggles, video source selector (file upload / webcam / RTSP stream), and Telegram alert configuration.
* **Center Viewport:** Low-latency live MJPEG stream, 1x1 / 2x2 / 3x3 multi-channel layouts, live telemetry overlay (FPS, inference ms, active tracks, signal status).
* **Right Sidebar:** Live ANPR card feed updated in real time via WebSockets (`/ws/events`), showing plate crops, vehicle types, timestamps, and violation tags.
* **Integrated Sub-Views:**
  - `Review Queue`: Officer challan decision console with side-by-side evidence images and video playback.
  - `Analytics`: Financial revenue breakdown in INR (₹), violation distribution charts.
  - `ANPR Trace`: Single-vehicle corridor trajectory tracking.
  - `Calibration Status`: Hardware validation checklist.

### 2. Standalone Monitoring Center (`static/index.html`)
A zero-build, self-contained single-page dashboard served directly by the FastAPI backend on `http://localhost:8765`:
* Embedded **Leaflet.js interactive maps** with dynamic camera markers, vehicle dead-reckoning markers with heading rotation, and road polyline overlays.
* **Leaflet Heatmap:** Visualizes traffic congestion hotspots and violation zones across the city.
* **ANPR Lab:** Interactive benchmarking suite for testing custom YOLO models on saved frames.
* **Blacklist Manager:** Interface for adding, viewing, and importing flagged license plates.

### 3. Interactive Prototyping Dashboard (`app.py` via Streamlit)
Designed for rapid experimentation and model tuning:
* Slider controls for detector confidence, NMS IoU, and inference dimensions ($320\text{px} - 640\text{px}$).
* Interactive Plotly charts for fine distributions and hourly violation volumes.
* Embedded Folium maps showing camera coordinates.

### 4. Pure CLI Headless Benchmarking Engine (`run_headless.py`)
Decoupled from all browser rendering limits:
* Benchmarks raw pipeline performance directly from the command line.
* Reports exact latency breakdowns: decode, YOLO inference, ByteTrack, scene graph, and evidence encoding.

---

## 🔌 Backend REST API & WebSocket Specifications

The FastAPI backend in `server.py` exposes over 25 endpoints:

```
┌─────────┬──────────────────────────────┬─────────────────────────────────────────────────────────┐
│ Method  │ Endpoint                     │ Description                                             │
├─────────┼──────────────────────────────┼─────────────────────────────────────────────────────────┤
│ GET     │ /stream                      │ MJPEG video stream with rendered bounding boxes & HUD   │
│ WS      │ /ws/events                   │ Bidirectional WebSocket event bus (ANPR & violations)   │
│ GET     │ /api/stats                   │ Real-time pipeline telemetry (FPS, infer_ms, tracks)    │
│ POST    │ /api/pipeline/toggle         │ Pause or resume pipeline video processing               │
│ GET     │ /api/live-logs               │ Recent FIFO log entries (violations & ANPR detections)  │
│ GET     │ /api/events                  │ Historical combined event feed                          │
│ POST    │ /api/upload-video            │ Upload MP4/AVI video file for surveillance evaluation   │
│ POST    │ /api/source                  │ Switch input source (webcam index, file, RTSP URL)      │
│ GET     │ /api/violations              │ Query historical violations with filtering & pagination │
│ GET     │ /api/review                  │ List pending review items awaiting officer adjudication │
│ POST    │ /api/review/action           │ Issue challan or dismiss item as false positive         │
│ POST    │ /api/review/clear-all        │ Purge all violation logs and evidence files             │
│ GET     │ /api/analytics               │ Aggregate statistics, fine totals in INR, distributions │
│ GET     │ /api/anpr/trace              │ Search vehicle passage history across camera checkpoints│
│ GET     │ /api/calibration             │ Check calibration status of active camera               │
│ GET     │ /api/blacklist               │ Retrieve list of blacklisted vehicle plates             │
│ POST    │ /api/blacklist               │ Add new vehicle plate to police blacklist               │
│ DELETE  │ /api/blacklist/{plate}       │ Remove license plate from blacklist                     │
│ POST    │ /api/blacklist/import        │ Bulk import blacklist records via JSON                  │
│ GET     │ /api/analytics/ocr-accuracy  │ Performance stats: raw OCR vs validated format ratios   │
│ GET     │ /api/cameras                 │ Retrieve list of all registered corridor camera nodes   │
│ POST    │ /api/cameras                 │ Register new camera node with GPS coordinates           │
│ GET     │ /api/flow/heatmap            │ Spatial density points for Leaflet heatmap rendering    │
│ GET     │ /api/flow/congestion         │ Real-time congestion status index across cameras        │
│ GET     │ /api/tracking/graph          │ Corridor road network nodes and directed edges          │
│ GET     │ /api/tracking/live           │ Real-time vehicle positions with dead-reckoning coords  │
│ POST    │ /api/tracking/simulate-sighting│ Inject mock ANPR detection to test corridor tracking │
│ POST    │ /api/tracking/reset          │ Reset all active corridor tracking instances            │
│ POST    │ /api/settings                │ Update rule parameters, speed limits, and thresholds    │
│ POST    │ /api/alerts/test             │ Send test alert to configured Telegram bot/chat         │
│ GET     │ /evidence/{type}/{file}      │ Serve evidence JPEG crops, plate images, and MP4 clips  │
└─────────┴──────────────────────────────┴─────────────────────────────────────────────────────────┘
```

---

## 📐 Camera Calibration & Mathematical Grounding Guide

To ensure speed and distance measurements are legally defensible, each camera is calibrated using `calibrate.py`.

```bash
python calibrate.py --source traffic.mp4 --out camera.json
```

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                           Interactive Calibration Sequence                                │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Step 1: HOMOGRAPHY (4 Points)                                                             │
│ Click 4 points on the road surface forming a known rectangle (e.g. lane markings).        │
│ Standard Indian highway lane width: 3.5m; center dashed line: 3.0m long with 6.0m gap.     │
│ Enter real-world dimensions in meters. Computes 3x3 homography matrix H.                  │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Step 2: STOP LINE (2 Points)                                                              │
│ Click 2 points defining the stop line. Crossing this vector while light=RED = violation.  │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Step 3: LANE DIRECTION (2 Points)                                                         │
│ Click 2 points along legal traffic flow. Computes normalized unit vector [dx, dy].        │
│ Movement with dot product <= -0.55 triggers WRONG_WAY violation.                          │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Step 4: NO-PARKING ZONES (Polygons)                                                       │
│ Click vertices to define restricted parking zones; press 'n' to close polygon.            │
│ Stationary dwell time >= 20 seconds inside polygon triggers ILLEGAL_PARKING violation.    │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Installation, Setup & Quickstart Guide

### Prerequisites
* **Operating System:** Windows 10/11, Ubuntu 20.04/22.04 LTS, or macOS (Apple Silicon / Intel).
* **Python:** Version `3.10` to `3.12` installed and added to `PATH`.
* **Node.js (Optional, for React UI):** Node.js 18+ and pnpm / npm.

### Automated Setup (Recommended)

#### On Windows:
```cmd
REM 1. Clone the repository and navigate into it
cd -TrafficSentinel-AI-main

REM 2. Run the one-click setup script (creates .venv, installs PyTorch & deps)
setup.bat

REM 3. Launch the FastAPI DSS Backend Server (port 8765)
run_server.bat
```

#### On Linux / macOS:
```bash
# 1. Grant execution rights and run setup
chmod +x setup.sh run.sh
./setup.sh

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Start the server
python server.py
```

### Starting the User Interfaces

#### Interface Option A: Standalone Surveillance Dashboard (Zero Node.js Required)
Once `server.py` is running, open any web browser and go to:
```
http://localhost:8765
```
This loads the complete surveillance center with MJPEG stream, WebSocket feeds, Leaflet maps, and ANPR lab.

#### Interface Option B: Dahua DSS React Ops-Center
For the modern desktop operations center:
```bash
cd "Dark-Themed Surveillance Dashboard"
pnpm install
pnpm dev
```
Open `http://localhost:5173` (or port indicated by Vite).

#### Interface Option C: Streamlit Dashboard
```bash
run.bat
# Or manually:
.venv\Scripts\streamlit.exe run app.py
```

#### Interface Option D: Headless Performance Benchmark
```bash
python run_headless.py --source traffic.mp4 --benchmark 300 --no-display
```

---

## 🧪 Testing, Verification & Quality Assurance

The codebase includes an automated test suite covering unit logic, integration routes, and multi-camera simulation:

```bash
# Run the complete test suite
.venv\Scripts\python.exe -m pytest tests/
```

### Test Suite Summary:
* `tests/test_anpr_deduplication.py` (11 Tests):
  - Database sighting deduplication caching.
  - Plate-to-vehicle containment association (`get_car()`).
  - HSRP `IND` prefix stripping.
  - Alphanumeric disambiguation without series corruption.
* `tests/test_live_logs.py` (4 Tests):
  - Real-time live log FIFO queuing.
  - Retroactive plate updates on existing violation items.
  - ANPR detection logging.
* `tests/test_road_network.py` (4 Tests):
  - Road network JSON loading and node verification.
  - Cumulative polyline distance interpolation.
  - Fork junction detection (`CAM-03` and `CAM-07`).
* `tests/test_server_tracking_api.py` (3 Tests):
  - `/api/tracking/graph` endpoint serialization.
  - Mock sighting injection and multi-branch spawning.
  - Downstream fuzzy confirmation and tracking reset.
* `tests/test_simulation_scenarios.py` (2 Tests):
  - Concurrent vehicle simulation through corridors.
  - Fork branch spawning, downstream fuzzy matching, and vanished track purging.
* `tests/test_tracking_engine.py` (7 Tests):
  - Levenshtein edit distance metric.
  - Dead-reckoning polyline interpolation and compass heading computation.
  - Track lifecycle transitions (`predicted` $\rightarrow$ `confirmed` $\rightarrow$ `vanished`).

**Result: 31 passed in 39.13 seconds (100% pass rate).**

---

## ⚖️ Legal & Ethical Compliance Note

TrafficSentinel AI is designed in compliance with modern digital governance principles:
1. **Explainable AI (XAI):** Uses transparent, rule-based decision trees for legal violations instead of end-to-end black-box predictions.
2. **Data Privacy:** Stores evidence media locally in secured directories; does not transmit facial biometrics to third-party cloud servers.
3. **Audit Trail:** Preserves all raw OCR candidate strings, confidence scores, and operator modifications to ensure evidentiary integrity under legal review.

---

*TrafficSentinel AI — Built for transparent, auditable, and safer smart city transportation networks.*
