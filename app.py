import asyncio
import os
import requests
import streamlit as st
from openpyxl import Workbook
from playwright.async_api import async_playwright
import tempfile
from bs4 import BeautifulSoup
import subprocess
import zipfile
import datetime
import random
import pandas as pd
from contextlib import asynccontextmanager

ua_list = []

with open('ua_list.txt', 'r') as f:
    ua_list = f.readlines()

ua_list = [ua.strip() for ua in ua_list]

def ensure_playwright_browser():
    """確保 Playwright 的 Chromium 瀏覽器已安裝"""
    browser_path = os.path.expanduser("~/.cache/ms-playwright/chromium-1097/chrome-linux/chrome")
    if not os.path.exists(browser_path):
        print("安裝 Playwright 瀏覽器...")
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            try:
                subprocess.run(["playwright", "install-deps", "chromium"], check=False)
            except:
                pass
            print("Playwright 瀏覽器安裝成功")
        except Exception as e:
            print(f"安裝 Playwright 瀏覽器失敗: {e}")
            try:
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
                try:
                    subprocess.run(["python", "-m", "playwright", "install-deps", "chromium"], check=False)
                except:
                    pass
                print("使用 python -m 安裝 Playwright 瀏覽器成功")
            except Exception as e:
                print(f"使用 python -m 安裝 Playwright 瀏覽器失敗: {e}")

ensure_playwright_browser()

st.set_page_config(
    page_title="裁判書查詢與下載工具",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

DOWNLOAD_FOLDER = "./downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@asynccontextmanager
async def get_browser_context():
    """瀏覽器上下文管理器"""
    browser = None
    context = None
    try:
        browser = await async_playwright().start()
        browser = await browser.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-accelerated-2d-canvas',
                '--no-zygote',
                '--single-process'
            ]
        )
        ua = random.choice(ua_list)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=ua
        )
        yield context
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()

async def get_judgment_details(context, url):
    """獲取裁判詳細資訊（字號、日期、案由）"""
    page = None
    try:
        page = await context.new_page()
        base_url = "https://judgment.judicial.gov.tw/FJUD/"
        full_url = url if url.startswith("http") else base_url + url
        
        await page.goto(full_url, timeout=30000)
        await page.wait_for_selector(".row", timeout=20000)
        
        rows = await page.query_selector_all(".row")
        case_number = "未找到裁判字號"
        case_date = "未找到裁判日期"
        case_reason = "未找到案由"
        
        for row in rows:
            text = await row.inner_text()
            if "裁判字號：" in text:
                try:
                    cols = await row.query_selector_all(".col-td")
                    if cols and len(cols) > 0:
                        case_number = await cols[0].inner_text()
                        case_number = case_number.strip()
                except:
                    continue
            elif "裁判日期：" in text:
                try:
                    cols = await row.query_selector_all(".col-td")
                    if cols and len(cols) > 0:
                        case_date = await cols[0].inner_text()
                        case_date = case_date.strip()
                except:
                    continue
            elif "裁判案由：" in text:
                try:
                    cols = await row.query_selector_all(".col-td")
                    if cols and len(cols) > 0:
                        case_reason = await cols[0].inner_text()
                        case_reason = case_reason.strip()
                except:
                    continue
        
        return {
            "case_number": case_number,
            "case_date": case_date,
            "case_reason": case_reason
        }
    except Exception as e:
        print(f"獲取裁判詳細資訊失敗: {e}")
        return {
            "case_number": "獲取失敗",
            "case_date": "獲取失敗",
            "case_reason": "獲取失敗"
        }
    finally:
        if page:
            await page.close()

