# Tastoria: desk research on competitors, the differentiation claim and the evidence (as of 17/10/2026)

**How this was done.** I used web reading only, through WebFetch and WebSearch; nothing was downloaded or installed. Research sub-agents and I opened each source. I opened the load-bearing pages again myself: Samsung Food+, DELISH KITCHEN, me:new, Frish, Cookpad VN, Thực đơn 365, Fridgenie, Chef Genie, Mealime's closing page, the two optimisation papers, and every statistics source.

Limits:
- Anything not seen on an opened page is marked UNVERIFIED.
- Google Play pages could not be read. Android install counts therefore come from third-party trackers (AppGoblin, androidrank) and are estimates.
- App Store dates that show no year are 2026.
- The shared search budget for this run (200 searches) ran out partway. The coverage gaps this caused are listed in section 7.

---

## 1. Key findings

1. **Recognising ingredients from a photo is now common.** It is in Samsung Food+ and the Family Hub camera (now built on Gemini), ChatGPT and Gemini, NoWaste, Cooksy, ChefGPT, and many very small apps.
2. **Claim (a), building a whole meal set from what is on hand, already exists in Japan.**
   - DELISH KITCHEN suggests a main dish, side dish and soup together (主菜・副菜・汁物) from leftovers the user types in.
   - me:new builds staple + main + side dinner sets (主食・主菜・副菜) from fridge leftovers.
   - What I did not find in any product: splitting one ingredient's quantity across the dishes of one meal, or building a Vietnamese mâm cơm from the user's own stock.
3. **Claim (b), prioritising by freshness, is weak.**
   - Samsung Food+ (2024) builds plans "prioritizing those nearing use-by-date".
   - Frish (Japan) builds sets with "賞味期限の近いものほど優先" (items nearest their best-before date first).
   - KitchenPal, Cooklist and Grocy suggest recipes from items about to expire.
   - Only estimating freshness from the image itself is still fairly open, and even that has prototypes (Fridgenie).
4. **Claim (c), a model trained on Vietnamese ingredients, is unproven.** I found no Vietnamese dataset of raw ingredients in a fridge. But Samsung's Gemini-based AI Vision now claims "region-specific items". So (c) only counts if Tastoria measurably beats a Gemini baseline.
5. **The competitor examples in the doc are weak.**
   - Mama has been broken since 2022 and has 6 ratings.
   - Cookez has 3 ratings.
   - Chef Genie is an entry in a Gemini developer competition, not a product.
   - Cold-to-Cooked could not be found at all.
   - The real comparisons are Samsung Food+, DELISH KITCHEN, me:new, Frish, Eat This Much, Cookpad VN and Thực đơn nấu ăn 365.
6. **The problem evidence mostly holds.**
   - The UNEP figures check out.
   - The adult overweight figure (12% → 19.6%) appears only in a 2024 Dân trí article. The doc's other source, Công luận, does not contain it.

---

## 2. Competitor comparison

Y = yes, P = partly, N = no. Source codes are listed after the tables.

### 2a. Global and Japan

