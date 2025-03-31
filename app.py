import asyncio
import os
import requests
import streamlit as st
from openpyxl import Workbook
from playwright.async_api import async_playwright
import tempfile
from bs4 import BeautifulSoup
import subprocess

def ensure_playwright_browser():
    """確保 Playwright 的 Chromium 瀏覽器已安裝"""
    browser_path = os.path.expanduser("~/.cache/ms-playwright/chromium-1097/chrome-linux/chrome")
    if not os.path.exists(browser_path):
        print("安裝 Playwright 瀏覽器...")
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            print("Playwright 瀏覽器安裝成功")
        except Exception as e:
            print(f"安裝 Playwright 瀏覽器失敗: {e}")
            try:
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
                print("使用 python -m 安裝 Playwright 瀏覽器成功")
            except Exception as e:
                print(f"使用 python -m 安裝 Playwright 瀏覽器失敗: {e}")

# 啟動時安裝瀏覽器
ensure_playwright_browser()

# 設定頁面配置
st.set_page_config(
    page_title="裁判書查詢與下載工具",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 設定下載資料夾
DOWNLOAD_FOLDER = "./downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

async def fetch_judgments(keyword, max_pages=25, page_size=20):
    """非同步獲取裁判書資料（包含分頁功能）"""
    # 創建佔位符以顯示進度
    progress_placeholder = st.progress(0)
    status_placeholder = st.empty()
    status_placeholder.text("正在準備查詢...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # 開啟法院查詢頁面
            status_placeholder.text("正在連接法院判決網站...")
            await page.goto("https://judgment.judicial.gov.tw/FJUD/default.aspx", timeout=60000)
            
            # 輸入關鍵字
            status_placeholder.text(f"輸入搜尋關鍵字: {keyword}")
            await page.fill("#txtKW", keyword)
            
            # 點擊查詢按鈕
            status_placeholder.text("送出查詢，請稍候...")
            await page.click("#btnSimpleQry")
            
            # 等待查詢結果頁面載入
            await asyncio.sleep(5)
            
            # 查找 iframe
            frame = None
            iframe = await page.query_selector("#iframe-data")
            if iframe:
                frame = page.frame(name="iframe-data") or page.frame(id="iframe-data")
            
            if not frame:
                for f in page.frames:
                    if "FJUD/data.aspx" in f.url:
                        frame = f
                        break
            
            if not frame:
                frame_locator = page.frame_locator("iframe").first
                if await frame_locator.count() > 0:
                    frame = await frame_locator.frame()
            
            if not frame:
                status_placeholder.text("尋找判決清單框架...")
                judgment_links = await page.query_selector_all("a[id*='hlTitle']")
                if len(judgment_links) > 0:
                    judgment_urls = []
                    for link in judgment_links:
                        href = await link.get_attribute("href")
                        text = await link.inner_text()
                        judgment_urls.append((text, href))
                    progress_placeholder.progress(1.0)  # 完成進度條
                    status_placeholder.text(f"找到 {len(judgment_urls)} 筆判決")
                    return judgment_urls, 1  # 只有一頁
                else:
                    progress_placeholder.progress(1.0)  # 完成進度條
                    status_placeholder.text("未找到任何判決")
                    return [], 0
            
            # 等待判決連結載入
            status_placeholder.text("等待判決清單載入...")
            await frame.wait_for_selector("a[id*='hlTitle']", timeout=20000)
            
            # 收集所有頁面的判決
            all_judgments = []
            current_page = 1
            
            while current_page <= max_pages:
                # 擷取當前頁面的判決
                elements = await frame.query_selector_all("a[id*='hlTitle']")
                page_judgments = []
                
                for el in elements:
                    url = await el.get_attribute("href")
                    text = await el.inner_text()
                    page_judgments.append((text, url))
                
                all_judgments.extend(page_judgments)
                
                # 更新進度條而不是使用 st.info
                progress_percentage = current_page / max_pages
                progress_placeholder.progress(progress_percentage)
                status_placeholder.text(f"進度: {current_page}/{max_pages} 頁 | 當前頁: {len(page_judgments)}筆 | 總計: {len(all_judgments)}筆")
                
                # 如果需要下載當前頁面的 PDF
                if len(page_judgments) > 0:
                    # 可以在這裡添加下載邏輯
                    pass
                
                # 如果還有下一頁，則切換頁面
                if current_page < max_pages:
                    # 使用 hlNext 連結進行下一頁
                    try:
                        next_link = await frame.query_selector("a#hlNext")
                        if next_link:
                            # 保存當前頁面的某些特徵以確認頁面確實變化了
                            current_titles = await frame.eval_on_selector_all("a[id*='hlTitle']", "els => els.map(el => el.textContent)")
                            
                            # 點擊下一頁
                            await next_link.click()
                            status_placeholder.text(f"正在切換到第 {current_page + 1} 頁...")
                            
                            # 等待頁面載入並確認頁面確實變化了
                            await asyncio.sleep(3)
                            await frame.wait_for_selector("a[id*='hlTitle']", timeout=20000)
                            
                            # 確認頁面已經變化
                            max_retries = 3
                            for retry in range(max_retries):
                                new_titles = await frame.eval_on_selector_all("a[id*='hlTitle']", "els => els.map(el => el.textContent)")
                                if new_titles != current_titles:
                                    # 頁面已經變化，跳出循環
                                    break
                                
                                # 如果頁面沒有變化，等待更長時間後再嘗試
                                if retry < max_retries - 1:
                                    status_placeholder.text(f"等待頁面載入... (嘗試 {retry + 1}/{max_retries})")
                                    await asyncio.sleep(2)
                                else:
                                    status_placeholder.warning("頁面可能未正確變化，繼續處理...")
                        else:
                            status_placeholder.text("已到最後一頁")
                            break
                    except Exception as e:
                        status_placeholder.text(f"切換頁面時發生錯誤: {e}")
                        # 嘗試重新獲取框架
                        try:
                            for f in page.frames:
                                if "FJUD/data.aspx" in f.url:
                                    frame = f
                                    break
                            await asyncio.sleep(3)
                            continue
                        except:
                            break
                
                current_page += 1
            
            # 獲取總頁數信息
            total_pages = await get_total_pages(frame)
            
            # 完成進度條
            progress_placeholder.progress(1.0)
            status_placeholder.text(f"完成查詢 - 共 {len(all_judgments)} 筆判決 ({current_page-1}/{total_pages} 頁)")
            
            return all_judgments, total_pages
            
        except Exception as e:
            progress_placeholder.progress(1.0)  # 完成進度條
            status_placeholder.text(f"查詢過程中發生錯誤: {e}")
            return [], 0
        finally:
            await browser.close()

async def get_total_pages(frame):
    """獲取總頁數"""
    try:
        # 檢查是否有下一頁按鈕
        next_link = await frame.query_selector("a#hlNext")
        if not next_link:
            # 如果沒有下一頁按鈕，可能只有一頁
            return 1
        
        # 嘗試使用較短的超時時間來獲取分頁信息
        try:
            # 先嘗試從分頁文字獲取
            page_info = await frame.inner_text("#divPager", timeout=5000)
            if "共" in page_info and "頁" in page_info:
                parts = page_info.split("共")[1].split("頁")[0].strip()
                return int(parts)
        except:
            # 如果獲取分頁文字失敗，繼續嘗試其他方法
            pass
        
        # 嘗試從頁面選擇器獲取
        try:
            select_html = await frame.inner_html("#ddlPage", timeout=5000)
            soup = BeautifulSoup(select_html, 'html.parser')
            select = soup.find('select', {'id': 'ddlPage'})
            
            if select:
                options = select.find_all('option')
                return len(options)
        except:
            # 如果獲取選擇器失敗，繼續嘗試其他方法
            pass
        
        # 如果上述方法都失敗，但有下一頁按鈕，至少有2頁
        return 2
        
    except Exception as e:
        # 不顯示警告，因為可能會干擾用戶體驗
        # st.warning(f"獲取總頁數失敗: {e}")
        return 1  # 如果獲取失敗，假設只有一頁

async def batch_download_pdfs(judgment_batch, download_folder, progress_bar=None, status_text=None):
    """批量下載一批判決書PDF"""
    downloaded_files = []
    errors = []
    
    for i, (name, url) in enumerate(judgment_batch):
        if status_text:
            status_text.text(f"正在下載第 {i+1}/{len(judgment_batch)} 個: {name}")
        if progress_bar:
            progress_bar.progress((i+1)/len(judgment_batch))
        
        file_path, error = await download_judgment_pdf(url, download_folder)
        if file_path:
            downloaded_files.append(file_path)
        else:
            errors.append(f"{name}: {error}")
    
    return downloaded_files, errors

async def download_judgment_pdf(url, download_folder):
    """下載單個裁判書PDF"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            base_url = "https://judgment.judicial.gov.tw/FJUD/"
            full_url = url if url.startswith("http") else base_url + url
            
            await page.goto(full_url, timeout=30000)
            await page.wait_for_selector("#jud", timeout=30000)
            
            # 擷取裁判字號
            rows = await page.query_selector_all("#jud .row")
            case_number = "unknown_case"
            
            for row in rows:
                text = await row.inner_text()
                if "裁判字號" in text:
                    try:
                        cols = await row.query_selector_all(".col-td")
                        if cols and len(cols) > 0:
                            case_number = await cols[0].inner_text()
                            break
                    except:
                        continue
            
            # 清理檔名
            safe_name = "".join(c for c in case_number if c.isalnum() or c in " ，年第字號").strip()
            if not safe_name:
                safe_name = "unknown_case"
            safe_name += ".pdf"
            
            # 擷取 PDF 連結
            pdf_link = await page.query_selector("#hlExportPDF")
            if not pdf_link:
                return None, "找不到PDF下載連結"
                
            pdf_url = await pdf_link.get_attribute("href")
            if pdf_url.startswith("/"):
                pdf_url = "https://judgment.judicial.gov.tw" + pdf_url
            
            # 下載 PDF
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(pdf_url, headers=headers)
            
            if response.status_code == 200:
                file_path = os.path.join(download_folder, safe_name)
                with open(file_path, "wb") as f:
                    f.write(response.content)
                return file_path, None
            else:
                return None, f"PDF下載失敗，狀態碼: {response.status_code}"
                
        except Exception as e:
            return None, f"下載過程中發生錯誤: {e}"
        finally:
            await browser.close()

def create_excel(judgments):
    """建立Excel檔案"""
    wb = Workbook()
    ws = wb.active
    ws.append(["判決名稱", "判決網址"])
    
    for name, url in judgments:
        ws.append([name, url])
    
    # 儲存到臨時檔案
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(temp_file.name)
    temp_file.close()
    
    return temp_file.name

def main():
    st.title("⚖️ 裁判書查詢與下載工具")
    st.markdown("""
        本工具可查詢司法院裁判書系統，並下載相關裁判書PDF檔案。
        請輸入查詢關鍵字，然後點擊「查詢」按鈕。
    """)
    
    # 初始化 session state
    if "search_clicked" not in st.session_state:
        st.session_state.search_clicked = False
    if "judgments" not in st.session_state:
        st.session_state.judgments = []
    if "excel_file" not in st.session_state:
        st.session_state.excel_file = None
    if "download_all" not in st.session_state:
        st.session_state.download_all = False
    if "batch_download" not in st.session_state:
        st.session_state.batch_download = False
    if "total_pages" not in st.session_state:
        st.session_state.total_pages = 1
    if "download_progress" not in st.session_state:
        st.session_state.download_progress = 0
    
    # 側邊欄設定
    with st.sidebar:
        st.header("查詢設定")
        keyword = st.text_input(
            "查詢關鍵字", 
            value="(法院+管轄)&公證處",
            help="使用進階查詢語法，例如：(保險公司&執行命令)&最高"
        )
        
        max_pages = st.number_input(
            "查詢頁數", 
            min_value=1, 
            max_value=25, 
            value=1,
            help="設定要查詢的頁數（每頁約20筆結果，最多25頁）"
        )
        
        page_size = st.number_input(
            "每頁顯示數量", 
            min_value=10, 
            max_value=50, 
            value=20,
            help="設定每頁顯示的查詢結果數量"
        )
        
        auto_download = st.checkbox(
            "自動下載每頁PDF",
            value=False,
            help="勾選後將在爬取每頁後自動下載該頁的PDF文件"
        )
        
        if st.button("開始查詢"):
            st.session_state.search_clicked = True
            st.session_state.download_all = False
            st.session_state.judgments = []
            st.session_state.excel_file = None
    
    # 主內容區
    if st.session_state.get("search_clicked", False):
        search_result_container = st.container()
        with search_result_container:
            with st.spinner("正在查詢裁判書，請稍候..."):
                judgments, total_pages = asyncio.run(fetch_judgments(keyword, max_pages, page_size))
                st.session_state.total_pages = total_pages
                
                if not judgments:
                    st.warning("沒有找到符合條件的裁判書，請嘗試其他關鍵字。")
                    st.session_state.search_clicked = False
                    st.stop()
                
                st.session_state.judgments = judgments
            
            # 顯示結果
            result_count = len(judgments)
            st.success(f"找到 {result_count} 筆裁判書結果")
            
            # 建立Excel檔案
            excel_file = create_excel(judgments)
            st.session_state.excel_file = excel_file
            
            # 分頁顯示結果
            results_container = st.container()
            with results_container:
                st.subheader("查詢結果")
                
                # 計算結果的總頁數
                items_per_page = page_size
                total_items = len(judgments)
                total_result_pages = (total_items + items_per_page - 1) // items_per_page
                
                # 選擇當前顯示的頁碼
                col1, col2 = st.columns([3, 1])
                with col1:
                    # 處理只有一頁的情況
                    if total_result_pages <= 1:
                        st.info("只有一頁結果")
                        current_display_page = 1
                    else:
                        current_display_page = st.slider(
                            "查詢結果頁碼", 
                            min_value=1, 
                            max_value=total_result_pages,
                            value=1
                        )
                
                # 顯示當前頁的判決
                start_idx = (current_display_page - 1) * items_per_page
                end_idx = min(start_idx + items_per_page, total_items)
                
                with col2:
                    st.info(f"顯示第 {start_idx+1}-{end_idx} 筆（共 {total_items} 筆）")
                
                # 顯示當前頁的判決列表
                current_page_judgments = judgments[start_idx:end_idx]
                
                # 批量下載當前頁的按鈕
                if st.button(f"下載當前頁 PDF（{len(current_page_judgments)} 筆）"):
                    st.session_state.batch_download = True
                    st.session_state.batch_judgments = current_page_judgments
                
                # 顯示判決列表
                for idx, (name, url) in enumerate(current_page_judgments, start_idx + 1):
                    with st.expander(f"{idx}. {name}"):
                        base_url = "https://judgment.judicial.gov.tw/FJUD/"
                        full_url = url if url.startswith("http") else base_url + url
                        st.markdown(f"**裁判書網址:** [點擊查看]({full_url})")
                        
                        # 單個下載按鈕
                        if st.button(f"下載 PDF {idx}", key=f"single_{idx}"):
                            with st.spinner(f"正在下載 {name}..."):
                                file_path, error = asyncio.run(
                                    download_judgment_pdf(url, DOWNLOAD_FOLDER))
                                
                                if file_path:
                                    with open(file_path, "rb") as f:
                                        st.download_button(
                                            label="點擊下載PDF",
                                            data=f,
                                            file_name=os.path.basename(file_path),
                                            mime="application/pdf"
                                        )
                                    st.success("下載完成！")
                                else:
                                    st.error(f"下載失敗: {error}")
            
            # 批量下載選項
            st.subheader("批量下載選項")
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("下載所有查詢結果 PDF (ZIP)"):
                    st.session_state.download_all = True
            
            with col2:
                # Excel下載
                st.download_button(
                    label="下載查詢結果清單 (Excel)",
                    data=open(st.session_state.excel_file, "rb"),
                    file_name="裁判書查詢結果.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    
    # 處理批量下載當前頁
    if st.session_state.get("batch_download", False) and st.session_state.get("batch_judgments"):
        judgments_batch = st.session_state.batch_judgments
        total = len(judgments_batch)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text(f"準備下載 {total} 筆判決文件...")
        
        # 建立臨時資料夾
        temp_dir = tempfile.mkdtemp()
        
        with st.spinner(f"正在下載 {total} 筆判決..."):
            downloaded_files, errors = asyncio.run(
                batch_download_pdfs(judgments_batch, temp_dir, progress_bar, status_text)
            )
        
        # 建立ZIP檔案
        if downloaded_files:
            import zipfile
            import datetime
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"裁判書合集_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in downloaded_files:
                    zipf.write(file, os.path.basename(file))
            
            # 提供下載
            with open(zip_path, "rb") as f:
                st.download_button(
                    label=f"點擊下載 {len(downloaded_files)} 筆裁判書 (ZIP)",
                    data=f,
                    file_name=zip_filename,
                    mime="application/zip"
                )
            
            st.success(f"已成功下載 {len(downloaded_files)}/{total} 個裁判書")
            
            if errors:
                st.warning("部分裁判書下載失敗:")
                for error in errors:
                    st.error(error)
        else:
            st.error("沒有任何裁判書下載成功")
        
        # 清理
        for file in downloaded_files:
            if os.path.exists(file):
                os.remove(file)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        os.rmdir(temp_dir)
        
        st.session_state.batch_download = False
        st.session_state.batch_judgments = None
    
    # 處理下載所有結果
    if st.session_state.get("download_all", False) and st.session_state.get("judgments"):
        judgments = st.session_state.judgments
        total = len(judgments)
        
        # 進度和狀態顯示
        download_progress = st.progress(0)
        download_status = st.empty()
        download_status.text(f"準備下載 {total} 筆判決文件...")
        
        # 建立臨時資料夾
        temp_dir = tempfile.mkdtemp()
        downloaded_files = []
        download_errors = []
        
        # 使用我們的批量下載函數
        with st.spinner(f"正在下載全部 {total} 筆判決..."):
            downloaded_files, download_errors = asyncio.run(
                batch_download_pdfs(judgments, temp_dir, download_progress, download_status)
            )
        
        # 建立ZIP檔案
        if downloaded_files:
            import zipfile
            import datetime
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"裁判書合集_全部_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in downloaded_files:
                    zipf.write(file, os.path.basename(file))
            
            # 提供下載
            with open(zip_path, "rb") as f:
                st.download_button(
                    label=f"點擊下載所有裁判書 (ZIP)",
                    data=f,
                    file_name=zip_filename,
                    mime="application/zip"
                )
            
            st.success(f"已成功下載 {len(downloaded_files)}/{total} 個裁判書")
            
            if download_errors:
                st.warning("部分裁判書下載失敗:")
                for error in download_errors:
                    st.error(error)
        else:
            st.error("沒有任何裁判書下載成功")
        
        # 清理
        for file in downloaded_files:
            if os.path.exists(file):
                os.remove(file)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        os.rmdir(temp_dir)
        
        st.session_state.download_all = False

if __name__ == "__main__":
    main()