async def fetch_judgments(context, keyword, max_pages=25):
    """非同步獲取裁判書資料"""
    progress_placeholder = st.progress(0)
    status_placeholder = st.empty()
    status_placeholder.text("正在準備查詢...")
    
    try:
        page = await context.new_page()
        
        status_placeholder.text("正在連接法院判決網站...")
        await page.goto("https://judgment.judicial.gov.tw/FJUD/default.aspx", timeout=60000)
        
        status_placeholder.text(f"輸入搜尋關鍵字: {keyword}")
        await page.fill("#txtKW", keyword)
        
        status_placeholder.text("送出查詢，請稍候...")
        await page.click("#btnSimpleQry")
        
        await asyncio.sleep(5)
        
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
                    details = await get_judgment_details(context, href)
                    judgment_urls.append({
                        "title": text,
                        "url": href,
                        "case_number": details["case_number"],
                        "case_date": details["case_date"],
                        "case_reason": details["case_reason"]
                    })
                progress_placeholder.progress(1.0)
                status_placeholder.text(f"找到 {len(judgment_urls)} 筆判決")
                return judgment_urls, 1
            else:
                progress_placeholder.progress(1.0)
                status_placeholder.text("未找到任何判決")
                return [], 0
        
        status_placeholder.text("等待判決清單載入...")
        await frame.wait_for_selector("a[id*='hlTitle']", timeout=20000)
        
        all_judgments = []
        current_page = 1
        
        while current_page <= max_pages:
            elements = await frame.query_selector_all("a[id*='hlTitle']")
            page_judgments = []
            
            for el in elements:
                url = await el.get_attribute("href")
                text = await el.inner_text()
                details = await get_judgment_details(context, url)
                page_judgments.append({
                    "title": text,
                    "url": url,
                    "case_number": details["case_number"],
                    "case_date": details["case_date"],
                    "case_reason": details["case_reason"]
                })
            
            all_judgments.extend(page_judgments)
            
            progress_percentage = current_page / max_pages
            progress_placeholder.progress(progress_percentage)
            status_placeholder.text(f"進度: {current_page}/{max_pages} 頁 | 當前頁: {len(page_judgments)}筆 | 總計: {len(all_judgments)}筆")
            
            if current_page < max_pages:
                try:
                    next_link = await frame.query_selector("a#hlNext")
                    if next_link:
                        current_titles = await frame.eval_on_selector_all("a[id*='hlTitle']", "els => els.map(el => el.textContent)")
                        
                        await next_link.click()
                        status_placeholder.text(f"正在切換到第 {current_page + 1} 頁...")
                        
                        await asyncio.sleep(3)
                        await frame.wait_for_selector("a[id*='hlTitle']", timeout=20000)
                        
                        max_retries = 3
                        for retry in range(max_retries):
                            new_titles = await frame.eval_on_selector_all("a[id*='hlTitle']", "els => els.map(el => el.textContent)")
                            if new_titles != current_titles:
                                break
                            
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
        
        total_pages = await get_total_pages(frame)
        
        progress_placeholder.progress(1.0)
        status_placeholder.text(f"完成查詢 - 共 {len(all_judgments)} 筆判決 ({current_page-1}/{total_pages} 頁)")
        
        return all_judgments, total_pages
        
    except Exception as e:
        progress_placeholder.progress(1.0)
        status_placeholder.text(f"查詢過程中發生錯誤: {e}")
        return [], 0
    finally:
        if page:
            await page.close()

async def get_total_pages(frame):
    """獲取總頁數"""
    try:
        next_link = await frame.query_selector("a#hlNext")
        if not next_link:
            return 1
        
        try:
            page_info = await frame.inner_text("#divPager", timeout=5000)
            if "共" in page_info and "頁" in page_info:
                parts = page_info.split("共")[1].split("頁")[0].strip()
                return int(parts)
        except:
            pass
        
        try:
            select_html = await frame.inner_html("#ddlPage", timeout=5000)
            soup = BeautifulSoup(select_html, 'html.parser')
            select = soup.find('select', {'id': 'ddlPage'})
            
            if select:
                options = select.find_all('option')
                return len(options)
        except:
            pass
        
        return 2
        
    except Exception as e:
        return 1

async def batch_download_pdfs(context, judgment_batch, download_folder, progress_bar=None, status_text=None):
    """批量下載一批判決書PDF"""
    downloaded_files = []
    errors = []
    
    for i, judgment in enumerate(judgment_batch):
        name = judgment["case_number"]
        url = judgment["url"]
        
        if status_text:
            status_text.text(f"正在下載第 {i+1}/{len(judgment_batch)} 個: {name}")
        if progress_bar:
            progress_bar.progress((i+1)/len(judgment_batch))
        
        file_path, error = await download_judgment_pdf(context, url, download_folder)
        if file_path:
            downloaded_files.append(file_path)
        else:
            errors.append(f"{name}: {error}")
    
    return downloaded_files, errors