| Product | Photo → ingredients | Freshness / expiry | Whole multi-dish meal | Splits stock across dishes | Calorie target | Price · platform | Traction · status | Src |
|---|---|---|---|---|---|---|---|---|
| **Samsung Food / Food+** (formerly Whisk) + Family Hub | Y. Phone "Vision AI" (Food+, 2024; not mentioned in the current store text). Fridge camera: "37 unobscured fresh food items". Gemini version covers "fresh and packaged… region-specific items", rolling out from 09/2026 | Use-by dates set by hand, with alerts. Food+ plans prioritise items "nearing use-by-date" | N: weekly plans of single recipes | N | Y: calorie and macro targets | Free; Food+ $6.99/mo or $59.99/yr · iOS, Android, fridge | iOS 4.8 (6.4K); Android ~3.8M installs; no Vietnamese in its 2024 language list | G1–G4 |
| **ChatGPT / Gemini** (general LLMs) | Y, through general image input | Not documented | Only if the user asks; no stored inventory | Only if asked | Only if asked | Free tiers; Gemini VN AI Plus ₫132,000/mo · all platforms | Healthline test (25/2/2025): ingredients misidentified, 4-photo limit | G5 |
| **SuperCook** | N: pick from 2,000+ ingredients, or voice | N | N | N | N | Free · iOS, Android, web | iOS 4.8 (22K) but iOS not updated since 06/2022; Android ~3.9M installs | G6 |
| **Cooklist** | P: short kitchen video (PantryScan, 02/2025), barcode, purchase import | Expiry notifications; recipes "with ingredients that is expiring soon" | N (AI meal planner uses in-stock items) | N | N (nutrition facts only) | Pro $5.99–9.99/mo · iOS | 4.7 (11K) | G7 |
| **KitchenPal** | N: barcode, voice, text | Dates set by hand, with alerts; recipes from expiring items | N | P: shopping list leaves out what is in stock | N | $3.99/mo or $14.99/yr · iOS, Android, web | Android ~372K installs; active | G8 |
| **NoWaste** | Y: several groceries in one photo, plus receipts and barcodes; scans expiry dates | Date tracking and reminders; no freshness estimate from the image | N (meal plans added 04/2026) | N | N | Pro $6.99/yr · iOS, Android, web | iOS 4.2 (753) | G9 |
| **Eat This Much** | N (barcode only) | N | P: whole-day plans split into meals | P: virtual pantry that "our algorithms will use it up with priority"; automatic leftovers (Premium) | Y: calorie and macro targets | Free; Premium $5/mo, billed yearly · iOS, Android, web | Site claims 4.7 from 32K+ reviews | G10 |
| **Mealime** | N | N | N: weekly plan of single dinner recipes | N (claims to "eliminate food waste") | P: calorie filter per recipe | Pro was $2.99/mo · iOS, Android | 4.8 (54K). **Shuts down 21/10/2026** (users moved to Albertsons Meals Hub) | G11 |
| **Yummly** (Whirlpool) | Y in 2018 (camera ingredient recognition) | UNVERIFIED | N | N | N | — | **Shut down 12/2024**; yummly.com now redirects to KitchenAid | G12 |
| **Plant Jammer** (Denmark) | N | N | N: one dish; "prioritizes what's already in the user's larder or fridge" | N | N | — | **Company registered as ceased 9/10/2024** | G13 |
| **ChefGPT** | Y: ingredient photo → recipe | N | N | N (uses every ingredient, but within one recipe) | P: macro grams per meal | Paid subscription · iOS, Android | 4.4 (233) | G14 |
| **Chef Genie / Fridgenie** (Gemini API competition, 2024) | Y (prototypes) | Fridgenie: shows "minimum storage periods"; items "nearing their expiration are highlighted in red" | N | N | N | Prototype only | No store listing | G15 |
| **Cold-to-Cooked** | Not found: domains don't resolve, Devpost returned 403 | — | — | — | — | — | Existence UNVERIFIED | — |
| **DELISH KITCHEN** (Japan) | N | N | **Y: "主菜・副菜・汁物をまとめて自動提案"**; "冷蔵庫の余りものを入力するだけで献立が決まります" | Not stated | P: calorie logging | Free; premium ¥480/mo · iOS, Android | US App Store 4.9 (1.6K) | G16 |
| **me:new** (Japan) | N | N | **Y: "主食・主菜・副菜を基本とする夕食の献立"**, sets made automatically from fridge leftovers or sale items | Not stated | P: shows kcal and salt | Free plus paid plan · iOS, Android | Japan App Store 4.2 (17K ratings) | G17 |
| **Frish** (Japan) | P: photo of receipt or forwarded order email | **Y: "賞味期限の近いものほど優先"** | Y (献立 meal sets) | Not stated | P: weighs kcal and nutrients | Free · iOS | 1 rating (US store); last update 23/3/2025 | G18 |

