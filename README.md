# Pineapple E-Nose Model Training

This folder contains the model training workflow for our pineapple ripeness detection project based on an electronic nose system.

The training pipeline starts from reconstructed raw sensor features, combines manual labels and reviewed labels, performs feature engineering and model evaluation, and finally exports deployment-ready files for Raspberry Pi.

---

## Overview

This directory is used for the **model training and deployment preparation stage** of our project.

Its main purposes are:

- rebuild per-day feature tables from raw Excel files
- merge pineapple data with daily air reference data
- load and repair labeling information
- perform reviewed label integration
- generate engineered features
- evaluate multiple training strategies
- compare CatBoost teacher models and student deploy models
- export final deployment bundles for Raspberry Pi

The main notebook currently used in this folder is:

- `labeling_perfect_final.ipynb`

This notebook is the latest integrated version of our training workflow.

---

## Current Folder Structure

```text
enose_model_training/
└── orkspace/
    ├── catboost_info/
    ├── data/
    ├── deploy_rpi_catboost/
    ├── deploy_rpi_et_10s/
    ├── deploy_rpi_et_10s_noday/
    ├── deploy_rpi_et_30s_noday/
    ├── deploy_rpi_et_30s_noday_s3_sensitive/
    ├── deploy_rpi_student/
    ├── deploy_rpi_student_short/
    ├── models/
    ├── reports/
    ├── cutpoints.json
    ├── data_label_audit_report.xlsx
    ├── feature_columns.json
    ├── labeling_perfect_final.ipynb
    ├── labeling.xlsx
    ├── model_final.pkl
    └── stage_timeline.png
```

> Note: `orkspace` is the current folder name in this project structure.

---

## Main Notebook

### `labeling_perfect_final.ipynb`

This is the main notebook for the current version of the pineapple e-nose training pipeline.

It includes the following major tasks:

### 1. Rebuild Features from Raw Excel Files
The notebook reconstructs per-day features from all raw Excel files, including:

- pineapple sample files
- individual air files
- shared air files

This step replaces older fragmented preprocessing steps and creates a cleaner feature table for later training.

### 2. Cross Features and Air-Contrast Features
Additional engineered features are created, including:

- cross-sensor ratio features
- fruit-air contrast features
- daily air-based comparison features

These features help the model better capture gas pattern differences between pineapple samples and background air.

### 3. Label Loading and Repair
The notebook loads `labeling.xlsx` and performs label repair based on audit results.

Key points:

- keeps the original 4-stage setting: `0 / 1 / 2 / 3`
- preserves stage 3 instead of merging it away
- applies reviewed label corrections
- checks stage 3 merge coverage
- generates audit and review support tables

### 4. Hybrid Label Propagation and Pseudo Labeling
For partially labeled data, the notebook uses a hybrid strategy that combines:

- manual labels
- anchor-based propagation
- ripening proxy features
- smell similarity
- monotonic stage constraints

This allows the training data to be expanded while still keeping the stage progression reasonable.

### 5. Feature Selection
The notebook performs feature selection using methods such as:

- mutual information
- monotonic relationship with stage
- proxy-based importance
- stable feature pool comparison

This helps identify the most useful deployable features.

### 6. Model Evaluation
Several model strategies are evaluated, including:

- reviewed-label training tables
- hybrid label versions
- CatBoost ordinal models
- stable feature pool experiments
- error hotspot analysis
- per-pineapple performance analysis

The notebook focuses on **real generalization performance**, not only training accuracy.

### 7. Deployment Candidate Search
The notebook also explores deployment-friendly models for Raspberry Pi, including:

- CatBoost-based deploy packs
- student models
- ExtraTrees deploy candidates
- short-window inference tests
- no-day-feature deploy versions

### 8. Final Raspberry Pi Export
The final cells export deployment-ready model bundles for Raspberry Pi usage.

---

## Training Workflow

The overall workflow of this folder is:

1. collect raw gas sensing data from Arduino Mega
2. organize pineapple and air Excel files
3. rebuild per-day features
4. generate engineered features
5. load and review labels
6. repair or refine stage labels
7. train and evaluate models
8. compare deployable candidates
9. export the final deploy pack for Raspberry Pi

---

## Important Files

### `labeling_perfect_final.ipynb`
The latest full training notebook.

### `labeling.xlsx`
Original manual labeling file used as the main label source.

