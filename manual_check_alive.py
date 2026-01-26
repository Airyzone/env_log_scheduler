import logging
import sys
import os

# 確保當前目錄在 path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from check_alive_task import run_check_alive

if __name__ == "__main__":
    # 強制設定 Logging 輸出到螢幕 (Standard Output)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True 
    )
    
    logger = logging.getLogger("manual_trigger")
    logger.info("正在手動執行 check_alive 檢查...")
    logger.info("這將會立即檢查所有裝置狀態，並顯示執行結果摘要。")
    
    try:
        run_check_alive()
        logger.info("--------------------------------------------------")
        logger.info("手動執行完成！請查看上方的 'Check Alive Summary' 確認結果。")
    except Exception as e:
        logger.error(f"執行失敗: {e}", exc_info=True)