### 2b. Vietnam

| Product | Photo → ingredients | Freshness | Whole mâm | Split | Calories | Price · platform | Traction · status | Src |
|---|---|---|---|---|---|---|---|---|
| **Cookpad VN** | N: typed ("Nói cho chúng tôi biết trong tủ lạnh có gì…") | N | N: weekly menu; shopping list "chỉ thêm những gì còn thiếu" | N | N (weight-loss filter only) | Premium 25K–69K₫ · iOS, Android | VN App Store 4.8 (3.9K ratings), v2026.42 | V1 |
| **Thực đơn nấu ăn 365** (VNP Group) | N (voice search by dish or ingredient) | N | P: curated "meal platters… for Vietnamese family meals", not built from the user's stock | N | N | Free · Android | 500K+ installs, 4.88 (11,792); v26.30, 15/3/2026 | V2 |
| **Cooky** | N | N | P: used to sell a "set cơm 99K" | N | N | — | **Dormant**: last Android build 27/11/2024, iOS listing 404, cooky.vn now sells cơm gà | V3 |
| **Mama** (FTECH) | N | N | Claims a "thực đơn" | N | N | Free · iOS | 6 ratings; reviews from 2022 report login failures | V4 |
| **Cookez** | N | N | N: search by ingredients on hand, plus a plan | N | P: calories per dish | Free · iOS, Android | 3 ratings; maintained in 2025 | V5 |
| **Điện máy Xanh Vào bếp / Bách hóa Xanh** | N | N | P: editorial articles only (e.g., "30 mâm cơm cả tháng", updated 26/5/2026, with cost for 3–4 people) | N | N | Free · web | — | V6 |
| **Samsung Bespoke AI (VN site)** | Y (fridge camera) | "AI Vision quản lý hạn dùng, tự động cảnh báo thực phẩm sắp hết hạn & gợi ý menu…" | N | N | — | Fridge hardware | No Vietnamese dishes named | V7 |
| **Cooksy** (English-only, sold in the VN store) | Y: fridge or pantry photo | N | N | N | N | Credits 29K–12,999K₫ · iOS | No ratings | V8 |

In the Vietnamese market I found **no Vietnamese-language app that recognises ingredients from a photo** (coverage limited), and nothing that builds a mặn + rau + canh tray from the user's own stock.

---

## 3. Is the differentiation claim true?

| Claim | Strength | Prior art |
|---|---|---|
| (a) Whole tray, with ingredients shared across dishes | **Weak as stated. Moderate only in a narrow form**: a Vietnamese tray whose dish quantities fit the stock on hand. | Multi-dish sets from leftovers: DELISH KITCHEN, me:new, Sharp's AIoT fridge (2018, G19). Allocating stock across recipes is standard optimisation: van Rooijen et al. 2024 (integer programming that picks recipe combinations against package sizes, "with no waste", P4); Hespanhol & Aswani 2017 (integer program with ingredient perishability, P5); meals as bundles of dishes in MealRec+ (SIGIR 2024, P2); Elsweiler & Harvey 2015 (P1). It is an algorithmic step, so competitors could copy it easily. |
| (b) Freshness priority | **Weak.** | Samsung Food+ (G1), Frish (G18), KitchenPal and Cooklist, Grocy's "due score" (P8), patent US9965798B1 (camera reads quality; recipes ordered so food is used before its best-before date, P6). Freshness from the image: patent US20170284733A1 (P7) and Fridgenie (G15). The only partly open angle is computing urgency from the photo plus days since the item was first seen, with no dates typed in. |
| (c) Model trained on Vietnamese ingredients | **Unproven.** | Existing Vietnamese datasets are of cooked dishes or fruit: VinaFood21 (21 dishes, 13,950 images), 30VNFoods, UIT-VinaFruit20 (P9). A raw-ingredient fridge dataset would be new. But Gemini-based AI Vision claims "region-specific items" (G3), so the value to users depends on beating the Gemini baseline the doc already plans. |

