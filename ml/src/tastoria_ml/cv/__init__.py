"""Image processing for Tastoria: vision class table, public detection data, preprocessing, models.

Pure-numpy parts (``classes``, ``preprocess``, ``phash``, ``yolo_format``) run in the project env and
are unit tested. Training and download scripts (``openimages``, ``mendeley_bd``, ``build_yolo``,
``train_detector``, ``freshness``) need the separate training env described in
``docs/reports/xu-ly-anh/ket-qua-so-bo.md`` (ultralytics, torch, Pillow, scikit-learn, mlflow).
"""
