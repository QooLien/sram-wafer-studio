# SRAM Wafer Studio

[下載 Windows 桌面版](https://github.com/QooLien/sram-wafer-studio/tree/main/releases)

## 啟動

在 Windows 解壓縮下載檔，雙擊 **Start SRAM Wafer Studio.cmd** 即可開啟桌面視窗。需要 Python 3.11 以上（加入 PATH）和 Microsoft Edge WebView2 Runtime。初次啟動若缺少套件，啟動程式會在專案內建立 Python 環境並安裝依賴。

也可執行 `python -m pip install -r requirements.txt` 後執行 `python app.py` 開啟同一個桌面視窗。所有操作均在本機處理，無需開啟瀏覽器、輸入 IP 或使用連接埠。

`examples/sim128/` 包含 WT1～WT3 的合成 ASC 和對應的 TNO 設定，可在介面選「載入 128 芯片範例」試跑。

## 操作

1. **匯入 ASC** 選同一片 wafer 的 1～3 個檔案。優先採用檔名中的 WT1／WT2／WT3，只有 WT3 時就顯示 WT3。所有檔名皆無 WT 時按 STEP 補編號，混合命名無法唯一對應時請補齊檔名。需要試跑時可使用「載入 128 芯片範例」。
2. **Wafer Maps** 可切換已匯入的 WT 和 Pattern。Wafer 的 X/Y 分布區維持等寬高。點選 Chip 可展開 16 × 16 BLK 矩陣，窄視窗可水平捲動。每格依實際 WT 顯示狀態色帶，再點 BLK 可切換 Pattern，查看 90% 累積曲線、依 Func. 分色的電壓 FBC 分布和地址匹配。Function 匹配顯示 Config 電壓。 選定 Pattern 後可匯出向量 PDF、300 dpi PNG 或含可編輯圖表、數據和地址匹配的 Excel。選擇目的地後，檔案寫入其中的 `Analysis_YYYYMMDD/`。
3. **資料核對** 可切換 Fail Address、BLK_FBC_Comparison、Missing BLK Address 和 Chip Vmin。Chip 選取連動資料核對範圍。
4. **匯出報表** 可選「完整 Excel 報表（原版版面）」匯出 Config、Fail Address、FBC 對照、含導覽連結的 Wafer Maps 及選定 Chip 的 256 BLK 分布。也可分別匯出 Address、FBC、Cat Map，或輸出整組圖片寬 37 公分的 PowerPoint。
5. **批次匯出** 可選不同 Lot／Wafer。依完整 LOT 和 WNO 分組；檔名使用前六碼 LOT、Wafer、檔名 WT 標記、ASC 版本及匯出日期。每片只輸出 Cat Wafer Map、Fail Address、Fail BLK 到來源資料夾下的 Address_日期。
6. **TNO 設定** 內的完整版和批次版各自儲存，初始值來自已發佈的 v13.1 與 v1.6。可匯入含 Config 工作表的 Excel 或 CSV，並調整列順序。

## 判定

- Fail BLK 取 Pattern 終點正值 FBC。Hard Fail、前序 WT Function fail 及同 WT 前序 Pattern 終點 fail 的 BLK 會排除。
- Address Coverage 使用同 WT／Chip／BLK 在 Pattern 區間的 Address 聯集，並保留終點 FBC 和地址差。
- FBC0 取首次正值 FBC 前一個電壓。FBC1～10 取首次達門檻的當站。FBC90% 取第一次達該 BLK 在 Pattern 內最高 FBC 的 90% 的站點。累積曲線按 Config 順序以截至當站的最高 FBC 除以整段峰值；電壓分布保留各站原始 FBC。
- Chip Vmin 取有效 BLK 中的最高 Vmin。Tail 基於每顆 Chip／WT 正值峰值 FBC 的 Q3 + 1.5 × IQR，至少四個完整樣本才套用。缺資料會在狀態和明細中保留。
- 「核對既有 VBA 結果」可讀取同一本舊 .xlsm 內的 Config、Fail Address、FBC by BLK 和 Import Index，驗證來源後重新核對。桌面視窗負責互動，輸出的 .xlsx 報表是靜態資料。