**Verdict.** Every component has prior art. The full chain (one photo → Vietnamese mâm cơm with quantities that fit the stock → freshness first → kcal target) was not found in any single product, and nothing like it exists in Vietnamese.

Suggested rewrite of §1.5: replace the "different at three points" framing with "the first integration built for the Vietnamese tray, measured on Vietnamese data". Name DELISH KITCHEN, me:new, Frish and Samsung Food+ as the closest competitors.

---

## 4. Checking the problem evidence

| Doc claim | Verdict | Best URL |
|---|---|---|
| 1.05 billion t wasted in 2022 | Confirmed. It **includes inedible parts** and equals 132 kg per person across all sectors. | E1, E2 |
| Households 631 Mt (~60%) | Confirmed: "631 million tonnes, or up to 60 per cent". | E1 |
| 79 kg per person per year | Confirmed as the **household** per-capita figure. UN News words it as "each person wastes 79 kilogrammes"; OWID shows the world household value for 2022 as 79.12. | E1, E4 |
| Hotter countries waste more "because of fresh food and poor storage" | Only the correlation is established. UNEP says hotter countries "appear to have more food waste per capita in households", and gives fresh produce and weak cold chains as *possible* reasons. **Soften to "có thể do".** | E1, E2 |
| Vietnam per-capita figure (requested) | **About 72 kg per person per year in households, for 2022.** OWID's SDG 12.3.1 data (updated 31/7/2026) gives Vietnam 72.11 (2019: 76.71, matching the 76 kg in the 2021 report). RMIT Vietnam (29/9/2026) cites the 2024 report for 72 kg. The report's confidence rating for Vietnam is UNVERIFIED; one aggregator's 68 kg is UNVERIFIED. | E4, E5 |
| UNEP primary report | UNVERIFIED: the page returned 403 and I did not open the PDF. | E3 |
| Nutrition survey: 22,400 households, 25 provinces | Confirmed. | E6, E7 |
| Fruit and vegetables at 66.4–77.4% of recommendation | Confirmed. | E6, E7 |
| Meat 84.0 → 136.4 g per person per day | Confirmed. | E6, E7 |
| **Adults overweight/obese 12% → 19.6%** | **Only in Dân trí 21/9/2024** ("ở người trưởng thành tăng từ 12 lên 19,6%"). It is not in Công luận, even though the doc cites both. VietnamPlus (26/12/2023) gives 19% for adults in 2020. The 8.5% → 19.0% figure reported at the 2021 launch is for **ages 5–19** (E9). In the same launch coverage, 19.6% is the under-5 *stunting* rate (E7), so the two may have been mixed up. The Ministry of Health page returns 404. Cite Dân trí explicitly, or use the better-documented 5–19 figure. | E8, E9, E10, E11 |

---

## 5. User research evidence (Vietnam)

- **Dinner structure:** 3.0 dishes per dinner, 62 minutes of cooking, 97% Vietnamese food. Q&Me, April 2023: 300 women who cook daily in Hanoi and HCMC, 6,000+ dinner photos. This supports the 3-dish tray template (U1).
- **Families:** 78% of mothers cook dinner every day. 41% go to the wet market every day and 16% go 4–6 times a week (Q&Me 2017, n=1,032; U2). So many family fridges hold little stock for long.
- **Living alone:** among people aged 18–29 who live alone, only 26% cook just for themselves; this group spends 820K₫ a month eating out vs 700K₫ on ingredients (Q&Me 2015, n=500; U3). Among Cần Thơ students, 18% never cook and 30.8% cook 1–2 times a week (2020; U4). 83% of urban 18–40-year-olds use food delivery (Q&Me Dec 2021, n=660; U5).
- **Households:** 80.5% owned a fridge in 2019, up from 31.6% in 2009. Average household size was 3.6 (2019) and 3.5 in 2024 (U6). The share of one-person households since 2019 was not found.
- **Food waste:**
  - Hanoi: more than 70% of household food waste happens during preparation and cooking; expired food and declining quality are the drivers (Liu & Nguyen 2020; U7).
  - HCMC (n=642): cooking skill and knowing the family's preferences reduce waste. Planning and storage matter little because people buy fresh food often. Intending to waste less does not lead to wasting less (Phan et al. 2026; U8).
  - Gen Z: 59.3% cook more than needed and 59.3% keep food until it spoils (Tạp chí Công Thương 2025, weak method; U9).