### `data_label_audit_report.xlsx`
Audit report for checking label consistency and merge conditions.

### `feature_columns.json`
Stores the final deploy feature names used by the exported model.

### `model_final.pkl`
Saved trained model file for one of the final deployable versions.

### `cutpoints.json`
Used when the model follows an ordinal-style prediction design.

### `stage_timeline.png`
A visual summary of stage progression or stage-related analysis.

---

## Folder Descriptions

### `data/`
Stores training-related data files, intermediate processed data, and rebuilt feature tables.

### `models/`
Stores trained model files, intermediate models, and comparison outputs.

### `reports/`
Stores training summaries, evaluation outputs, audit results, and related exported reports.

### `catboost_info/`
Automatically generated CatBoost training logs and temporary outputs.

This folder is usually not necessary for GitHub upload and can be ignored if needed.

### `deploy_rpi_catboost/`
Deployment bundle for Raspberry Pi using the CatBoost ordinal-style model.

### `deploy_rpi_student/`
Deployment bundle for Raspberry Pi using a student model distilled or simplified from the teacher pipeline.

### `deploy_rpi_student_short/`
A shorter or lighter deployment version for Raspberry Pi.

### `deploy_rpi_et_10s/`
ExtraTrees deployment pack using a 10-second inference window.

### `deploy_rpi_et_10s_noday/`
ExtraTrees deployment pack using a 10-second window without day-based features.

### `deploy_rpi_et_30s_noday/`
ExtraTrees deployment pack using a 30-second window without day-based features.

This is one of the most important deploy candidates because it is more practical for on-device prediction.

### `deploy_rpi_et_30s_noday_s3_sensitive/`
A modified 30-second ExtraTrees deployment pack with more sensitive stage-3-related decision behavior.

This version is useful when the system wants to be more cautious about overripe tendency.

---

## Raspberry Pi Deployment Files

According to the current training notebook, the final deployment pack for Raspberry Pi should include the files required by the selected deploy version.

### Common Required Files
The final Raspberry Pi package usually includes:

- trained model file(s)
- `feature_columns.json`
- optional `scaler.pkl`
- optional `cutpoints.json`
- optional `deploy_meta.json`

The exact set depends on which deployment version is used.

### Option 1: CatBoost Ordinal Deploy Pack
If you use the CatBoost ordinal deployment version, the Raspberry Pi package should typically include:

- `cb_ge1.cbm`
- `cb_ge2.cbm`
- `cb_ge3.cbm`
- `scaler.pkl`
- `feature_columns.json`
- `deploy_meta.json`

These files are usually stored inside:

- `deploy_rpi_catboost/`

This version corresponds to the teacher-style ordinal deployment workflow.

### Option 2: ExtraTrees 30s No-Day Deploy Pack
If you use the final lightweight Raspberry Pi deployment version, the package should typically include:

- `model_final.pkl` or equivalent ET model file
- `feature_columns.json`
- `deploy_meta.json` if generated

These files are usually stored inside:

- `deploy_rpi_et_30s_noday/`

If you use the more sensitive version, then use:

- `deploy_rpi_et_30s_noday_s3_sensitive/`

This version is more practical for Raspberry Pi because:

- it is lighter than CatBoost
- it avoids day-related features
- it supports short-window prediction
- it is suitable for real device deployment

---

## Current Recommended Deployment Direction

Based on the later cells of the notebook, the current deployment direction is:

- use a Raspberry Pi friendly model
- prefer a short inference window
- avoid unnecessary day-based features
- keep feature columns fixed for stable inference
- export a complete deploy folder instead of only one model file

For this reason, the following folders are especially important:

- `deploy_rpi_catboost/`
- `deploy_rpi_et_30s_noday/`
- `deploy_rpi_et_30s_noday_s3_sensitive/`

---

## Notes

- This folder is for **model training, evaluation, and deploy-pack export**
- It is not the Arduino data collection folder
- It is not the final Flask or Raspberry Pi runtime folder
- `catboost_info/` is a training log folder and usually does not need to be committed
- if Git reports path-length issues, shorten folder names or ignore temporary training folders

---

## Project Context

This folder is part of our graduation project:

**An Electronic Nose Based Non-Destructive Pineapple Ripeness Detection System**

The trained models from this workflow are later integrated into the Raspberry Pi inference side and connected to the overall application system.
