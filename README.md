# SRAM Wafer Studio

[下載 Windows 桌面版](https://github.com/QooLien/sram-wafer-studio/tree/main/releases)

## 啟動

在 Windows 解壓縮下載檔，雙擊 **Start SRAM Wafer Studio.cmd** 即可開啟桌面視窗。啟動時會最大化，版面以 1920×1080 及 Windows 125% 縮放為目標。需要 Python 3.11 以上（加入 PATH）和 Microsoft Edge WebView2 Runtime。初次啟動若缺少套件，啟動程式會在專案內建立 Python 環境並安裝依賴。

也可執行 `python -m pip install -r requirements.txt` 後執行 `python app.py` 開啟同一個桌面視窗。所有操作均在本機處理，無需開啟瀏覽器、輸入 IP 或使用連接埠。

`examples/sim128/` 包含 WT1～WT3 的合成 ASC 和對應的 TNO 設定，可在介面選「載入 128 芯片範例」試跑。

## 操作

1. **匯入 ASC** 選同一片 wafer 的 1～3 個檔案。優先採用檔名中的 WT1／WT2／WT3，只有 WT3 時就顯示 WT3。所有檔名皆無 WT 時按 STEP 補編號，混合命名無法唯一對應時請補齊檔名。需要試跑時可使用「載入 128 芯片範例」。
2. **Wafer Maps** 可切換已匯入的 WT 和 Pattern。Wafer 的 X/Y 分布區維持等寬高。點選 Chip 可展開 16 × 16 BLK 矩陣，窄視窗可水平捲動。上方可切換 Wafer Map、256 BLK、BLK 明細，並直接切換 WT。矩陣的 Pass 以綠色顯示。點 BLK 後，可在同一張 FBC 圖上按電壓由高到低比較 Scan 和 March，各 Function 保留各自的原始柱值。切換 Pattern 可查看對應的 90% 累積曲線及地址匹配。Function 匹配顯示 Config 電壓。同一 WT 的 BLK 若 Scan Pass、March Fail，點選後會直接展開 March 的 Function sweep。 圖表標籤使用英文。在明細可切換 FBC 與 W/R Match。W/R Match 依電壓堆疊 Read only、Write only、Write & Read、No monitor hit，只計入原始資料有輸出的 Function Fail Address，同一個電壓的重複 Address 只計一次。PDF、PNG、Excel 也包含 Scan／March 合併 FBC 圖及 W/R Match 圖。Hard Fail 明細列出各 WT 實際觸發的 TNO、電壓與 FBC。矩陣用紅色粗體標出目前 Chip、WT 下 Scan 和 March 各自最高的有效 Vmin，同值 BLK 一併標記。 Scan 和 March 的最差電壓相同時，兩者都標示紅色粗體。同一 BLK 同時符合兩者時，格內直接顯示共用電壓。 選定 Pattern 後可匯出向量 PDF、300 dpi PNG 或含可編輯圖表、數據和地址匹配的 Excel。選擇目的地後，檔案寫入其中的 `Analysis_YYYYMMDD/`。
3. **資料核對** 可切換 Fail Address、BLK_FBC_Comparison、Missing BLK Address 和 Chip Vmin。Chip 選取連動資料核對範圍。Fail Address 的表頭固定在資料區上方。上下捲動時只移動資料列，左右捲動時表頭與資料同步，X、Y、BLK、WL、BL、IO、Cat. 保留在左側。「返回上一頁」會回到進入資料核對前的畫面與位置。
4. **匯出報表** 可選「完整 Excel 報表（原版版面）」匯出 Config、Fail Address、FBC 對照、含導覽連結的 Wafer Maps 及選定 Chip 的 256 BLK 分布。也可分別匯出 Address、FBC、Cat Map，或輸出整組圖片寬 37 公分的 PowerPoint。
5. **批次匯出** 可選不同 Lot／Wafer。依完整 LOT 和 WNO 分組；檔名使用前六碼 LOT、Wafer、檔名 WT 標記、ASC 版本及匯出日期。每片只輸出 Cat Wafer Map、Fail Address、Fail BLK 到來源資料夾下的 Address_日期。
6. **TNO 設定** 內的完整版和批次版各自儲存，初始值來自已發佈的 v13.1 與 v1.6。可匯入含 Config 工作表的 Excel 或 CSV，並調整列順序。

### 256 BLK 與 W/R 相關性

- 在 256 BLK 選擇 WT 和 Vmin scope。矩陣顯示各 BLK 的 Vmin。紫框 J 為該範圍的 Judge BLK，橘框 T 為 Tail。**Box Plot & Outliers** 顯示每顆 Chip 的 FBC90% 箱型圖和 16 × 16 離群 BLK 位置。橘色是 Tail，另有顏色標示僅超出上界或低於下界的 BLK。點選位置可開啟明細。用 **Show R/W Match Count** 在矩陣顯示左上 Read only、右上 Write only、左下 Write & Read、右下 No monitor hit 的筆數。
- **W/R Monitor Correlation** 按 WT 選擇 Scan、March 或 Scan & March。匹配取符合既有 Fail Map 判定的 BLK，收集 Pattern 內 Function TNO 的 Fail Address，使用相同 WT、Chip 和完整 Address 匹配任一設定電壓的 W-Low／R-Low Monitor。合併範圍去重。Pearson r 以具備完整 Function FBC 與所選 Monitor 觀測的 Chip 計算，使用可取得的 Fail Address 筆數。支援匯出所有已匯入 WT 的彙總與逐 Chip 資料。

## 判定

- Scan Vmin 僅分析 Scan 有 Fail BLK 的 Chip；March Vmin 僅分析 Scan 全 Pass、March 有 Fail BLK 的 Chip。依各 Pattern 全部 Config TNO 的 256 BLK FBC 分類，不使用 Fail Address 數量。任一 FBC > 0 為 Fail；資料完整且全為 0 才算 Pass。Scan Fail 的 Chip 在 March 圖顯示 Not Applicable，無法確認 Scan Pass 時顯示 No Data。最差 Scan／March BLK 列表同步篩選；原始單 BLK 曲線、整體 Chip Vmin 與 Merge 判定保留。

- 若最高設定測試電壓已達所選模式的 Fail 門檻，Vmin 顯示為「≥ Hard Fail 電壓」下限；例如首個 1.035 V TNO 判 Fail、Hard Fail 設為 1.20 V 時輸出 ≥ 1.20 V。Hard Fail 電壓取 Config Hard Fail 區間的最高設定值，原始測試電壓及觸發 TNO 保留。缺少必要電壓時不推定下限。

- Fail BLK 取 Pattern 終點正值 FBC。Hard Fail、前序 WT Function fail 及同 WT 前序 Pattern 終點 fail 的 BLK 會排除。
- Address Coverage 使用同 WT／Chip／BLK 在 Pattern 區間的 Address 聯集，並保留終點 FBC 和地址差。
- FBC0 取首次正值 FBC 前一個電壓。FBC1～10 取首次達門檻的當站。FBC90% 取第一次達該 BLK 在 Pattern 內最高 FBC 的 90% 的站點。累積曲線按 Config 順序以截至當站的最高 FBC 除以整段峰值；電壓分布保留各站原始 FBC。
- 依 Chip、WT、所選 Vmin scope 計算 Tail。至少四筆 FBC90% Tail 樣本才計算上下界。確定 Vmin 使用原值；最高測試電壓 Fail 而回報 ≥ Hard Fail 電壓的 BLK，使用實際 Fail 測試電壓（例如 1.035 V）參與統計，不把 ≥1.20 V 當成精確值。Pass、缺資料及無實際 Fail 電壓的下限不納入四分位數。高於 Q3 + 1.5 × IQR 且從 Median 往上跨至少兩個實際測試電壓階，才判定為 Tail。電壓階以去重後的測試電壓順序由低到高計算。
- Scan／March 各使用自己的測試範圍。Merge 90% 使用兩段共用的峰值。Chip Vmin 的箱型圖對每個 BLK 取各合格 Pattern 的最高 FBC90% Vmin。兩個電壓階以該 BLK 觸發 Pattern 的電壓計算。Judge 仍使用選定的 FBC 模式。Wafer Map 和矩陣採用同一份 Tail 清單。矩陣並列排除 Tail 前的最高值與排除後的 Judge Vmin。箱型圖顯示加入實際 Fail 電壓樣本前後的上界及回到候選的 BLK；加入後仍符合 Tail 的 BLK 一併排除。
- 「核對既有 VBA 結果」可讀取同一本舊 .xlsm 內的 Config、Fail Address、FBC by BLK 和 Import Index，驗證來源後重新核對。桌面視窗負責互動，輸出的 .xlsx 報表是靜態資料。

## W/R 相關性 Chip 選取

W/R 相關性頁面的 Wafer Map 支援左鍵選單顆、Shift＋左鍵增減多顆 Chip。顯示全部恢復整片，清除選取顯示空集合。散點、匹配統計及 Pearson r 會依選取重新計算；缺少必要資料的 Chip 保留在 Map／清單，但不計入相關係數。點散點或 Chip Breakdown 的「查看 Chip」可開啟座標、地址數與各 BLK 匹配分類，並進入 256 BLK matrix 或 BLK 明細。相同座標的重疊散點可從清單逐顆查看。切換 WT／Pattern 會重設選取。Export Excel 依目前 Chip 選取匯出全部 WT／Pattern。

Stop Sign flow 尾端若回升電壓，達標項目改回溯到該 flow 最後的低電壓 Go/No-Go 項目。例如 0.765 V → 1.26 V，末項達 90% 時回報 0.765 V；連續回升項目同樣回溯，不跨 Stop Sign。原始達標 TNO、電壓與 FBC 保留，明細與匯出另列 Go/No-Go 來源。正常的最高掃描電壓 Fail 仍保留 ≥ Hard Fail 電壓規則。

## English interface and W/R wafer colours

The application interface, validation messages and progress notifications are in English. Source filenames, configured Pattern/Stop Sign names and raw data are retained as supplied. The W/R Correlation map compares captured monitor address counts: orange = W worse (W > R), blue = R worse (R > W), purple = equal positive counts, green = both captured counts zero, grey = incomplete Function coverage or unavailable monitor data. These categories do not imply physical failure severity or complete FBC. Selection outlines preserve category colours during Shift-click multi-selection.

### Tail-adjusted FBC0（v1.8.6）

在 Vmin Mode 選擇 **FBC0 · Tail-adjusted**（內部名稱 `FBC0-Tail`），在 **TNO Configuration** 設定門檻並儲存；設定或模式改變後須重新匯入分析。預設仍為 FBC0，現有 FBC0–FBC10、FBC90% 不變。新模式套用 Chip Vmin、Scan／March／其他 Stop Sign 的 Vmin 與 BLK 明細；Merge 90% 及三張 FBC90% Accumulation 仍使用原算法。Tail BLK 排除仍使用原 FBC90% 統計，與 BLK 內早期 Fail 的排除分開。

逐 BLK、逐相同名稱的 Function，依 Config 原順序比較嚴格降壓區段。同電壓連續測項合併為一站，相同 Function 使用最大 FBC，不相加；各站 Function 組合須一致。末端升壓恢復測項不參與轉折或後續確認，但其原有 Go/No-Go Vmin 規則保留。

對每個 Function 尋找最早符合下列所有條件的主要 Fail 起點：

- 早期 FBC 上限為起點前最大 FBC，必須大於 0，且同時不超過絕對上限及起點 FBC 的指定比例。
- 增加倍率為 `(起點 FBC + 1) / (早期 FBC 上限 + 1)`。
- 斜率為 `max(0, 本站 FBC - 前站 FBC) / (前站電壓 - 本站電壓)`。起點斜率需達到此前最大斜率的指定倍數；此前斜率下限設為「起點電壓區間內增加 1 bit」的斜率，避免平坦區段除以零。
- 起點與第一個非零 FBC 之間需有足夠的不同電壓區間，且從起點開始的指定數量測站均維持不低於起點的 FBC。

| 設定 | 預設值 |
|---|---:|
| Maximum early FBC | 10 bit |
| Early FBC / onset FBC（上限） | 0.05（5%） |
| Minimum FBC increase ratio | 5 |
| Minimum slope increase ratio | 5 |
| Minimum voltage intervals | 2 |
| Main-fail confirmation points（含起點） | 2 |

這些預設值為保守起點，未經正式器件資料校準。各 BLK 的實際早期 FBC 基準由本身曲線決定；例如可能分別為 2 bit、10 bit，而非所有 BLK 共用固定 FBC 判定。符合條件時，只在判定用副本中忽略該 Function 起點之前的非零 FBC 觀測，再對整個 Pattern 套用 FBC0；未確認的其他 Function 失效仍保留。原始 FBC、Fail BLK／Pattern eligibility、Hard Fail／Prior WT 排除均不更動。資料不足、Function 覆蓋不一致、內部電壓回升或無明確轉折時保留原始 FBC0。

例：`0 → 1 → 2 → 80 → 500` 對應 `1.035 → 0.990 → 0.945 → 0.900 → 0.855 V`，可將 1、2 FBC 的早期觀測列為排除候選，修正 FBC0 Vmin 為 0.945 V。這是 FBC 曲線啟發式，不代表已辨識或扣除相同物理地址的 Tail Bit。

BLK 明細新增 **Tail-adjusted FBC0 evidence**，顯示原始／修正 Vmin、排除 TNO、早期 FBC 基準、有效 FBC 門檻（早期上限＋1）、增加倍率、斜率與後續確認。完整 Excel 與 FBC Excel 新增 **Tail FBC0 Audit**；Config 的 L:M 欄保存六項設定，重新匯入 Excel Config 時一併還原。只有證據充分的 Function 會排除早期觀測，其他少量 Fail 不會自動忽略。