- **"Hôm nay ăn gì" fatigue:** I found no Vietnamese survey that quantifies it, only opinion pieces (U12).
- **Health apps:** 7.9% of young people used a nutrition app (2015 data, n=356; U11). Nothing recent was found.

---

## 6. Features to add or cut

The doc's rule: a feature is added only if it (R1) makes photo → tray more accurate, (R2) helps go from tray to eating, or (R3) creates training data.

**Add**
1. **A "chụp đồ vừa mua" photo** of the market haul at purchase time (R1 + R3).
   - It gives the real purchase date dᵢ.
   - Items are not hidden behind each other: Samsung only recognises "unobscured" items and warns "results vary by manner of placement".
   - It yields freshness-over-time training images with known age.
   - It suits daily wet-market shoppers, who get no receipts.
2. **Gram quantities per dish, scaled to the number of eaters and E_mâm** (R2). Most waste happens at preparation (Hanoi, more than 70%), and overcooking is common. This lever may matter as much as freshness.
3. **Leftovers as a stock type after "Nấu xong"** (R1 + R3), as Eat This Much does with automatic leftovers.
4. **Make "YOLO vs Gemini" the headline result**, per class, on Vietnamese items (rau muống, rau ngót, mồng tơi, đậu phụ, chả lụa…) (R1). If the LLM wins at detection, keep the trained model for counting and freshness.

**Keep out (the doc already excludes these, and competitor evidence supports that)**
- Receipt and barcode import: wet-market food has neither.
- Weekly menus: every incumbent has them, and daily shoppers don't need them.
- Expiry push reminders: tracker apps already do this, and intending to waste less doesn't change behaviour. Show urgency inside the tray instead.
- Grocery ordering: Cooky is dormant and Mealime is closing.

**Cut from the doc:** the Mama, Cookez, Cold-to-Cooked and Chef Genie comparisons.

---

## 7. Risks and unknowns

1. **A free LLM could replace it.** Samsung's Gemini-based AI Vision began rolling out in phases from 09/2026. Whether a 30-class YOLO beats Gemini is unknown. ChatGPT's misidentifications are documented.
2. **Fridge photos are hard.** Items hide each other, door bins and the freezer are out of view, and quantity in grams is hard to estimate. Even Samsung's fixed camera has users "manually check and adjust the list". Accuracy is unknown.
3. **Freshness from images is unvalidated** for meat, fish and produce in plastic bags, and carries food-safety liability.
4. **Daily shoppers' fridges hold little.** "Use what is about to spoil" may matter more to singles and weekly shoppers than to families. The share of weekly shoppers is unknown.
5. **People living alone cook little**, and delivery competes for them.
6. **Weak evidence in places:** no quantified data on decision fatigue; the adult obesity figure is secondary only; Vietnam's FWI confidence rating is unknown; Q&Me samples are small online panels in Hanoi and HCMC.
7. **Market data:** Android installs are estimates; Japanese ratings come from the App Store only.
8. **Not covered (search budget ran out):** Korean and Chinese set-menu apps, Lofit/Calo and other Vietnamese diet apps, Zalo mini apps, AI features in MoMo or Grab, Vietnamese student projects, Fridgy, KitchenMate and CozZo.
9. **Samsung Food could add Vietnamese.** Samsung's Vietnam site already advertises expiry alerts and menu suggestions in Vietnamese.