async def download_judgment_pdf(context, url, download_folder):
    """下載單個裁判書PDF"""
    page = None
    try:
        page = await context.new_page()
        base_url = "https://judgment.judicial.gov.tw/FJUD/"
        full_url = url if url.startswith("http") else base_url + url
        
        await page.goto(full_url, timeout=30000)
        await page.wait_for_selector("#jud", timeout=30000)
        
        # 獲取裁判字號和案由
        rows = await page.query_selector_all("#jud .row")
        case_number = "unknown_case"
        case_reason = "unknown_reason"
        
        for row in rows:
            text = await row.inner_text()
            if "裁判字號：" in text:
                try:
                    cols = await row.query_selector_all(".col-td")
                    if cols and len(cols) > 0:
                        case_number = await cols[0].inner_text()
                        case_number = case_number.strip()
                except:
                    continue
            elif "裁判案由：" in text:
                try:
                    cols = await row.query_selector_all(".col-td")
                    if cols and len(cols) > 0:
                        case_reason = await cols[0].inner_text()
                        case_reason = case_reason.strip()
                except:
                    continue
        
        # 清理檔名中的非法字元
        def clean_filename(text):
            keep_chars = (' ', '_', '-', '，', '。', '、', '：', '；', '？', '！', 
                         '「', '」', '『', '』', '（', '）', '【', '】', '《', '》')
            return "".join(c for c in text if c.isalnum() or c in keep_chars).strip()
        
        case_number_clean = clean_filename(case_number)
        case_reason_clean = clean_filename(case_reason)
        
        # 組合檔名
        safe_name = f"{case_number_clean}_{case_reason_clean}.pdf"
        
        # 如果檔名過長，適當縮短
        if len(safe_name) > 200:
            safe_name = f"{case_number_clean[:150]}_{case_reason_clean[:50]}.pdf"
        
        # 擷取 PDF 連結
        pdf_link = await page.query_selector("#hlExportPDF")
        if not pdf_link:
            return None, "找不到PDF下載連結"
            
        pdf_url = await pdf_link.get_attribute("href")
        if pdf_url.startswith("/"):
            pdf_url = "https://judgment.judicial.gov.tw" + pdf_url
        
        # 下載 PDF
        headers = {
            "User-Agent": random.choice(ua_list)
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
        if page:
            await page.close()

def create_excel(judgments):
    """建立Excel檔案"""
    wb = Workbook()
    ws = wb.active
    ws.append(["序號", "裁判字號", "裁判日期", "裁判案由", "判決網址"])
    
    for idx, judgment in enumerate(judgments, 1):
        ws.append([
            idx,
            judgment["case_number"],
            judgment["case_date"],
            judgment["case_reason"],
            judgment["url"]
        ])
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(temp_file.name)
    temp_file.close()
    
    return temp_file.name

with st.sidebar:
    st.header("關於本工具")
    st.markdown("""
    本工具為**司法院裁判書查詢與批量下載工具**，
    方便您快速搜尋與下載公開裁判書 PDF。
    """)
    st.header("使用教學")
    st.markdown("""
    1. 輸入查詢關鍵字  
    2. 選擇查詢頁數 (最多僅能獲取 25頁 / 500 筆資料)  
    3. 點擊「開始查詢」  
    4. 可下載 Excel 或批量下載 PDF
    """)

    st.header("⚠️ 檢索字詞說明事項")
    st.markdown("""
    有關檢索字詞說明，請參見[司法院裁判書系統](https://judgment.judicial.gov.tw/FJUD/default.aspx)檢索字詞輔助說明。進入網頁後於搜尋欄點擊最右邊的「檢索字詞輔助說明」即可參閱。
    """)

async def main_async():
    """非同步主函數"""
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
    if "search_completed" not in st.session_state:
        st.session_state.search_completed = False
    if "current_display_page" not in st.session_state:
        st.session_state.current_display_page = 1
    
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

    if "search_clicked" not in st.session_state:
        st.session_state.search_clicked = False

    if st.button("開始查詢"):
        st.session_state.search_clicked = True
        st.session_state.search_completed = False
        st.session_state.download_all = False
        st.session_state.judgments = []
        st.session_state.excel_file = None
    
    async with get_browser_context() as context:
        if st.session_state.get("search_clicked", False):
            search_result_container = st.container()
            with search_result_container:
                if not st.session_state.get("search_completed", False):
                    with st.spinner("正在查詢裁判書，請稍候..."):
                        judgments, total_pages = await fetch_judgments(context, keyword, max_pages)
                        st.session_state.total_pages = total_pages
                        st.session_state.current_display_page = 1  # 重置為第一頁
                        
                        if not judgments:
                            st.warning("沒有找到符合條件的裁判書，請嘗試其他關鍵字。")
                            st.session_state.search_clicked = False
                            return
                        
                        st.session_state.judgments = judgments
                        st.session_state.search_completed = True
                
                result_count = len(st.session_state.judgments)
                st.success(f"找到 {result_count} 筆裁判書結果 (共 {st.session_state.total_pages} 頁)")
                
                excel_file = create_excel(st.session_state.judgments)
                st.session_state.excel_file = excel_file
                
                results_container = st.container()
                with results_container:
                    st.subheader("查詢結果")
                    
                    items_per_page = 20
                    total_items = len(st.session_state.judgments)
                    total_result_pages = (total_items + items_per_page - 1) // items_per_page
                    
                    # 顯示當前頁碼和總頁數
                    st.write(f"當前頁碼: {st.session_state.current_display_page}/{total_result_pages}")
                    
                    # 分頁控制按鈕
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        if st.button("第一頁", disabled=st.session_state.current_display_page == 1):
                            st.session_state.current_display_page = 1
                    with col2:
                        if st.button("上一頁", disabled=st.session_state.current_display_page == 1):
                            st.session_state.current_display_page -= 1
                    with col3:
                        st.write("")  # 空白列用於間隔
                    with col4:
                        if st.button("下一頁", disabled=st.session_state.current_display_page == total_result_pages):
                            st.session_state.current_display_page += 1
                    with col5:
                        if st.button("最後一頁", disabled=st.session_state.current_display_page == total_result_pages):
                            st.session_state.current_display_page = total_result_pages
                    
                    # 顯示當前頁的判決
                    start_idx = (st.session_state.current_display_page - 1) * items_per_page
                    end_idx = min(start_idx + items_per_page, total_items)
                    
                    st.info(f"顯示第 {start_idx+1}-{end_idx} 筆（共 {total_items} 筆）")
                    
                    current_page_judgments = st.session_state.judgments[start_idx:end_idx]
                    
                    table_data = []
                    for idx, judgment in enumerate(current_page_judgments, start_idx + 1):
                        table_data.append({
                            "序號": idx,
                            "裁判字號": judgment["case_number"],
                            "裁判日期": judgment["case_date"],
                            "裁判案由": judgment["case_reason"]
                        })
                    
                    df = pd.DataFrame(table_data)
                    df = df.reset_index(drop=True)
                    st.table(df)
                    
                    if st.button(f"下載當前頁 PDF（{len(current_page_judgments)} 筆）"):
                        st.session_state.batch_download = True
                        st.session_state.batch_judgments = current_page_judgments
                
                st.subheader("批量下載選項")
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("下載所有查詢結果 PDF (ZIP)"):
                        st.session_state.download_all = True
                
                with col2:
                    st.download_button(
                        label="下載查詢結果清單 (Excel)",
                        data=open(st.session_state.excel_file, "rb"),
                        file_name="裁判書查詢結果.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        
        if st.session_state.get("batch_download", False) and st.session_state.get("batch_judgments"):
            judgments_batch = st.session_state.batch_judgments
            total = len(judgments_batch)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            status_text.text(f"準備下載 {total} 筆判決文件...")
            
            temp_dir = tempfile.mkdtemp()
            
            with st.spinner(f"正在下載 {total} 筆判決..."):
                downloaded_files, errors = await batch_download_pdfs(context, judgments_batch, temp_dir, progress_bar, status_text)
            
            if downloaded_files:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                zip_filename = f"裁判書合集_{timestamp}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for file in downloaded_files:
                        zipf.write(file, os.path.basename(file))
                
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
            
            for file in downloaded_files:
                if os.path.exists(file):
                    os.remove(file)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            os.rmdir(temp_dir)
            
            st.session_state.batch_download = False
            st.session_state.batch_judgments = None
        
        if st.session_state.get("download_all", False) and st.session_state.get("judgments"):
            judgments = st.session_state.judgments
            total = len(judgments)
            
            download_progress = st.progress(0)
            download_status = st.empty()
            download_status.text(f"準備下載 {total} 筆判決文件...")
            
            temp_dir = tempfile.mkdtemp()
            downloaded_files = []
            download_errors = []
            
            with st.spinner(f"正在下載全部 {total} 筆判決..."):
                downloaded_files, download_errors = await batch_download_pdfs(context, judgments, temp_dir, download_progress, download_status)
            
            if downloaded_files:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                zip_filename = f"裁判書合集_全部_{timestamp}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for file in downloaded_files:
                        zipf.write(file, os.path.basename(file))
                
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
            
            for file in downloaded_files:
                if os.path.exists(file):
                    os.remove(file)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            os.rmdir(temp_dir)
            
            st.session_state.download_all = False

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()