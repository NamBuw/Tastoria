# Tastoria: Image Processing desk research (checked 2026-10-17)

**How this was checked.** I only read web pages and metadata. Nothing was downloaded or installed. Class lists and Kaggle/Mendeley/HF metadata were streamed to stdout, and WebFetch auto-saved one 1.5 MB paper PDF in tool-results. Roboflow Universe blocks direct fetches with Cloudflare, so I read some Universe pages through the r.jina.ai reader. Partway through, the shared WebSearch budget ran out (200/turn), and the notice also ruled out readers and curl-based search workarounds. After that I only fetched known URLs directly. Anything I did not open is marked **UNVERIFIED**. The user can send a follow-up to finish those items.

## 0. Key findings
- **The design doc is wrong that "Gemini không trả khung".** The Gemini API returns `box_2d` = `[ymin, xmin, ymax, xmax]` normalized to 0–1000, and segmentation masks too ([docs](https://ai.google.dev/gemini-api/docs/image-understanding)). The baseline can therefore be compared at box level and count level, not only at list level.
- **The doc's YOLOv8n figures match the docs but are out of date.** Docs give 3.2M params, 37.3 mAP, 80.4 ms CPU ONNX. YOLO26n (released Jan 2026) has 2.4M params, 40.9 mAP and 38.9 ms CPU ONNX. It is still AGPL-3.0 ([YOLOv8](https://docs.ultralytics.com/models/yolov8/), [YOLO26](https://docs.ultralytics.com/models/yolo26/)).
- **No usable public Vietnamese raw-ingredient detection set exists.** The only one with Vietnamese labels has 334 images and 5 kinds of greens. Rau muống, cải ngọt, su su, mướp, giá đỗ and ba chỉ must come mostly from the team's own photos.
- **AgriFreshNET is verified:** CC BY 4.0, 14,500 images, 24 classes, Fresh/Semi-Fresh/Rotten. Its produce list is not published. For leafy greens the best match is the **Local Spinach Leaf Dataset**, which has water spinach (rau muống) fresh/non-fresh.
- **Preprocessing evidence:** in an 18-method × 7-detector study, enhancement generally *lowered* detector AP and raw images scored best. Wrong white balance does hurt CNNs. So gray-world + CLAHE will likely matter more for the HSV/LBP classifier than for YOLO.

## 1. Detection datasets

### 1.1 Large taxonomies
All three are too big for the server and must be handled on Colab/Kaggle.

| Dataset | Size | License | Classes present (from the VN list) | Missing |
|---|---|---|---|---|
| Open Images V7 boxable ([facts](https://storage.googleapis.com/openimages/web/factsfigures_v7.html), [class CSV](https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv)) | 600 classes; 14.6M train boxes, about 90% drawn by hand | Annotations CC BY 4.0; images CC BY 2.0, with a per-image caveat | Tomato, Egg, Cabbage, Carrot, Potato, Cucumber, Zucchini, Pumpkin, **Winter melon**, Squash, Bell pepper, Radish, Mushroom, Lemon, Fish, Shrimp, Crab, Squid; "Chicken" is the animal | onion, garlic, ginger, lime, lettuce, spinach, corn (only Popcorn), tofu, pork, beef, eggplant, chili, scallion |
| LVIS v1 ([categories](https://github.com/facebookresearch/detectron2/blob/main/detectron2/data/datasets/lvis_v1_categories.py), [Ultralytics](https://docs.ultralytics.com/datasets/detect/lvis/)) | 1,203 classes; about 160k COCO images; about 2M instances; 20.7 GB | CC BY 4.0 per the Purdue RCAC mirror, **UNVERIFIED** (official page did not render) | tofu (bean_curd), beef, garlic, ginger, green_onion, onion, lettuce, lime, lemon, chili, corn, eggplant, fish_(food), prawn/shrimp, egg, tomato, potato, carrot, cucumber, mushroom, pumpkin, radish, zucchini | **cabbage**, spinach, pork, chicken meat, bok choy, bean sprouts, chayote, luffa |
| Objects365 ([Ultralytics](https://docs.ultralytics.com/datasets/detect/objects365/), [YAML](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/Objects365.yaml)) | 365 classes; 1.82M images; about 30M boxes; about 712 GB | **Conflicting:** CC BY 4.0 per Ultralytics, "Non-Commercial" per a hyper.ai snippet. **UNVERIFIED** | Green Vegetables (generic), Green Onion, Garlic, Onion, Lettuce, Cabbage, Egg, Tomato, Potato, Carrot, Cucumber, Pepper, Eggplant, Mushroom, Corn, Pumpkin, Radish, Lemon, Okra, Shrimp, Crab, Other Fish, Steak | ginger, tofu, pork, lime, spinach, winter melon, chili |

### 1.2 Ingredient and fridge sets
Opened unless marked otherwise.

| Dataset | Images / classes | Most relevant VN classes | Format · License · Size | Domain |
|---|---|---|---|---|
| [aicook](https://universe.roboflow.com/aicook/aicook-lcv4d) ([blog](https://roboflow.com/blog/smart-fridge)) | 516 originals (3,050 augmented) / 30 | eggs, beef, chicken(_breast), shrimp, onion, lime, spinach, corn, mushrooms | Roboflow export · **MIT** · small | One real fridge, fixed camera |
| FridgeAnalysisV2 (mirror: [kaggle rkuo2000/fridge](https://www.kaggle.com/datasets/rkuo2000/fridge)) | 2,214, already 3× augmented / 87 (duplicates such as apple/apples) | ginger, lime, lettuce, spinach, spring onion, shallot, shrimp, beef, chili | YOLOv7 · CC BY 4.0 per its README (Kaggle mirror says MIT) · 102 MB | Mixed |
| [Viet Hoang Food "Food Ingredient Detection"](https://universe.roboflow.com/viet-hoang-food/food-ingredient-detection-mnc5n) | 1,182 / 80 | **pork belly, pork rib, bean sprout, bok choy**, spring onion, chilli, garlic, ginger, egg, fish, shrimp, cabbage | Roboflow · CC BY 4.0 · n/a | Not described |
| [Robo1 "INGREDIENTS"](https://universe.roboflow.com/robo1-s-workspace/ingredients-b5dkh) | 17,279 (the page also says 41,363) / 110 | **bok_choy, napa_cabbage, chayote, mung_bean_sprout**, bitter_melon, gourd, pork, quail_egg, lime, calamansi | Roboflow · CC BY 4.0 · n/a | Not described; Filipino-flavoured class names |
| [SmartPantry](https://universe.roboflow.com/smartpantry/ingredients-yot0w) | 6,295 / 61 | **tofu, pork**, green_onion, chili, okra, cabbage | CC BY 4.0; no published version | Not described |
| [Jahan et al. 2025, Bangladesh vegetables](https://data.mendeley.com/datasets/gnc4s3z2mf/3) ([paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12686877/)) | 3,534 / 22; about 90k boxes (my sum of the per-class table) | cabbage, green chilli, spring onion, lemon, pumpkin, bitter/bottle/snake gourd, coriander, eggplant | Pascal VOC · CC BY 4.0 (Kaggle mirror says CC BY-SA) · about 0.25 GB | Roadside vendor stalls, one phone |
| [Nhận Diện Rau](https://universe.roboflow.com/khai-pha-du-lieu/nhan-dien-rau-p2y8s) | 334 (v6: 854) / 5 | **rau_muong, rau_cai_bap, rau_mung_toi, rau_xa_lach, rau_ngai_cuu** | CC BY 4.0 | The only Vietnamese-labeled detection set I found |
| [water-spinach-disease](https://universe.roboflow.com/fishdetect-q6amf/water-spinach-disease-7a5pr) | 1,415 / 3 | Water Spinach Fresh / NonFresh boxes | CC BY 4.0 | Not described |
| [Phcs vegetables](https://universe.roboflow.com/phcs-workspace-kultf/vegetables-ckjsc) | 798 / 6 | bok choy, tofu, **winter_melon**, shrimp | Instance segmentation · CC BY 4.0 | Not described |
| Small Kaggle sets | [slirq123](https://www.kaggle.com/datasets/slirq123/common-vegetable-dataset-for-object-detection): eggs, garlic, potatoes, tomatoes, lemons; VOC; CC BY-SA 4.0; 39 MB. [Refrigerator Contents](https://www.kaggle.com/datasets/surendraallam/refrigerator-contents): 7 classes incl. spinach, eggs; "© Original Authors". [denuwan](https://www.kaggle.com/datasets/denuwanwijesinghe/vegetable-object-detection): 4 classes; MIT | | | |

- **UNVERIFIED (seen only in search or listing snippets):** Hien_Fridge (860 images), FridgeItems_2 (863; fish, shrimp, squid, chili), vegetablesmeatingredients/ingredient-detection, an Indonesian "Vegetables" set with kangkung (vegetables-gdugj, 1.21k), cs131/fridge (2.73k).
- **Not relevant:**
  - [FoodSeg103/154](https://xiongweiwu.github.io/foodseg103.html): 9,490 food images with pixel masks over 154 ingredient classes. These are dish photos, with no boxes.
  - [MVTec D2S](https://www.mvtec.com/company/research/datasets/mvtec-d2s): 21k images of 60 grocery/product classes, **CC BY-NC-SA 4.0**.
- **Vietnamese datasets cover dishes only:** [VinaFood21](https://arxiv.org/abs/2108.02929) (13,950 images / 21 dishes), [30VNFoods](https://github.com/HuynhXuanLam-IT44/30VNFoods) (25,136 / 30), [ViFoodVQA](https://www.kaggle.com/datasets/phantrihieu/vnfood-combined-dataset) (CC BY-NC-SA, 6.9 GB).

### 1.3 Coverage gaps
- **Covered by large taxonomies and several sets:** cà chua, khoai tây, cà rốt, dưa chuột, nấm, bí đỏ, trứng, tôm, cá.
- **Only in LVIS/O365 or small community sets:** hành tây, tỏi, gừng, hành lá, xà lách, ngô, ớt, chanh (lime appears only in LVIS, aicook and Robo1), bắp cải (absent from LVIS).
- **Only in community sets, so must be self-collected:**
  - thịt lợn/ba chỉ (Viet Hoang, SmartPantry, Robo1)
  - đậu phụ (LVIS, SmartPantry, Phcs)
  - cải ngọt/bok choy (Robo1, Viet Hoang)
  - giá đỗ (Robo1, Viet Hoang)
  - su su (Robo1 only)
  - bí đao (OI V7, Phcs)
  - rau muống (Nhận Diện Rau, water-spinach sets)
  - **mướp: none**
- **gà:** the large sets only have the live animal; aicook and Viet Hoang have chicken meat.

## 2. Freshness and spoilage datasets

| Dataset | Images | Produce | Labels | Leafy greens? | License · Size |
|---|---|---|---|---|---|
| [AgriFreshNET](https://data.mendeley.com/datasets/42m5tb7yv9/1) (Risdin et al., East West Univ., published 30 Jul 2026) | 14,500 | 24 fruits and vegetables; **list not published (UNVERIFIED)** | Fresh / Semi-Fresh / Rotten plus shelf-life ranges (1–4 … 24–35 days); markets, supermarkets, households, farms | Unknown | **CC BY 4.0** · Processed Data.zip 348 MB (via Mendeley API) |
| [Local Spinach Leaf v3](https://data.mendeley.com/datasets/skf6w2s2h2/3) (Hasan et al., 2024) | 3,999 originals + 2,495 augmented | red, **water**, Malabar spinach | fresh / non-fresh, defined by experts (no storage days) | **Yes (rau muống)** | CC BY 4.0 · 2 × 300 MB |
| [Abeer et al. 2023](https://research.daffodilvarsity.edu.bd/scopus-article/3568), IFIP AICT pp. 50–66, doi:10.1007/978-3-031-38296-3_5 (checked on Crossref) | About 6,000 | eggplant, okra, cauliflower | fresh / aged / rotten, by appearance and capture day | No | Public availability **UNVERIFIED** |
| [Koyama et al. 2021, PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0248769) | 1,045 | Spinach photographed daily for 12 days at 10 °C | 4-level sensory score from 12 panelists | Yes | Data and code on GitHub, per the paper |
| [VegNet](https://europepmc.org/article/PMC/PMC9679474) ([Mendeley](https://data.mendeley.com/datasets/6nxnjbn9w6)) | 6,850 | bell pepper, tomato, chili, NM chile | unripe / ripe / old / dried / damaged | No | CC BY 4.0 · 128 MB |
| [FruitNet v3](https://data.mendeley.com/datasets/b6fftwbr2v) | 14,700+ | apple, banana, guava, **lime**, orange, pomegranate | good / bad / mixed | No | CC BY 4.0 · about 3.25 GB |
| Kaggle [fresh/stale](https://www.kaggle.com/datasets/raghavrpotdar/fresh-and-stale-images-of-fruits-and-vegetables) | n/a | apple, banana, bitter gourd, capsicum, orange, tomato; photographed daily | fresh / stale | No | CC0 · 1.5 GB |
| Kaggle [healthy vs rotten](https://www.kaggle.com/datasets/muhammad0subhan/fruit-and-vegetable-disease-healthy-vs-rotten) | 29,291 | 14 produce types, incl. carrot, cucumber, potato, tomato, bell pepper | healthy / rotten | No | CC0 · 5.2 GB; compiled from other sets |

**License laundering.** Files from [sriramr's 2018 set](https://www.kaggle.com/datasets/sriramr/fruits-fresh-and-rotten-for-classification) (license "Unknown") reappear inside sets re-labeled [Apache-2.0](https://www.kaggle.com/datasets/ulnnproject/food-freshness-dataset) and [CDLA](https://www.kaggle.com/datasets/swoyam2609/fresh-and-stale-classification). The derived licenses cannot be trusted.

**Day-by-day structure.** Only Koyama (daily for 12 days) and Abeer (capture day) are organized by time.

## 3. Detector choice (Oct 2026)

| Model | License | Params | COCO mAP50-95 | Speed | Notes |
|---|---|---|---|---|---|
| **YOLO26n** | AGPL-3.0 / Enterprise | 2.4M | 40.9 (end-to-end 40.1) | **38.9 ms CPU ONNX**, NMS-free; 1.7 ms T4 | Ultralytics' pick for new projects; YOLO27 announced but not out ([models](https://docs.ultralytics.com/models/)) |
| [YOLO11n](https://docs.ultralytics.com/models/yolo11/) | AGPL | 2.6M | 39.5 | 56.1 ms CPU | Stable |
| [YOLO12n](https://docs.ultralytics.com/models/yolo12/) | AGPL | 2.6M | 40.6 | No CPU figure | Docs warn of training instability and slow CPU |
| [RF-DETR-N / S](https://github.com/roboflow/rf-detr) | **Apache-2.0** (Atto–Pico and XL/2XL are PML 1.0) | 30.5M / 32.1M | 48.4 / 53.0 | 2.3 / 3.5 ms T4 TensorRT; **no CPU benchmark** | Trains on COCO-JSON or YOLO format; `model.export(format="onnx")`; needs ≥8 GB VRAM (6 GB for N/S) ([docs](https://rfdetr.roboflow.com/latest/)) |
| [D-FINE-N](https://github.com/Peterande/D-FINE) | Apache-2.0 | 4M | 42.8 | 2.12 ms T4 | COCO format; ONNX export script; can fine-tune from Objects365 weights |
| [DEIM-D-FINE-N](https://github.com/ShihuaHuang95/DEIM) | Apache-2.0 (badge) | 4M | 43.0 | 2.12 ms T4 | |
| [DEIMv2](https://github.com/Intellindust-AI-Lab/DEIMv2) | **Custom non-commercial** ([LICENSE](https://raw.githubusercontent.com/Intellindust-AI-Lab/DEIMv2/main/LICENSE.md)) | N: 3.6M | 43.0 | | Avoid |
| [RT-DETRv2-S](https://github.com/lyuwenyu/RT-DETR) | Apache-2.0 | 20M | 48.1 | 217 FPS T4 | |
| [YOLOX-Nano / Tiny](https://github.com/Megvii-BaseDetection/YOLOX) | Apache-2.0 | 0.91M / 5.06M | 25.8 / 32.8 at 416 px | | Old |

**What AGPL means here.** Ultralytics says AGPL "covers the training code and the models produced," and that SaaS/API deployment still requires either open-sourcing the whole project or buying an Enterprise license. Coursework is listed under the free AGPL tier, not as an exemption ([license](https://www.ultralytics.com/license)). For a public course repo this is fine if the backend code and weights are published under AGPL. If the app is commercialized, switch to D-FINE/DEIM/RF-DETR/RT-DETRv2.

## 4. Auto-labeling for draft boxes

| Model / tool | License | Notes |
|---|---|---|
| [Grounding DINO T/B](https://github.com/IDEA-Research/GroundingDINO) | Apache-2.0; in HF transformers | T: 48.4 COCO zero-shot. Versions 1.5/1.6 Pro (COCO 54.3/55.4) are **API-only and paid** ([repo](https://github.com/IDEA-Research/Grounding-DINO-1.5-API)) |
| [SAM 3 / 3.1](https://github.com/facebookresearch/sam3) | "SAM License": royalty-free, no explicit non-commercial clause ([LICENSE](https://raw.githubusercontent.com/facebookresearch/sam3/main/LICENSE)) | Text or exemplar prompt returns masks, boxes and scores for all instances. 848M params, needs a CUDA GPU, weights gated. SAM 3.1 released 2026-03-27 |
| [OWLv2](https://huggingface.co/google/owlv2-base-patch16-ensemble) | Apache-2.0 | About 0.2B params |
| [Florence-2-large](https://huggingface.co/microsoft/Florence-2-large) | MIT | 0.77B; `<OD>` and `<CAPTION_TO_PHRASE_GROUNDING>`; 37.5 COCO zero-shot |
| [YOLOE-26](https://docs.ultralytics.com/models/yoloe/) | Ships in the AGPL Ultralytics package (page states no license) | LVIS text-prompt mAP 24.7 (n) to 40.6 (x); docs list "dataset bootstrapping" as a use; classes are fixed at ONNX export |
| [YOLO-World v2.1](https://github.com/AILab-CVC/YOLO-World) | GPL-3.0 | LVIS 26.8 (L, 640 px) |

**Caution.** On RF100-VL, Grounding DINO and Qwen2.5-VL score under 2% zero-shot on hard domains ([arXiv 2505.20612](https://arxiv.org/abs/2505.20612)). Expect text prompts to work poorly for rau muống, su su, mướp and similar.

**Free, self-hostable tooling:**
- [Label Studio ML backend](https://github.com/HumanSignal/label-studio-ml-backend) (Apache-2.0): grounding_dino (interactive), yolo (pre-annotation), SAM 2.
- [CVAT Community](https://github.com/cvat-ai/cvat) (MIT, Docker): Nuclio SAM and YOLOv7. SAM 2/3 auto-labeling is **paid tiers only**.
- [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) (GPL-3.0 desktop app, v4.0.0 Aug 2026): Grounding DINO, YOLO-World, YOLOE, SAM 3, Florence-2, Gemini, Qwen3-VL; exports YOLO/COCO/VOC.
- [autodistill](https://github.com/autodistill/autodistill) (Apache-2.0): GroundingDINO/OWLv2/Grounded SAM 2 to YOLOv8. YOLO11 and RF-DETR are not listed; each plugin keeps its model's license.

## 5. Gemini API object detection
- **Format** ([docs](https://ai.google.dev/gemini-api/docs/image-understanding)):
  - The documented prompt is "…The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."
  - Segmentation returns `box_2d`, a polygon `mask` and a `label`; the docs recommend `thinking_level: "minimal"` for it.
  - The examples use `gemini-3.8-flash`.
  - Gemini 2.5 Flash already did this, with thinkingBudget=0 ([blog, Jul 2025](https://developers.googleblog.com/en/conversational-image-segmentation-gemini-2-5/)).
- **Vertex AI** labels the feature **Experimental (Pre-GA)**. Its sample system instruction says "…Never return masks. Limit to 25 objects," with temperature 0.5 ([Vertex](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/bounding-box-detection)).
- **No confidence score.** The documented schema has no score field (my reading), so mAP is not directly defined for Gemini output.
- **Models** ([list](https://ai.google.dev/gemini-api/docs/models)):
  - Stable: `gemini-3.8-flash`, `3.6-flash`, `3.5-flash-lite`, `3.1-flash-lite`.
  - Preview: `gemini-3.1-pro-preview`.
  - 2.5 models are served only to past users; 2.0 is shut down.
- **Tokens** ([media resolution](https://ai.google.dev/gemini-api/docs/media-resolution)): Gemini 3/4 default to 1,120 tokens per image (low 280, medium 560, ultra_high 2,240). Gemini 2.5 uses 258 tokens per 768×768 tile.
- **Prices per 1M tokens** ([pricing](https://ai.google.dev/gemini-api/docs/pricing)):
  - 3.8 Flash: $0.75 in / $3.75 out through 31 Dec 2026, **doubling on 1 Jan 2027**; Batch $0.375 / $1.875.
  - 3.5 Flash-Lite: $0.30 / $2.50.
  - 2.5 Flash-Lite: $0.10 / $0.40.
  - Free tier: data "used to improve our products". Paid tier: no.
- **My cost estimate:** about 1,270 input and 600 output tokens per fridge photo, which is about $0.003 per image on 3.8 Flash and about $0.002 on 3.5 Flash-Lite. 300 test images × 3 runs is under $3.

## 6. Prior work
- **Fridge detection:**
  - AICook (2021, YOLOv5, no mAP reported).
  - [Bukhori et al. 2024](https://ukm.my/jkukm/wp-content/uploads/2024/3605/06.pdf), Jurnal Kejuruteraan 36(5): YOLOv4, 5 classes, 200 images, "100% mAP" during training. It also notes that Food-101, Fruits360 and VegFru have no boxes. It illustrates the small-sample, weak-evaluation pattern to avoid.
- **Vietnamese:** VinaFood21 (EfficientNet-B0, 74.81%) and 30VNFoods (77.54% top-1) are dish classification. I found no paper on Vietnamese raw-ingredient detection (gap; search incomplete).
- **Leafy-green freshness:**
  - Koyama 2021: color statistics plus ORB features into an RBF SVM gave 70% / 77% / 84% accuracy for 4/3/2 classes. This is a direct template for the HSV+LBP+SVM arm.
  - [SpinachXAI-Rec 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12521408/) (Sci Rep 15:35853): DenseNet121 96%, macro-F1 0.97, but with a 70/30 split *after* augmenting to 12k images, so leakage is likely.
  - Abeer 2023: DenseNet201 97.72%.
- **Preprocessing:**
  - [Wang et al. 2023](https://arxiv.org/abs/2311.18814): "underwater image enhancement suppresses the performance of object detection." Raw images were best for all 7 detectors; CLAHE and WB were among the least harmful.
  - [Afifi & Brown, ICCV 2019](https://arxiv.org/abs/1912.06960): wrong white balance degrades CNNs, and WB-emulation augmentation or WB pre-correction helps.
  - Ultralytics training already jitters HSV by default (hsv_h 0.015, s 0.7, v 0.4), and applies CLAHE with p=0.01 if albumentations is installed ([augmentation](https://docs.ultralytics.com/guides/yolo-data-augmentation/)).

## 7. Recommended plan
1. **Data.**
   - Build the test set only from the team's own photos, split by kitchen, and freeze it first.
   - Two annotators label the test set from scratch, with no model drafts and never Gemini drafts, to avoid biasing the comparison.
   - Training adds mapped public data in this order: Viet Hoang Food, Robo1 (filtered to mapped classes), Bangladesh (cabbage, chili, spring onion, gourds), aicook / FridgeAnalysisV2 (fridge context), Nhận Diện Rau plus the water-spinach sets.
   - Remove duplicates with perceptual hashing, drop pre-augmented copies, merge synonyms, and keep a manifest with the license and source of each image.
2. **Detector.**
   - Main model: YOLO26n at 640 px from COCO weights; also try imgsz 960 for small items.
   - Fallback: YOLO11n.
   - Add one Apache-2.0 comparator (D-FINE-N with Objects365 weights, or RF-DETR-N) as the license exit.
   - Measure ONNX latency on the real VPS (p50/p95 over 100 runs).
3. **Labeler.**
   - Round 0: Grounding DINO-T, YOLOE-26 or SAM 3, run on Colab, for generic classes only. Vietnamese-specific classes are labeled by hand.
   - Round 1 onward: the team's own YOLO pre-labels through the Label Studio `yolo` backend or X-AnyLabeling. Log the draft-to-final edit rate.
4. **Gemini baseline.**
   - Run `gemini-3.8-flash` and `gemini-3.5-flash-lite`, logging the model ID and date.
   - Use a JSON schema with the closed 30-class enum (Vietnamese and English names), `box_2d` plus count, a higher object cap than 25, minimal thinking, and the paid tier (user photos are personal data).
   - Run each image 3 times.
   - Metrics: list-level P/R/F1; box-level P/R/F1 at IoU ≥ 0.5 (no mAP, because there are no scores); count MAE; latency; cost.
   - Test with a paired bootstrap by image, and report cost at both 2026 and 2027 prices.
5. **Preprocessing ablation.**
   - Arms: none, GW, CLAHE-L, GW+CLAHE, plus a "WB-cast augmentation" arm.
   - Apply each arm identically at train and test, for both the detector and the freshness classifier.
   - For freshness photos, use white-patch correction from the white card instead of gray-world.
6. **Freshness.**
   - Pretrain on Local Spinach Leaf, plus AgriFreshNET once its produce list is checked, plus VegNet.
   - Fine-tune on the team's own daily photo series.
   - Compare Koyama-style color + LBP/GLCM + SVM against MobileNetV3-Small, split by batch (lô rau), with McNemar.
   - On a subset, also report how well the day-based label agrees with a human visual label.

## 8. Risks and unknowns
- Image provenance and real licenses of the Roboflow community sets are unknown (some may be scraped). Class names are noisy. I checked page metadata only, never the images.
- AgriFreshNET's produce list, Abeer's dataset availability, Objects365's license and LVIS's license on its official page are all **UNVERIFIED**.
- CPU latency for RF-DETR, D-FINE and DEIM is not published, and RF-DETR-N has 30.5M params.
- Gemini detection is Pre-GA on Vertex, models change often, the 3.8 Flash price doubles in Jan 2027, and there are no confidence scores.
- Gray-world fails on single-hue scenes, such as a shelf full of greens.
- Day-based freshness labels may not be visually separable, and FoodKeeper lacks Vietnamese greens.
- Open-vocabulary labelers are weak on region-specific concepts.
- Several Roboflow items in §1.2 were seen only in snippets, because the search budget ran out.