---

## Sources

**Global and Japan**
- G1: https://samsung-newsroom-production.barbariangroup.com/us/?p=74058 (mirror of Samsung US Newsroom, 29/8/2024; the canonical news.samsung.com URL timed out). UK version: https://news.samsung.com/uk/upgraded-samsung-food-raises-the-bar-for-food-experiences-at-ifa-2024
- G2: https://www.samsung.com/us/explore/family-hub-refrigerator/overview/
- G3: https://news.samsung.com/uk/samsung-enhances-long-term-value-of-refrigerators-and-laundry-appliances-with-ai-focused-software-updates (10/9/2026)
- G4: https://apps.apple.com/us/app/samsung-food-meal-planner/id1133637674 · https://appgoblin.info/apps/com.foodient.whisk
- G5: https://www.healthline.com/health/how-to-use-ai-for-food-swaps-and-recipe-ideation · https://chatgpt.com/g/g-5zGMpAO1A-picture-pantry-chef · https://gemini.google/subscriptions/
- G6: https://apps.apple.com/us/app/supercook-recipe-by-ingredient/id1477747816 · https://appgoblin.info/apps/com.supercook.app
- G7: https://apps.apple.com/us/app/cooklist-pantry-meals-recipes/id1352600944
- G8: https://kitchenpalapp.com/en/ · https://appgoblin.info/apps/fr.icuisto.icuisto
- G9: https://www.nowasteapp.com/ · https://apps.apple.com/us/app/nowaste-food-inventory-list/id926211004
- G10: https://www.eatthismuch.com/ · https://www.eatthismuch.com/pricing
- G11: https://www.mealime.com/closing · https://apps.apple.com/us/app/mealime-meal-plans-recipes/id1079999103 · https://support.mealime.com/article/105-filtering-recipes-by-calories
- G12: https://whirlpool.mediaroom.com/2018-01-08-Yummly-2-0-Will-Integrate-Curated-Cooking-Experiences-into-Whirlpool-R-Kitchen-Appliances · https://www.plantoeat.com/blog/2024/12/yummly-is-closing-discover-the-best-meal-planning-alternative/ · https://en.wikipedia.org/wiki/Yummly
- G13: https://agfundernews.com/plant-jammer-scoops-4-7m-from-oetker-miele-to-develop-its-digital-chef · https://danskcvrapi.dk/nyt/37654655-ophor-2024-10-09
- G14: https://apps.apple.com/us/app/chefgpt/id6449961549
- G15: https://ai.google.dev/competition/projects/chef-genie · https://ai.google.dev/competition/projects/fridgenie · https://ai.google.dev/competition
- G16: https://apps.apple.com/us/app/-/id1177907423
- G17: https://apps.apple.com/JP/app/id977041956
- G18: https://apps.apple.com/us/app/frish/id1543534868
- G19: https://news.mynavi.jp/article/20180806-sharp/

**Vietnam**
- V1: https://apps.apple.com/vn/app/id585332633?l=vi
- V2: https://www.androidrank.org/application/thuc-don-50k/com.vnplace.thucdon50k · https://apkpure.com/thuc-don-nau-an-365/com.vnplace.thucdon50k
- V3: https://apkpure.com/cooky/vn.cooky.cooky/versions · https://cooky.vn
- V4: https://apps.apple.com/vn/app/id1473100317
- V5: https://apps.apple.com/vn/app/cookez/id6744654472
- V6: https://www.dienmayxanh.com/vao-bep/toi-nay-an-gi-goi-y-30-mam-com-hap-dan-ca-thang-khoi-lo-xem-24445
- V7: https://www.samsung.com/vn/home-appliances/bespoke-home/
- V8: https://apps.apple.com/vn/app/id6749788075?l=vi

