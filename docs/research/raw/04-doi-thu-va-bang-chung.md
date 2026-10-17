# Tastoria: competitor and evidence desk research (web only, 17/10/2026)

**How this was done**
- Five parallel web sweeps (global competitors in two parts, Asian prior art and papers, Vietnamese competitors, user research), plus my own checks.
- Every item was opened in this session unless it is marked **UNVERIFIED**. I re-opened the items the verdict depends on myself: Samsung Food+, DELISH KITCHEN, me:new, Frish, Fridgenie, Chef Genie, Eat This Much, Cookpad VN, Thực đơn 365, the Mealime closure, the Samsung Gemini update, and every statistic.
- The shared web-search budget for this turn (200 queries across all agents) ran out partway through, so some areas were not covered. They are listed under Risks.
- Android installs marked * come from third-party trackers (AppGoblin, androidrank). Google Play pages don't render when fetched.
- No files were downloaded or installed.

## 1. Bottom line

- **Each piece already exists somewhere, but not the whole chain.** No single product does one photo → a Vietnamese mâm cơm, quantities split across dishes, freshness first, and a kcal target. Nothing comparable exists in Vietnamese.
- **(a) Whole meal set: partly anticipated.** Japanese 献立 apps already put together main + side + soup sets from leftovers: DELISH KITCHEN, and me:new with 17K ratings.
- **(b) Freshness priority: weak.** Samsung Food+ (2024) already builds plans "prioritizing those nearing use-by-date". Frish says "賞味期限の近いものほど優先" (items nearest their best-before date come first).
- **(c) Vietnamese-trained model: the strongest of the three, but only if it beats Gemini when measured.**
- **§1.5 names weak competitors.** Mama has been broken since 2022, Cookez has 3 ratings, Cold-to-Cooked could not be found, and Chef Genie is a competition prototype. The real ones are Samsung Food+, DELISH KITCHEN, me:new, Frish, Eat This Much, Cookpad VN and Thực đơn nấu ăn 365.
- **Problem evidence mostly holds.** The UNEP figures are correct, with two nuances. The rau quả and thịt figures are correct. The adult obesity figure "12% → 19.6%" appears only in Dân trí 2024 and is **not** in the Công luận article the doc cites.

## 2. Competitor comparison

### Global and Asia

