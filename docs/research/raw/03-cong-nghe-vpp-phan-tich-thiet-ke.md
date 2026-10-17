# Tastoria: desk research report (web only, 17 Oct 2026)

**Method.** I opened the linked page for every statement below. Anything I could not open is tagged **UNVERIFIED**. The turn's shared web-search quota ran out partway through. After that I only fetched known official URLs directly, so items 4 (Vietnamese templates) and a few others stay unverified. I installed and downloaded nothing.

---

## 1. Getting diagrams into Visual Paradigm (VP)

**Community Edition (CE)**
- **Still free.** The CE page says "Free for non-commercial uses, including education, non-profit and personal projects" and "Free usage and upgrades forever" ([CE](https://www.visual-paradigm.com/editions/community/)).
- **Current version:** 18.1, build 20261011, for Windows, Linux and macOS ([CE download](https://www.visual-paradigm.com/download/community.jsp)). 18.1 was announced 22 Jun 2026 ([release](https://www.visual-paradigm.com/aboutus/newsreleases/vp181.jsp)).
- **Activation:** you enter a name and email and receive an activation code by email. Registration contacts VP's server, and a firewall can block it ([know-how, 2015](https://knowhow.visual-paradigm.com/license-key-2/register-ce/)). No account sign-in is mentioned.
- **Watermark:** "For Community Edition, a single-lined watermark will be appeared in printout / exported image" ([comparison](https://www.visual-paradigm.com/support/edition-comparison.jsp)). Forum posts from 2010–2014 describe a diagonal watermark once a project has more than one diagram of the same type ([forum](https://forums.visual-paradigm.com/t/valid-community-edition-but-diagonal-watermark-when-more-than-one-diagram-per-diagram-type/11470)). Whether 18.1 still does this: **UNVERIFIED**.
- **Editions are cumulative:** Community < Modeler < Standard < Professional < Enterprise ([VP guide 2022](https://guides.visual-paradigm.com/in-depth-comparison-of-visual-paradigm-editions/)).
  - Modeler: US$6/mo or $99 ([Modeler](https://www.visual-paradigm.com/editions/modeler/)). Standard: $19/mo or $349 ([Standard](https://www.visual-paradigm.com/editions/standard/)).
  - 30-day trial, "No registration" ([download](https://www.visual-paradigm.com/download/)). CE can switch into the evaluation from inside the app ([know-how 2016](https://knowhow.visual-paradigm.com/technical-support/switch-from-ce-to-eval/)).
  - Academic licences are department-wide and must be requested by teaching staff. Standard costs $1,250/yr, and students may use it off-campus ([academic](https://www.visual-paradigm.com/partner/academic/)).

**Which edition has what.** The comparison page's text only shows how many ✔ each row has. I inferred the lowest edition from the cumulative rule. Which column each ✔ sits in is **UNVERIFIED**.

| Feature | ✔ | Lowest edition |
|---|---|---|
| Use case, class, sequence, activity, state machine, component, deployment diagrams; ERD; Java plug-ins | 5 | CE |
| XMI import/export, Excel import/export, Visio import, Rose import, textual analysis | 4 | Modeler |
| Reverse ERD from database or DDL; generate DDL; flow-of-events editor; use-case spec generation; Doc. Composer | 3 | Standard (the Standard page confirms "Generate ERD from database/DDL") |
| PlantUML import, draw.io import, command line | no row | – |

**Import formats (desktop)**
- **Supported importers:** XML, VP project, Excel, XMI, BPMN 2.0, Visio, Rational Rose, RSA EMX/DNX, ERwin, Rhapsody, System Architect, NetBeans 6.x, Bizagi. PlantUML and draw.io are not in the list ([user guide ch.27](https://circle.visual-paradigm.com/docs/export-and-import/importing/importing-xmi/)). draw.io XML can only be opened in VP Online ([know-how 2018](https://knowhow.visual-paradigm.com/?p=13787)).
- **XMI:** menu Project > Import > XMI. Options include "Auto Layout after imported", "Generate new ID" and "Fully follow import XMI". The import overwrites project changes ([UG](https://www.visual-paradigm.com/support/documents/vpuserguide/124/221/6864_importingxmi.html)). VP exports XMI as "2.1" or "2.1UML2" ([CLI](https://www.visual-paradigm.com/support/documents/vpuserguide/124/255/7348_exportingand.html)).
  - Whether a foreign XMI without diagram data produces laid-out diagrams or only Model Explorer elements: **UNVERIFIED**.
  - PlantUML's own XMI export is labelled alpha and works for class diagrams only ([plantuml.com/xmi](https://plantuml.com/xmi)).
- **PlantUML:** a VP marketing article says PlantUML is mapped into VP's meta-model but gives no menu path or edition ([guide](https://www.visual-paradigm.com/guide/from-text-to-architecture-the-ultimate-guide-to-plantuml-visual-paradigm-and-ai-driven-uml/)). PlantUML import is absent from the user guide, the 18.1 notes and the comparison table, so treat a built-in importer as **UNVERIFIED** and assume it does not exist. VPasCode is a browser-only editor ([VPasCode](https://www.visual-paradigm.com/features/plantuml-editor/)).
- **Third-party plug-in "PlantUML-VP" (MIT licence):** converts both ways for class, use case, sequence, component, deployment, state and activity diagrams (activity in new syntax only). Install via Help > Install Plugin; it also has a `Plugin.sh` CLI ([repo](https://github.com/nbourdi/PlantUML-VP-Plugin)). Release v1.0.0 is published ([releases](https://github.com/ntua/PlantUML-VP/releases)), and the latest issue was opened 12 Sep 2026. Plug-ins work in every edition, including CE. Compatibility with VP 18.1: **UNVERIFIED**.
- **Excel import:** needs a template first exported from VP, and creates model elements, not diagrams ([know-how](https://knowhow.visual-paradigm.com/?p=5973)).
- **Database → ERD:**
  - Tools > DB > Reverse Database, over JDBC. The "Form a new diagram" option creates the ERD automatically ([UG](https://www.visual-paradigm.com/support/documents/vpuserguide/3563/3587/85406_reverseengin.html)).
  - Tools > DB > Reverse DDL, from a .sql/.ddl file, with a database type and a "Generate ERD" option ([UG](https://www.visual-paradigm.com/support/documents/vpuserguide/3563/3587/85425_reverseengin.html)).
  - PostgreSQL is supported ([features](https://www.visual-paradigm.com/features/database-engineering-tools/)).
  - Known pitfall: a raw pg_dump containing pg_catalog functions produced no ERD until the user fixed a settings option ([forum 2020](https://forums.visual-paradigm.com/t/problem-trying-to-import-a-ddl-file-in-order-to-create-an-erd/15848)).

**Command line and the .vpp file format**
- VP documents 14 command-line operations, including ExportDiagramImage, ImportXMI/ExportXMI, Excel, and "Running a plug-in without starting Visual Paradigm" ([CLI index](https://visual-paradigm.com/support/documents/vpuserguide/124/255_commandlinei.html), [image export](https://visual-paradigm.com/support/documents/vpuserguide/124/255/7347_exportingdia.html), [plug-in](https://visual-paradigm.com/support/documents/vpuserguide/124/255/84449_runningplug-.html)).
  - The docs only show Windows and Mac paths, and say nothing about edition or display requirements.
  - Forum posts from 2009 and 2011 say the CLI needs a licence file or Modeler and above ([2009](https://forums.visual-paradigm.com/t/export-from-commandline-without-license/10819), [2011](https://forums.visual-paradigm.com/t/generate-html-report-or-jpeg-in-console/11750)).
  - Running it headless under Xvfb: **UNVERIFIED**, and it would mean installing VP on the server anyway.
- **.vpp format is undocumented.** A user wrote in 2014 that it "is a sqlite3 db". VP staff did not confirm this and said "we do not support and not recommend user direct manipulate the project database", pointing to the Open API instead ([forum](https://forums.visual-paradigm.com/t/recommendation-how-to-manipulate-the-model-programatically/12604)). SQLite is plausible but **UNVERIFIED**, so we should not generate .vpp files directly.

### Recommendation: plan for handing over .vpp-ready material
We build a text-only "VP import kit" on the server, and the user assembles the .vpp on a desktop.

**What we generate on the server:**
1. **`uml/*.puml`**, one file per diagram (see the table in §4). Render each with our local PlantUML 1.2024.8 + Graphviz to PNG/SVG. This checks the syntax and gives watermark-free figures for the report. Stay within what the plug-in supports: new activity syntax, no `!include`, no sprites.
2. **`db/schema.sql`**, generated with `alembic upgrade head --sql` ([Alembic offline mode](https://alembic.sqlalchemy.org/en/latest/offline.html)), plus a VP-safe copy **`db/schema_vp.sql`**.
   - The safe copy keeps only CREATE TABLE with PK/FK/UNIQUE: no extensions, functions or triggers, and `vector(384)` replaced by `bytea` with a comment.
   - Reason: whether VP's DDL parser accepts `vector`, `jsonb`, arrays or identity columns is **UNVERIFIED**.
3. **Optional `model/domain.xmi`**, an XMI 2.1 class model. This is experimental.
4. **Use-case specifications as tables.** These belong in the Word report, because VP's flow-of-events editor needs Standard or above.
5. **A step-by-step guide file** for the user, with the steps below.

**What the user does on Windows/macOS:**
1. Install VP CE 18.1, activate it, create `Tastoria.vpp`, and back it up.
2. Install the PlantUML-VP plug-in v1.0.0 and restart. Import one small `.puml` first, then the whole folder, then tidy the layouts. If the plug-in fails on 18.1, redraw the diagrams by hand from the PNGs; that always works in CE.
3. Build the ERD:
   - Preferred: during the 30-day trial (or with Standard+ / an academic licence), run Tools > DB > Reverse DDL on `schema_vp.sql`, choose PostgreSQL, and leave "Generate ERD" on.
   - Alternative: Reverse Database over JDBC against a local Postgres.
   - CE-only fallback: draw the ERD with CE's ERD tool.
4. Optional: Project > Import > XMI with Auto Layout (Modeler+ or trial).
5. Save and commit the `.vpp`. Use the PlantUML renders or VP exports as figures, and ask the lecturer whether a CE watermark is acceptable. Do all trial-only steps in one session; how CE treats a project after trial features were used is **UNVERIFIED**.

---

## 2. Expo / React Native (Oct 2026)

**Versions**
- **Expo SDK 58** was released 15 Oct 2026: "SDK 58 upgrades React Native from 0.86 to 0.88" ([SDK 58](https://expo.dev/changelog/sdk-58)). Expo's table pairs SDK 58 with RN 0.88, React 19.3.0, react-native-web 0.21.0 and Node 22.13 ([versions](https://docs.expo.dev/versions/latest/)).
- **SDK 57:** 30 Jun 2026, RN 0.86 ([changelog](https://expo.dev/changelog)).
- **RN 0.88:** the release post is dated 19 Oct 2026, two days after today, so treat that date as uncertain. It lists no user-facing breaking changes ([RN 0.88](https://reactnative.dev/blog/2026/10/19/react-native-0.88)).

**Expo Go vs development builds**
- The store version of Expo Go will support only SDK 58 ([SDK 58](https://expo.dev/changelog/sdk-58)). Since 3 Sep 2026 you must log in to run projects in Expo Go ([changelog](https://expo.dev/changelog)).
- Expo Go cannot load third-party native code. Expo "strongly recommend[s] using development builds for any real project" ([FAQ](https://docs.expo.dev/faq/)).

**Expo on the web**
- Expo sites "can be statically rendered for SEO and performance, or client-rendered", and Expo recommends react-native-web to maximise code reuse ([Expo web](https://docs.expo.dev/workflow/web/)). Static output generates HTML per route ([static rendering](https://docs.expo.dev/router/web/static-rendering/)).
- **SDK 58 gotcha:** Expo Router now defaults to *server* output when `web.output` is not set ([SDK 58](https://expo.dev/changelog/sdk-58)).

**Web support for the modules Tastoria needs**

| Module | Web support |
|---|---|
| expo-camera | Works, but no video recording, and images come back as base64 ([camera](https://docs.expo.dev/versions/latest/sdk/camera/)) |
| expo-image-picker | Works; must be triggered by a user tap; returns a `File` you can upload with `FormData` ([picker](https://docs.expo.dev/versions/latest/sdk/imagepicker/)) |
| expo-image-manipulator | Resize and JPEG compression work on web ([manipulator](https://docs.expo.dev/versions/latest/sdk/imagemanipulator/)) |
| expo-keep-awake | "Web support is limited" ([keep-awake](https://docs.expo.dev/versions/latest/sdk/keep-awake/)) |

Browser camera access and the Wake Lock API both require HTTPS ([getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [Wake Lock](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)).

**Camera library:** VisionCamera supports iOS and Android only, is built on Nitro Modules, and needs `expo prebuild` ([docs](https://visioncamera.margelo.com/docs)). V5 is out and V4 is no longer maintained ([repo](https://github.com/mrousavy/react-native-vision-camera)).

**On-device inference.** All three options are native-only and need a development build:

| Library | Notes |
|---|---|
| react-native-fast-tflite | .tflite models; CoreML and Android GPU delegates; "NNAPI is deprecated on Android 15"; Expo config plugin + prebuild; works with VisionCamera v5 frame processors ([repo](https://github.com/mrousavy/react-native-fast-tflite)) |
| onnxruntime-react-native | Android/iOS; config plugin + `npx expo prebuild`; ONNX and ORT models; no unsigned tensors except uint8 on Android ([README](https://github.com/microsoft/onnxruntime/tree/main/js/react_native)). Support for the New Architecture / RN 0.88: **UNVERIFIED** |
| react-native-executorch | New Architecture only; "Expo Go is not supported"; RN 0.83+ / SDK 55+, iOS 17+, Android 13+; you can load your own `.pte` models ([repo](https://github.com/software-mansion/react-native-executorch)); lists YOLO and RF-DETR ([site](https://executorch.swmansion.com/)) |

**EAS free tier**
- "Up to 15 Android and 15 iOS builds", low priority, 45-minute timeout, 1,000 MAUs for EAS Update. The cheapest paid plan (Starter) is $19/mo ([pricing](https://expo.dev/pricing)).
- Limits reset monthly ([plans](https://docs.expo.dev/billing/plans/)). Once they are used up, new builds are unavailable until the 1st of the next month ([billing FAQ](https://docs.expo.dev/billing/faq/)).
- You can run `--local` builds on macOS or Linux, one platform at a time ([local builds](https://docs.expo.dev/build-reference/local-builds/)).

### Recommendation
- **Use one Expo Router codebase:** Android first, with the web as a second target of the same app. Image inference runs on the server, so the full flow (capture → upload → poll → chips → mâm → cooking) works on the web with the modules above.
- **Do not build a separate React web app;** it would double the maintenance.
- Put the native-only parts (VisionCamera + TFLite live boxes) in `*.native.tsx` files, with a picker/upload fallback on web.
- Set `web.output: "single"` explicitly so nginx can serve it as static files.
- Use a development build from day one.
- **SDK choice:** SDK 58 is two days old. Adopt it only if VisionCamera v5 and fast-tflite declare support; otherwise use SDK 57. Pin the version for the semester.
- The landing page stays separate (§5).

---

## 3. Infrastructure: licensing and current versions

| Component | Status as of Oct 2026 |
|---|---|
| MinIO | Repository archived 25 Apr 2026: "THIS REPOSITORY IS NO LONGER MAINTAINED". The community edition is "distributed as source code only", with no new binaries; the README points to AIStor ([repo](https://github.com/minio/minio)). In May 2025 the "Embedded UI Console is now deprecated" and LDAP/OIDC logins moved to AIStor ([release](https://github.com/minio/minio/releases/tag/RELEASE.2025-05-24T17-08-30Z)) |
| SeaweedFS | Apache-2.0; S3 API including presigned URLs; `weed mini` is "fine for single-node production" ([repo](https://github.com/seaweedfs/seaweedfs)) |
| Garage | v2.4.1. Its `--single-node` mode "should not be used in production" because it has no redundancy ([quick start](https://garagehq.deuxfleurs.fr/documentation/quick-start/)). Presigned URLs supported; Expiration lifecycle rules partly; no versioning or bucket policies ([S3 compatibility](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/)). Licence: **UNVERIFIED** (repo page was blocked) |
| RustFS | Apache-2.0; has a web console; features are labelled Available or Preview ([repo](https://github.com/rustfs/rustfs)) |
| Redis | 8.0 and later: you choose RSALv2, SSPLv1 or AGPLv3. 7.2 and earlier: BSD-3 ([licences](https://redis.io/legal/licenses/)) |
| Valkey | BSD-3-Clause, under LF Projects ([repo](https://github.com/valkey-io/valkey)). Latest 9.1.2, 1 Sep 2026, Docker image `valkey/valkey` ([download](https://valkey.io/download/)) |
| RQ | Actively maintained: 2.12.0 released 30 Aug 2026; "requires Redis >= 5 or Valkey >= 7.2" ([PyPI](https://pypi.org/project/rq/)) |
| pgvector | 0.8.7, 1 Oct 2026 ([changelog](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md)). Supports Postgres 13+; Docker image `pgvector/pgvector:pg18`; HNSW indexes up to 2,000 dimensions (halfvec 4,000) ([README](https://github.com/pgvector/pgvector)). PostgreSQL 18.6 is the current release ([versioning](https://www.postgresql.org/support/versioning/)) |
| FastAPI | 0.143.3, 16 Oct 2026, Python ≥3.10 ([PyPI](https://pypi.org/project/fastapi/)) |
| SQLAlchemy | 2.1.5, 16 Oct 2026, Python ≥3.11 ([PyPI](https://pypi.org/project/SQLAlchemy/)) |
| Alembic | 1.20.0, 11 Sep 2026 ([PyPI](https://pypi.org/project/alembic/)) |
| Argon2 / JWT | The FastAPI tutorial uses PyJWT + `pwdlib[argon2]` ([tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)). pwdlib 0.3.1 notes "Starting Python 3.13, passlib won't work anymore" ([PyPI](https://pypi.org/project/pwdlib/)). argon2-cffi is at 25.1.0 ([docs](https://argon2-cffi.readthedocs.io/en/stable/)) |
| ONNX Runtime | v1.31.0, released 9 Oct (year not shown) ([releases](https://github.com/microsoft/onnxruntime/releases)) |

Two adjacent risks I found in the ML stack:
- **LightFM:** last release 1.17 on 20 Mar 2023, source distribution only, no wheels ([PyPI](https://pypi.org/project/lightfm/)).
- **Ultralytics YOLO is AGPL-3.0.** An Enterprise licence is needed "if you want to use Ultralytics YOLO without open-sourcing your entire project" ([licence](https://www.ultralytics.com/license)).

### Recommendation
- **Replace MinIO.**
  - Durable default: a Docker volume behind a `Storage` interface. FastAPI issues short-lived HMAC-signed links, checks them, then answers with `X-Accel-Redirect` to an `internal` nginx location. This uses only core nginx features ([nginx core](https://nginx.org/en/docs/http/ngx_http_core_module.html)); `secure_link` "is not built by default" ([module](https://nginx.org/en/docs/http/ngx_http_secure_link_module.html)).
  - The 30-day deletion of raw images becomes a scheduled job.
  - If the report must say "S3-compatible", put SeaweedFS `weed mini` behind the same interface.
- **Use Valkey 9.1 instead of Redis,** and keep RQ.
- **Pin versions:** PostgreSQL 18 + pgvector 0.8.7, FastAPI 0.143.x, SQLAlchemy 2.1.x on a Python 3.12 image, Alembic 1.20, PyJWT + pwdlib[argon2].
- **Serve the ranking model from exported numpy arrays** rather than importing LightFM in the API.
- **Keep the repository public** to satisfy Ultralytics' AGPL.

---

## 4. Systems analysis & design documentation standards

- **ISO/IEC/IEEE 29148:2018** is the active edition, published 30 Nov 2018, replacing the 2011 edition ([IEEE SA](https://standards.ieee.org/ieee/29148/6937/)). The ISO page was blocked, so the SRS outline below is from memory: **UNVERIFIED**. It runs: introduction (purpose, scope, product perspective and functions, user characteristics, limitations) → references → specific requirements (external interfaces, functions, usability, performance, logical database, design constraints, system attributes) → verification → appendices.
- **Use-case template (Cockburn, TR 96.03a, 1998).** Fields: Goal in Context, Scope, Level, Preconditions, Success End Condition, Failed End Condition, Primary Actor, Trigger, Main Success Scenario, Extensions, Sub-Variations, Related Information (priority, performance target, frequency, super/subordinate use cases, secondary actors, channels), Open Issues, Schedule ([mirror](https://www.cs.otago.ac.nz/coursework/cosc461/uctempla.htm)). The RUP-style fields (brief description, basic/alternative flows, special requirements, pre/post-conditions, extension points) are **UNVERIFIED**.
- **UML 2.5.1** is a formal OMG specification from Dec 2017 (formal/17-12-05), with normative XMI including the diagram-interchange model UMLDI ([OMG](https://www.omg.org/spec/UML/2.5.1/)). It has 14 diagram types: 7 structure and 7 behaviour ([VP guide](https://www.visual-paradigm.com/guide/uml-unified-modeling-language/what-is-uml/)).

Suggested Tastoria diagram set (my own mapping):

| Diagram | Content |
|---|---|
| Use case | Actors: user, admin, ML worker. Use cases: Hồ sơ 60s, Quét tủ lạnh, Xác nhận nguyên liệu, Mâm cơm hôm nay, Đổi món, Thiếu gì?, Nấu cả mâm, Nấu xong, Nhật ký, consent/data rights |
| Activity | Scan → chips → mâm, with swimlanes App/API/Worker; weekly retraining with the validation gate |
| Sequence | POST /scans → 202 → RQ → worker → polling; POST /meal-plans; /cook-sessions/{id}/complete |
| Class | The §6.4 entities plus a service per module |
| State machine | Scan (queued → processing → done/failed), Consent (granted → revoked), CookSession, pantry urgency |
| Component | The 9 modules, the worker, storage, database and queue |
| Deployment | VPS with the Docker Compose services, the Android device, Colab/Kaggle |

- **ERD.** VP draws crow's-foot cardinality and supports conceptual, logical and physical ERDs ([VP](https://www.visual-paradigm.com/guide/data-modeling/what-is-entity-relationship-diagram/)). The original papers, Chen 1976 (doi:10.1145/320434.320440) and Codd 1970 (doi:10.1145/362384.362685), returned 403 on ACM, so their details are **UNVERIFIED**.
- **Normalisation.** Microsoft's archived article explains 1NF–3NF well but wrongly says "Fourth normal form, also called Boyce-Codd Normal Form" ([MS Learn](https://learn.microsoft.com/en-us/office/troubleshoot/access/database-normalization-description)). Do not cite it for BCNF. Use Silberschatz et al., 7th ed., ch. 6 (E-R) and ch. 7 (Relational Database Design) slides instead ([db-book](https://www.db-book.com/slides-dir/index.html)); I did not open the slide contents.
- **Normalisation issues an examiner will spot in the §6.4 schema:**
  - `synonyms`, `allergen_groups`, `flavor_tags` and `steps` are multi-valued columns, which breaks strict 1NF. Either move them to junction tables or justify them in writing.
  - `recipes.kcal…fiber` and `pantry_items.urgency` are derived values. Document them as cached results.
- **Vietnamese PTIT/HUST report template:** not found, because the search quota ran out (**UNVERIFIED**). Ask the lecturer for the official template.
- **WCAG correction for the design doc:** criterion 2.5.5 (44×44 px) is Level AAA. WCAG 2.2 (Recommendation, 12 Dec 2024) adds 2.5.8 at Level AA with 24×24 px ([WCAG 2.2](https://www.w3.org/TR/WCAG22/)).

### Recommendation
- Structure the SRS on the 29148 outline.
- Write one Cockburn-style table per use case, with Vietnamese labels.
- Draw a sequence diagram for each core use case.
- Produce the physical ERD from the DDL, plus a table-by-table 3NF/BCNF check that justifies every denormalisation.

---

## 5. Landing page

- **Structure (NN/g, 2024).** Five principles: make the homepage easy to reach; communicate who you are and what you do with a tagline and value proposition; show content through examples; use specific CTA labels, not "Learn More"; keep it simple ([NN/g](https://www.nngroup.com/articles/homepage-design-principles/)).
- **Attention.** Users spend 57% of viewing time above the fold and 74% in the first two screenfuls ([NN/g 2018](https://www.nngroup.com/articles/scrolling-and-attention/)). Avoid "false floors" that make the page look finished ([NN/g](https://www.nngroup.com/articles/page-fold-manifesto/)). Start headings with the key words ([NN/g](https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/)).
- **Performance.** "Good" means LCP ≤2.5 s, INP ≤200 ms and CLS ≤0.1, measured at the 75th percentile ([web.dev](https://web.dev/articles/vitals)). Give the hero image `fetchpriority="high"` and never lazy-load it ([LCP](https://web.dev/articles/optimize-lcp)). Use WOFF2 fonts, `font-display: swap` or `optional`, and subset the font ([fonts](https://web.dev/articles/font-best-practices)).
- **Accessibility (WCAG 2.2 AA).** Text contrast 4.5:1, colour never the only cue, touch targets at least 24 px.

### Recommendation
- A single static HTML/CSS page served by nginx, with no framework JavaScript.
- **Hero:** one plain sentence on what Tastoria does, a mâm photo the team took itself, and two buttons: "Tải app Android" and "Dùng trên web".
- **Then:** three steps, results that were actually measured, a privacy section (consent, deleting data, Law 91/2025), and an FAQ.
- Self-host Be Vietnam Pro as WOFF2 with a Vietnamese subset.
- Smart App Banner details: **UNVERIFIED** (Apple's page did not render), and they only apply to iOS anyway.

---

## Risks / unknowns
1. Which VP edition has each feature is inferred from ✔ counts, not read from the table columns.
2. The PlantUML-VP plug-in is untested on 18.1, and it is what makes the non-ERD diagrams importable. The fallback is redrawing by hand.
3. A foreign XMI may import as model elements without diagrams.
4. VP's DDL parser may reject PostgreSQL-specific types.
5. CE watermark rules in 18.1, and how CE behaves after trial features were used, are unknown.
6. VP's command-line edition and headless requirements, and the internal `.vpp` format, are undocumented.
7. SDK 58 is two days old, the RN 0.88 post carries a future date, and the native libraries' support for SDK 58/RN 0.88 is unverified (onnxruntime-react-native especially).
8. The free EAS tier allows 15 builds per platform per month, so native changes must be batched.
9. Open infra questions: Garage's licence, RustFS's maturity, and whether the nginx Docker image includes `secure_link`.
10. LightFM may not build on modern Python; Ultralytics' AGPL licence applies.
11. Unverified sources: the 29148 outline, the RUP template, the Chen/Codd ACM pages, and any Vietnamese university template. The search quota ran out mid-task.