**Papers and patents**
- P1: https://researchportal.northumbria.ac.uk/en/publications/towards-automatic-meal-plan-recommendations-for-balanced-nutritio/
- P2: https://arxiv.org/abs/2404.05386
- P4: https://agris.fao.org/search/ar/records/662912bc2b3930d7cdc09e8c (DOI 10.1016/j.resconrec.2024.107559)
- P5: https://arxiv.org/abs/1703.07932
- P6: https://patents.google.com/patent/US9965798B1/en
- P7: https://patents.google.com/patent/US20170284733A1/en
- P8: https://grocy.info/
- P9: https://arxiv.org/abs/2108.02929v1 · https://github.com/HuynhXuanLam-IT44/30VNFoods · https://vjs.ac.vn/index.php/jst/article/view/16299

**Problem evidence**
- E1: https://news.un.org/en/story/2024/03/1148036
- E2: https://www.eco-business.com/press-releases/world-squanders-over-1-billion-meals-a-day-un-report/
- E3 (not opened): https://www.unep.org/resources/publication/food-waste-index-report-2024
- E4: https://ourworldindata.org/grapher/food-waste-per-capita (values read from its CSV endpoint)
- E5: https://www.rmit.edu.vn/vi/tin-tuc/tat-ca-tin-tuc/2026/sep/lang-phi-thuc-pham-va-vong-xoay-phan-xet
- E6: https://congluan.vn/ty-le-nguoi-thua-can-beo-phi-o-viet-nam-tang-hon-10-trong-10-nam-post128273.html
- E7: https://thanhtra.com.vn/an-sinh-AFA9C5670/nguoi-viet-an-qua-nhieu-thit-32A9F8AE.html
- E8: https://dantri.com.vn/suc-khoe/ty-le-thua-can-beo-phi-tang-cao-bat-thuong-20240921114101227.htm
- E9: https://news.tuoitre.vn/news/society/20220709/vietnam-sees-surge-in-childhood-obesity/68020.html
- E10: https://www.vietnamplus.vn/kiem-soat-tinh-trang-thua-can-beo-phi-o-tre-em-va-nguoi-truong-thanh-post917793.vnp
- E11 (returns 404): https://moh.gov.vn/en/tin-noi-bat/-/asset_publisher/3Yst7YhbkA5j/content/bo-y-te-cong-bo-ket-qua-tong-ieu-tra-dinh-duong-nam-2019-2020

**User research**
- U1: https://qandme.net/en/report/vietnam-cooking-survey-what-6000-dinner-photo-tells-us.html
- U2: https://qandme.net/en/report/how-does-the-modern-trade-change-purchase-behaviors-of-housewives.html · https://www.slideshare.net/slideshow/survey-vietnam-moms-shopping-behavior-change/77163157
- U3: https://qandme.net/en/report/Vietnamese-youth-cooking-at-home.html
- U4: https://sti.vista.gov.vn/publication/view/10021330b7fd6e70bbe6681021597299-e2d57537dff050cb1e34da4a78d1d285-310763.html
- U5: https://qandme.net/en/report/food-delivery-trend-in-vietnam-2022.html
- U6: https://www.nso.gov.vn/?p=16888 · https://nso.gov.vn/tin-tuc-thong-ke/2025/05/thong-cao-bao-chi-ket-qua-khao-sat-muc-song-dan-cu-nam-2024/
- U7: https://api.crossref.org/works/10.3390/su12166565
- U8: https://researchnow.flinders.edu.au/en/publications/towards-sustainable-food-consumption-understanding-household-food/
- U9: https://tapchicongthuong.vn/nghien-cuu-su-khac-biet-ve-hanh-vi-lang-phi-thuc-pham-giua-cac-the-he-o-viet-nam-hien-nay-245709.htm
- U11: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.2196/mhealth.6490&resultType=core&format=json
- U12: https://nhandan.vn/trua-nay-an-gi-post989090.html · https://www.sggp.org.vn/hom-nay-an-gi-post566063.html
