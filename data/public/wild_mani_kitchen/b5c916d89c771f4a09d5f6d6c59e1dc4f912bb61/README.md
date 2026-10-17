---
license: apache-2.0
task_categories:
- robotics
tags:
- lerobot
- robotics
- mixed-reality
- bimanual
- kitchen
- manipulation
- imitation-learning
- demonstration
configs:
- config_name: default
  data_files:
  - split: train
    path: data/chunk_*.parquet
pretty_name: 'WILD-Mani: Kitchen Edition'
---

# WILD-Mani: A Real-World Bimanual Manipulation Dataset – Kitchen Edition

The first installment of the WILD-Mani series.
* High-fidelity bimanual demonstrations collected in real-world kitchen environments using Mixed Reality (MR).
* Designed to support Sim2Real transfer for bimanual manipulation tasks.
* Current Domain: Kitchen

## OOJU dataset series

| Dataset | Robot | Episodes | Robot actions | Format |
| --- | --- | ---: | --- | --- |
| **wild-mani-kitchen** (this card) | retarget targets: Unitree G1, UR5e | 102 | no | LeRobot v3.0 parquet |
| [ooju-galaxea-pick-cube](https://huggingface.co/datasets/OOJU/ooju-galaxea-pick-cube) | Galaxea R1 Pro | 177 | yes, 80,014 samples | raw JSON + TAR |
| [unitree-g1-pick-place-cup](https://huggingface.co/datasets/OOJU/unitree-g1-pick-place-cup) | Unitree G1 | 47 | yes | LeRobot v2.1 parquet + policy baselines |

Series overview with hand-to-robot retargeting accuracy measurements: https://ooju.world/datasets.html

#### Update: 08-2026

This dataset was captured with OOJU, a platform for collecting robot training data with Meta Quest 3. The same pipeline (MR capture, raw data capture and automated validation, Unitree G1 or UR5e kinematic retargeting) is available for your own tasks and environments. Access is released in cohorts.

🚀 **[Collect & validate your own data](https://ooju-app.world/request?utm_source=huggingface&utm_medium=dataset_card&utm_campaign=wild-mani-kitchen&utm_content=update)**

#### Update: 02-21-2026

We are currently scaling the WILD-Mani series to 1,000+ bimanual episodes with full Unitree G1 kinematic validation. Access to the **expanded library** and our **collection/automated-validation pipeline** is being released in cohorts.

## Dataset Description

This dataset contains human demonstrations of kitchen manipulation tasks captured using a Mixed Reality headset in **real-world kitchen environments**. The data tracks both hands simultaneously with 6-DOF pose tracking, enabling bimanual robot imitation learning research.

### Key Features

- **Real-world environments**: Demonstrations captured in actual kitchens (not simulation)
- **Mixed Reality capture**: High-fidelity hand tracking in physical spaces
- **Bimanual manipulation**: Both hands tracked simultaneously
- **Camera view**: Single camera (center eye) per demonstration
- **Diverse tasks**: Multiple kitchen manipulation tasks with varying complexity


## Dataset Statistics

| Property | Value |
|----------|-------|
| **Episodes** | 102 |
| **Total Frames** | 79,244 |
| **FPS** | 30 |
| **Cameras** | 1 |
| **Environment** | Real kitchen with lighting variations |


## Task Categories

| Category | Task | Objects | Actions | Demos |
|----------|------|---------|---------|-------|
| Meal Prep | Get item from fridge | Bottle, container | Open, pick, close, place | 25 |
| Dish Organizing | Place cups on shelf | Cups (2-3) | Pick, place | 26 |
| Dish Organizing | Put utensils in drawer | Fork, spoon, knife | Pick, open, place, close | 26 |
| Meal Prep | Set table (plate + utensil) | Plate, fork, knife | Pick, place | 25 |


## Start/End Labeling (Temporal Bounds)

Each episode has **start and end labels** so that the stored trajectory contains only the task-relevant segment. Frames before the task start (e.g. approach to the scene or button press) and after the task end are excluded. **Users can assume that the data does not include unnecessary motion at the beginning or end** of each demonstration; each episode is trimmed to the intended task interval.


## Action Labels (`observation.action_label`)

Per-frame labels are provided as `action::subaction` strings. The vocabulary **varies by task**. Below is the label set for each task.
- Hierarchical Semantic Labeling (VLA-Ready)
- Language-Conditioned Policy training and Chain-of-Thought reasoning for bimanual manipulation.


### Get item from fridge (25 episodes)

| Action | Subactions |
|--------|------------|
| **open** | approach → grasp → pull → release |
| **pick** | reach → grasp → extract |
| **close** | approach → push → retract |
| **place** | transport → release |

*Labels:* `open::approach`, `open::grasp`, `open::pull`, `open::release`, `pick::reach`, `pick::grasp`, `pick::extract`, `close::approach`, `close::push`, `close::retract`, `place::transport`, `place::release`.

### Place cups on shelf (26 episodes)

| Action | Subactions |
|--------|------------|
| **pick** | approach → align → grasp → lift |
| **place** | release → retract |

*Labels:* `pick::approach`, `pick::align`, `pick::grasp`, `pick::lift`, `place::release`, `place::retract`.

### Put utensils in drawer (26 episodes)

| Action | Subactions |
|--------|------------|
| **open** | approach → grasp → pull → release |
| **pick** | approach → grasp → lift |
| **place** | transport → release |
| **close** | approach → push → retract |

*Labels:* `open::approach`, `open::grasp`, `open::pull`, `open::release`, `pick::approach`, `pick::grasp`, `pick::lift`, `place::transport`, `place::release`, `close::approach`, `close::push`, `close::retract`.

### Set table (plate + utensil) (25 episodes)

| Action | Subactions |
|--------|------------|
| **pick** | approach → align → grasp → lift |
| **place** | transport → adjust → lower → release |

*Labels:* `pick::approach`, `pick::align`, `pick::grasp`, `pick::lift`, `place::transport`, `place::adjust`, `place::lower`, `place::release`.

---

## Diversity Dimensions

| Dimension | Coverage | Details |
|-----------|----------|---------|
| **Actions** | 4+ types | Pick, place, open, close |
| **Objects** | 15+ objects | Kitchen items varying in size, shape, material |
| **Environment** | 1 kitchen | Natural light, artificial light, dim lighting |
| **Surfaces** | 3 surfaces | Counter, dining table, shelf |
| **Task Complexity** | Single + Multi-step | Pick-place (single) → Fridge sequence (multi-step) |
| **Clutter** | Natural | Objects on counter, objects in fridge |


## Data Format

This dataset follows the **LeRobot v3.0** format.

### Action Space (14D)

The action space represents delta poses for both hands:

| Dimensions | Description |
|------------|-------------|
| 0-2 | Left hand position delta (x, y, z) |
| 3-6 | Left hand rotation delta (quaternion x, y, z, w) |
| 7-9 | Right hand position delta (x, y, z) |
| 10-13 | Right hand rotation delta (quaternion x, y, z, w) |

### Observation Space

| Key | Shape | Description |
|-----|-------|-------------|
| `state` | (14,) | Combined left/right wrist poses |
| `left_state` | (7,) | Left wrist pose (position + quaternion) |
| `right_state` | (7,) | Right wrist pose (position + quaternion) |
| `right_joint_poses` | (78,) | Right hand full skeleton (26 joints × 3D position) |
| `left_joint_poses` | (78,) | Left hand full skeleton (26 joints × 3D position) |
| `observation.images.center_eye` | (H, W, 3) | Center eye camera view |
| `observation.action_label` | string | Per-frame action label (e.g. pick::grasp, place::release) |

### Joint Order (26 joints per hand)

palm, wrist, thumb_metacarpal, thumb_proximal, thumb_distal, thumb_tip, index_metacarpal, index_proximal, index_intermediate, index_distal, index_tip, middle_metacarpal, middle_proximal, middle_intermediate, middle_distal, middle_tip, ring_metacarpal, ring_proximal, ring_intermediate, ring_distal, ring_tip, little_metacarpal, little_proximal, little_intermediate, little_distal, little_tip


## Recording Setup

- **Headset**: Meta Quest 3 (Mixed Reality)
- **Environment**: Real-world kitchen
- **Tracking**: Full skeletal hand tracking (26 joints per hand) via Quest 3 hand tracking
- **Cameras**: 1 camera (center eye view)
- **Software**: Unity-based recording system


## File Structure

```
.
├── data/
│   ├── chunk_0000.parquet
│   └── chunk_0001.parquet
├── meta/
│   ├── info.json
│   ├── stats.json
│   └── episode_index.parquet
├── videos/
│   └── observation.images.center_eye/
└── README.md
```

## Capture & validate your own dataset

Every episode here was recorded with OOJU: MR hand tracking on a Quest 3, per-frame action labels, temporal trimming, and automated validation against a target embodiment. If your tasks, objects, or environment are not covered by this kitchen set, you can collect them yourself with the same pipeline instead of waiting for someone to publish them.

🚀 **[Request access](https://ooju-app.world/request?utm_source=huggingface&utm_medium=dataset_card&utm_campaign=wild-mani-kitchen&utm_content=footer)**


## License

This dataset is released under the Apache 2.0 License.


## Citation

If you use this dataset in your research, please cite:

```bibtex
@misc{wild_mani_kitchen,
  title={WILD-Mani: A Real-World Bimanual Manipulation Dataset -- Kitchen Edition},
  author={OOJU},
  year={2026},
  publisher={Hugging Face},
  howpublished={\url{https://huggingface.co/datasets/OOJU/wild-mani-kitchen}}
}
```


## Acknowledgments

Dataset collected using Mixed Reality hand tracking in real-world kitchen environments. Recording system built with Unity and Meta Quest.