| Product (status) | Photo → ingredients | Freshness / expiry | Whole multi-dish meal | Splits shared stock | Calorie target | Price · platform | Traction | Src |
|---|---|---|---|---|---|---|---|---|
| Samsung Food / Food+ (ex-Whisk, renamed 30/8/2023; active) | Yes: phone "Vision AI" (2024; not mentioned in 2026 store text). Fridge camera recognises "37 unobscured fresh food items". Gemini version in the US from 5/2026, other markets from 9/2026 | Use-by dates set by hand, plus alerts. Food+ plans "prioritizing those nearing use-by-date" | No (weekly plans of single recipes) | No | Yes (calorie + macro) | Free; Food+ $6.99/mo or $59.99/yr · iOS/Android/fridge | iOS 4.8 (6.4K); ~3.8M Android* | [1–7] |
| Eat This Much | No (barcode only) | No. Pantry is "used up with priority" | Daily plans of several meals | Pantry-aware | Yes | Free; Premium $5/mo billed yearly · iOS/Android/web | "4.7 from 32,000+ reviews" (vendor's claim) | [8] |
| DELISH KITCHEN カスタム献立 (JP) | No (leftovers typed in) | No | **Yes**: "主菜・副菜・汁物をまとめて自動提案" (main, side and soup proposed together) | Not stated | Calorie logging | Free; ¥480/mo premium | US store 4.9 (1.6K) | [9] |
| me:new (JP) | No | No | **Yes**: 主食・主菜・副菜 (staple, main, side) dinner sets, auto-built from "冷蔵庫の残り物" (fridge leftovers) | Not stated | Shows kcal and salt | Free + paid plan | JP store 4.2 (17K) | [10] |
| Frish (JP) | Receipt photo or forwarded order e-mail | **Yes**, expiry priority | Yes (献立 sets) | Not stated | Takes kcal and nutrients into account | Free · iOS | Tiny (1 US rating) | [11] |
| Cooklist | Kitchen video scan, barcode, purchase import | Expiry notifications; recipes using expiring items | No | No | No | Pro $5.99–9.99/mo · iOS | 4.7 (11K) | [12] |
| KitchenPal | No (barcode/voice) | Dates set by hand; alerts; recipes from expiring items | No | Shopping list skips items in stock | No | $3.99/mo · iOS/Android/web | ~372K* | [13] |
| NoWaste | Yes: one photo adds several items; scans expiry dates | Date tracking and reminders | No | No | No | Pro $6.99/yr | iOS 4.2 (753) | [14] |
| SuperCook | No (tick list or voice) | No | No | No | No | Free | iOS 4.8 (22K), no iOS update since 6/2022; ~3.9M* | [15] |
| Mealime (**closes 21/10/2026**) | No | No | No (weekly single dinners) | Claims to "eliminate food waste"; no method documented | Per-recipe calorie filter | Pro $2.99/mo, now free | 4.8 (54K) | [16] |
| Yummly (shut 12/2024) | Had camera ingredient recognition (2018) | – | No | – | – | – | Site redirects to KitchenAid | [17] |
| Plant Jammer (company ceased 9/10/2024) | No | No | Single dish | Favoured larder items | No | – | – | [18] |
| ChatGPT / Gemini (general-purpose) | Yes, ad hoc; misidentification documented | No | Only if prompted | No persistent inventory | Only if prompted | Free tiers; Gemini AI Plus ₫132,000/mo in VN | – | [19, 20] |
| ChefGPT | Photo → recipe | No | No | "All-In" mode, within one recipe only | Macros per meal | Subscription | 4.4 (233) | [21] |
| Chef Genie; Fridgenie (Gemini API Developer Competition entries) | Yes | Fridgenie: shows storage periods, near-expiry items in red | No | No | No | Prototypes | – | [22] |
| Cold-to-Cooked | **Not found.** No site, app or Devpost page could be opened. UNVERIFIED that it exists | | | | | | | – |

Smart fridges:
- LG ThinQ Food (CES 2026): an internal camera identifies ingredients and suggests recipes [23].
- Sharp's 2018 fridge proposed 献立 from stored food [31].

### Vietnam

| Product | Photo | Freshness | Whole mâm | Split | Calories | Price · platform | Status | Src |
|---|---|---|---|---|---|---|---|---|
| Cookpad (VN) | No; typed: "Nói cho chúng tôi biết trong tủ lạnh có gì, chúng tôi nói bạn nấu được món gì" | No | No. Weekly menu of recipes; shopping list "Chỉ thêm những gì còn thiếu" | No | No (only a weight-loss filter) | Premium 25k–69k₫ · iOS/Android | VN store 4.8 (3.9K); 10M+ global* | [34] |
| Thực đơn nấu ăn 365 (VNP Group) | No (voice search by ingredient) | No | Curated "meal platters… for Vietnamese family meals", not built from the user's stock | No | No | Free · Android | 500K+, 4.88 (11,792), v26.30 on 15/3/2026* | [35] |
| Cooky | No | No | Used to sell meal kits / "set cơm 99K" | No | No | iOS listing 404; last Android build 27/11/2024 | Dormant; cooky.vn now sells cơm gà | [36] |
| Mama – Trợ lý nội trợ (FTECH) | No | No | Claims a "thực đơn" | No | No | Free · iOS | 6 ratings; reviews from 2022 say login fails | [37] |
| Cookez | No | No | Recipes by ingredient, plus a plan | No | Kcal per dish | Free · iOS/Android/web | 3 ratings | [38] |
| Điện máy Xanh "Vào bếp" / Bách hóa Xanh | No | No | Editorial mâm articles only (e.g., 30 trays, priced for 3–4 people) | No | No | Web | – | [39] |
| Samsung Bespoke AI Family Hub+ (VN) | Yes | "quản lý hạn dùng, tự động cảnh báo thực phẩm sắp hết hạn & gợi ý menu" | No | No | – | Fridge (out of stock) | No Vietnamese dishes named | [40] |
| Cooksy (English-only, listed in VN store) | Fridge photo | No | No | No | No | Credits 29k–12,999k₫ | No ratings | [41] |

## 3. Verdict on the differentiation claim

**(a) Whole tray with ingredients shared across dishes: weak as written, moderate in a narrower form.**
- Building a multi-dish set from food on hand is already done and proven commercially in Japan: DELISH KITCHEN [9], me:new [10], Frish [11], and Sharp's fridge from 2018 [31].
- Spreading shared stock across recipes is standard in research:
  - van Rooijen et al. 2024 use mathematical programming to pick recipe combinations against package sizes, aiming for zero waste [26].
  - Hespanhol & Aswani 2017 use an integer program that models ingredient perishability [27].
  - Patent US9965798B1 covers similar ground [30].
- Not found anywhere: a product that says it splits one ingredient's quantity across the dishes of a single meal, or any generator for cơm + mặn + rau + canh.
- That gap is real but narrow. Splitting quantities is a constraint in the solver, not a moat.

**(b) Freshness priority: weak.**
- Products already rank by expiry: Samsung Food+ [1], Frish [11], Cooklist and KitchenPal [12, 13], Grocy's "Due score" [25], and Eat This Much's pantry priority [8].
- The one open angle is judging urgency from the image plus days since the item was first seen, with no dates typed in. Even that is partly covered by Fridgenie [22] and patent US20170284733A1 [30].

**(c) Model trained on Vietnamese ingredients: the most defensible, but conditional.**
- The Vietnamese datasets found label cooked dishes (VinaFood21, 30VNFoods) or fruit types (UIT-VinaFruit20). None labels raw ingredients in a fridge [32].
- But Samsung's Gemini-based AI Vision now claims "branded and region-specific items", rolling out in phases from 9/2026 [4].
- So (c) only counts if the YOLO model beats the Gemini baseline the doc already plans, on a frozen test set of Vietnamese items, or matches it at lower cost, lower latency, offline, or with better privacy. Make that comparison the headline result.

**Suggested plain wording for §1.5:** "Nhận diện ảnh, ghép bộ món từ đồ thừa (DELISH KITCHEN, me:new) và ưu tiên đồ sắp hết hạn (Samsung Food+, Frish) đều đã có. Tastoria kết hợp chúng cho mâm cơm Việt: chia lượng nguyên liệu giữa các món, ước lượng độ tươi từ ảnh không cần nhập hạn dùng, và đo mô hình trên nguyên liệu Việt so với Gemini."

## 4. Problem evidence check

| Claim in the doc | Result | Best URLs | Note |
|---|---|---|---|
| 1.05 billion t wasted in 2022 | Correct | [43, 44] | Includes inedible parts; equals 132 kg/capita across all sectors |
| Households 631 Mt ≈ 60% | Correct | [43] ("up to 60 per cent"), [44] | |
| 79 kg/capita/yr | Correct, and it is the **household** figure | [43]; OWID world household 2022 = 79.12 [46] | UN News words it as "each person wastes 79 kg", which is ambiguous; 132 kg is the all-sector total |
| Hotter countries waste more because of fresh food and poor storage | Overstated | [43] | UNEP says hotter countries "appear to" waste more and gives these reasons only as "possibly". Write "có thể do" |
| Vietnam household waste per capita | **72 kg/capita/yr (2022)** | OWID (FAO/UNEP SDG 12.3.1 data, updated 31/7/2026: 72.11; 2019: 76.71) [46]; RMIT, 29/9/2026 [47] | The 2021 report gave 76 kg. A third-party site's 68 kg conflicts; OWID supports 72. The confidence rating for Vietnam is UNVERIFIED (report annex not opened) |
| Survey of 22,400 households in 25 provinces | Correct | [48, 49] | |
| Rau quả at 66.4–77.4% of recommendation | Correct | [48, 49] | Measured against the adult dietary pyramid |
| Thịt 84.0 → 136.4 g/person/day | Correct | [48, 49] | Urban figure is 155.3 g |
| Adult overweight/obesity 12% → 19.6% | **Secondary source only** | Dân trí, 21/9/2024: "ở người trưởng thành tăng từ 12 lên 19,6%" [50] | Not in Công luận [48]. Launch coverage's 8.5% → 19.0% is for ages 5–19 [49, 51]. VietnamPlus gives adults 19% in 2020 [52]. In 2020, 19.6% was also the stunting rate for under-5s [49], an easy mix-up. The NIN report table could not be found and the MoH page returns 404 [53] |

The canonical UNEP report page returns 403 to automated fetches and its key-messages file is a PDF, so neither was opened [45]. Cite the report itself, with UN News as the access route.

## 5. User research evidence (Vietnam)

**Small families fit a three-dish tray.**
- 78% of working mothers in Hà Nội/HCMC cook dinner every day (n=1,032, 2017) [56].
- A Q&Me study of more than 6,000 dinner photos (n=300 women who cook daily, 4/2023) found 3.0 dishes per dinner, 62 minutes of cooking, and 97% Vietnamese food [57].
- Average household size is 3.6 (Census 2019) and 3.5 (Household Living Standards Survey 2024). 80.5% of households owned a fridge in 2019, up from 31.6% in 2009 [61].

**But their fridges turn over fast.**
- 41% of mothers go to the wet market every day and another 16% go 4–6 times a week [56].
- Wet-market trips fell from 25.17 to 18.86 a month between 2010 and 2018 (Nielsen) [68].
- Little food sits for long, and chợ purchases have no receipts or barcodes.

**Students and singles cook little.**
- Among 18–29-year-olds living alone (n=500, 2015), only 26% cook just for themselves. They spend 820k₫ a month eating out vs 700k₫ on ingredients [54].
- 18% of Cần Thơ students never cook and 30.8% cook only 1–2 times a week [55].
- 83% of urban 18–40-year-olds use food delivery (n=660, 12/2021) [58]. 65% used a delivery app in the past month (Decision Lab 2025) [60].

**Waste happens in the kitchen.**
- In Hà Nội, over 70% of household food waste is generated during preparation and cooking. Expired food and declining quality drive the rest [62].
- Among Gen Z, 59.3% cook more than needed and 59.3% keep food until it spoils (weak sample) [65].
- In HCMC (642 households), planning and storage have limited effect because people buy fresh food often and in small amounts. Intending to waste less does not lead to wasting less [64].
- In a 2024 study, planning (β −0.189) and storing (β −0.145) reduced waste (n=203) [63].
- Nationally, more than 8 Mt of edible food is discarded each year, about US$3.9bn; 32% of it is vegetables and fruit [66].

**Decision fatigue ("hôm nay ăn gì") is not quantified.**
- No Vietnamese survey measures it; only editorial pieces exist, such as Nhân Dân, 17/9/2026 [69].
- Health-app use is low and the data is old: 14.1% of smartphone-owning 15–24-year-olds had a health app (n=1,028, 2015) [67].

## 6. Ideas worth adding or cutting

Each idea is tested against the doc's rule: R1 makes photo → mâm more accurate, R2 helps go from mâm to eating, R3 creates training data.

**Add**
1. **"Chụp đồ vừa mua"**: a photo of the market haul on the counter, as an alternative to the fridge photo.
   - R1: an unobstructed view. Even Samsung's fixed camera only handles "unobscured" items and asks users to adjust the list [3, 5].
   - R3: images with a known purchase date feed the freshness time series.
   - It suits daily chợ shoppers, and replaces receipt scanning (Frish, NoWaste, Cooklist), which doesn't work at chợ.
2. **Gram quantities per dish, scaled to the number of eaters and E_mâm** (R2). This targets the waste that happens during preparation and over-cooking [62, 65].
3. **"Must use" pin**: let the user tap 1–2 ingredients the tray has to use, as DELISH KITCHEN and Frish do (R1, cheap).
4. **Leftovers as stock after "Nấu xong một chạm"** (R1 + R3). Eat This Much charges for "automatic leftovers" [8].

**Cut, or keep out (most are already excluded)**
- **Expiry push reminders.** Several competitors offer them, and the HCMC study shows intentions don't change behaviour [64].
- **Barcode and receipt scanning.** Chợ produce has neither.
- **Weekly plans.** People shop daily; Samsung and Cookpad already do weekly plans; Mealime is closing [16].
- **Ordering.** Cooky's grocery business went dormant [36].
- **The weak competitor examples in §1.5.**
- Keep the **calorie target**, but optional. It is standard among competitors (Samsung, Eat This Much), not a differentiator, and demand in Vietnam is unmeasured.

## 7. Risks and unknowns

1. **Gemini may simply be better.** Samsung's Gemini AI Vision is going global from 9/2026 [4], and ChatGPT/Gemini already handle photo → recipe. YOLO on about 30 classes could lose that comparison, so have a cost, latency, offline or privacy argument ready.
2. **Real fridge photos are hard**: occlusion, plastic bags, door bins. Estimating quantity in grams from one photo is unvalidated.
3. **Judging freshness from in-fridge images** has no Vietnamese dataset, and judging meat or fish this way is unreliable.
4. **"Use what's about to spoil" may matter little to daily chợ shoppers.** Students may not cook enough to stay. Test both with your own fridge-photo audit or diary study.
5. **Data gaps**:
   - No survey quantifies "hôm nay ăn gì".
   - The share of one-person households is only available from Census 2009 (7.3%, UNVERIFIED).
   - There is no data on student food waste.
   - The confidence rating for Vietnam's FWI estimate is unknown.
   - The primary source for the adult obesity figure is missing.
6. **Data caveats**: Android installs are tracker estimates; Japanese apps' ratings are from the US store; Cold-to-Cooked could not be found.
7. **Not covered because the search budget ran out**:
   - Korean and Chinese set-meal composers; Kurashiru and Cookpad JP 献立 features.
   - Vietnamese calorie apps (Lofit, Calo), Zalo mini apps, and AI features in MoMo, Grab or ShopeeFood.
   - Vietnamese hackathon projects.
   - Kantar, YouGov, Cimigo and WWF-Vietnam studies.
8. **A reviewer can challenge novelty with the Japanese 献立 apps.** Cite them up front.

## Sources
[1] https://samsung-newsroom-production.barbariangroup.com/us/?p=74058 (Samsung US Newsroom, 29/8/2024; mirror domain, because the canonical news.samsung.com URL timed out) · UK copy: https://news.samsung.com/uk/upgraded-samsung-food-raises-the-bar-for-food-experiences-at-ifa-2024
[2] https://apps.apple.com/us/app/samsung-food-meal-planner/id1133637674
[3] https://www.samsung.com/us/explore/family-hub-refrigerator/overview/
[4] https://news.samsung.com/uk/samsung-enhances-long-term-value-of-refrigerators-and-laundry-appliances-with-ai-focused-software-updates (10/9/2026)
[5] https://samsung-newsroom-production.barbariangroup.com/us/samsung-expands-ai-capabilities-bespoke-ai-family-hub-refrigerators-major-update/
[6] https://appgoblin.info/apps/com.foodient.whisk
[7] https://9to5google.com/2023/08/30/whisk-samsung-food-app-rebrand/
[8] https://www.eatthismuch.com/ · https://www.eatthismuch.com/pricing
[9] https://apps.apple.com/us/app/-/id1177907423
[10] https://apps.apple.com/JP/app/id977041956
[11] https://apps.apple.com/us/app/frish/id1543534868
[12] https://apps.apple.com/us/app/cooklist-pantry-meals-recipes/id1352600944
[13] https://kitchenpalapp.com/en/ · https://appgoblin.info/apps/fr.icuisto.icuisto
[14] https://apps.apple.com/us/app/nowaste-food-inventory-list/id926211004 · https://www.nowasteapp.com/
[15] https://apps.apple.com/us/app/supercook-recipe-by-ingredient/id1477747816 · https://appgoblin.info/apps/com.supercook.app
[16] https://www.mealime.com/closing · https://apps.apple.com/us/app/mealime-meal-plans-recipes/id1079999103 · https://support.mealime.com/article/105-filtering-recipes-by-calories
[17] https://en.wikipedia.org/wiki/Yummly · https://www.plantoeat.com/blog/2024/12/yummly-is-closing-discover-the-best-meal-planning-alternative/ · https://whirlpool.mediaroom.com/2018-01-08-Yummly-2-0-Will-Integrate-Curated-Cooking-Experiences-into-Whirlpool-R-Kitchen-Appliances
[18] https://danskcvrapi.dk/nyt/37654655-ophor-2024-10-09 · https://agfundernews.com/plant-jammer-scoops-4-7m-from-oetker-miele-to-develop-its-digital-chef
[19] https://gigazine.net/gsc_news/en/20230926-chatgpt-see-hear-speak · https://www.healthline.com/health/how-to-use-ai-for-food-swaps-and-recipe-ideation · https://chatgpt.com/g/g-5zGMpAO1A-picture-pantry-chef (OpenAI's own launch post returned 403, so its fridge example is UNVERIFIED)
[20] https://gemini.google/subscriptions/
[21] https://apps.apple.com/us/app/chefgpt/id6449961549 · https://www.chefgpt.xyz/features/pantryChef
[22] https://ai.google.dev/competition/projects/chef-genie · https://ai.google.dev/competition/projects/fridgenie
[23] https://www.lg.com/global/newsroom/news/home-appliance-solution/lg-signature-evolves-with-ai-redefining-premium-home-appliances-at-ces-2026/
[25] https://grocy.info/
[26] https://agris.fao.org/search/ar/records/662912bc2b3930d7cdc09e8c (DOI 10.1016/j.resconrec.2024.107559)
[27] https://arxiv.org/abs/1703.07932
[30] https://patents.google.com/patent/US9965798B1/en · https://patents.google.com/patent/US20170284733A1/en
[31] https://news.mynavi.jp/article/20180806-sharp/
[32] https://arxiv.org/abs/2108.02929v1 · https://github.com/HuynhXuanLam-IT44/30VNFoods · https://vjs.ac.vn/index.php/jst/article/view/16299
[34] https://apps.apple.com/vn/app/id585332633?l=vi
[35] https://www.androidrank.org/application/thuc-don-50k/com.vnplace.thucdon50k · https://apkpure.com/thuc-don-nau-an-365/com.vnplace.thucdon50k
[36] https://apkpure.com/cooky/vn.cooky.cooky/versions · https://cooky.vn
[37] https://apps.apple.com/vn/app/id1473100317
[38] https://apps.apple.com/vn/app/cookez/id6744654472
[39] https://www.dienmayxanh.com/vao-bep/toi-nay-an-gi-goi-y-30-mam-com-hap-dan-ca-thang-khoi-lo-xem-24445 · https://www.bachhoaxanh.com/kinh-nghiem-hay/mam-com-cuoi-tuan-chi-4-mon-thoi-ma-ngon-het-nac-1204679
[40] https://www.samsung.com/vn/home-appliances/bespoke-home/
[41] https://apps.apple.com/vn/app/id6749788075?l=vi
[43] https://news.un.org/en/story/2024/03/1148036 (27/3/2024)
[44] https://www.eco-business.com/press-releases/world-squanders-over-1-billion-meals-a-day-un-report/ (copy of the UNEP press release)
[45] https://www.unep.org/resources/publication/food-waste-index-report-2024 (returned 403; not opened)
[46] https://ourworldindata.org/grapher/food-waste-per-capita (read through its CSV endpoint)
[47] https://www.rmit.edu.vn/vi/tin-tuc/tat-ca-tin-tuc/2026/sep/lang-phi-thuc-pham-va-vong-xoay-phan-xet
[48] https://congluan.vn/ty-le-nguoi-thua-can-beo-phi-o-viet-nam-tang-hon-10-trong-10-nam-post128273.html
[49] https://thanhtra.com.vn/an-sinh-AFA9C5670/nguoi-viet-an-qua-nhieu-thit-32A9F8AE.html
[50] https://dantri.com.vn/suc-khoe/ty-le-thua-can-beo-phi-tang-cao-bat-thuong-20240921114101227.htm
[51] https://news.tuoitre.vn/news/society/20220709/vietnam-sees-surge-in-childhood-obesity/68020.html
[52] https://www.vietnamplus.vn/kiem-soat-tinh-trang-thua-can-beo-phi-o-tre-em-va-nguoi-truong-thanh-post917793.vnp
[53] https://moh.gov.vn/en/tin-noi-bat/-/asset_publisher/3Yst7YhbkA5j/content/bo-y-te-cong-bo-ket-qua-tong-ieu-tra-dinh-duong-nam-2019-2020 (404)
[54] https://qandme.net/en/report/Vietnamese-youth-cooking-at-home.html
[55] https://sti.vista.gov.vn/publication/view/10021330b7fd6e70bbe6681021597299-e2d57537dff050cb1e34da4a78d1d285-310763.html
[56] https://qandme.net/en/report/how-does-the-modern-trade-change-purchase-behaviors-of-housewives.html · https://www.slideshare.net/slideshow/survey-vietnam-moms-shopping-behavior-change/77163157
[57] https://qandme.net/en/report/vietnam-cooking-survey-what-6000-dinner-photo-tells-us.html
[58] https://qandme.net/en/report/food-delivery-trend-in-vietnam-2022.html
[60] https://www.decisionlab.co/racing-ahead-vietnams-competitive-food-delivery-landscape
[61] https://www.nso.gov.vn/?p=16888 · https://nso.gov.vn/tin-tuc-thong-ke/2025/05/thong-cao-bao-chi-ket-qua-khao-sat-muc-song-dan-cu-nam-2024/
[62] https://api.crossref.org/works/10.3390/su12166565 (Liu & Nguyen, *Sustainability* 2020; abstract)
[63] https://iieta.org/node/17752
[64] https://researchnow.flinders.edu.au/en/publications/towards-sustainable-food-consumption-understanding-household-food/
[65] https://tapchicongthuong.vn/nghien-cuu-su-khac-biet-ve-hanh-vi-lang-phi-thuc-pham-giua-cac-the-he-o-viet-nam-hien-nay-245709.htm
[66] https://news.tuoitre.vn/vietnam-wastes-nearly-4bn-in-edible-food-annually-103250930133910138.htm
[67] https://pmc.ncbi.nlm.nih.gov/articles/PMC6009816
[68] https://vietnamnews.vn/economy/479951/modern-format-stores-luring-away-vietnamese-shoppers-survey.html
[69] https://nhandan.vn/trua-nay-an-gi-post989090.html
