# SRAM Analysis Tool 發佈規則

- 此專案是 Python 桌面版。GitHub 發佈位置為公開的 `QooLien/sram-wafer-studio`。
- 壓縮檔固定放在 `releases/`，名稱為 `SRAM Analysis Tool vX.Y.Z.zip`。此命名系列的第一版為 `v1.0`。
- 從 v1.7.1 起採三段式版號 Major.Minor.Patch；小幅更新依序使用 `1.7.1 → 1.7.2 → 1.7.3`，不覆蓋舊版 ZIP。
- 更新 `VERSION` 和 `releases/README.md` 的最新版下載路徑。提交來源後執行 `python tools/package_release.py`，驗證解壓縮後可執行。將新版 ZIP 和來源推送至 GitHub，並以 `tool-vX.Y.Z` 建立對應 Release。
- `releases/` 保留每一版 ZIP，不覆蓋舊版；亦可由 GitHub Release 或 Git 歷史取得。ZIP 收錄啟動檔、程式、預設配置、說明和合成範例。個人設定、虛擬環境、測試報表與正式 ASC 不在發佈清單。
