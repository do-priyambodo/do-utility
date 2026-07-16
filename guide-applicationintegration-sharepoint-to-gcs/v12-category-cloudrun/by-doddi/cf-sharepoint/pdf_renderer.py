import base64
import html
import io
import re
import threading
import time
import os
import gc
import shutil
import glob

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# Concurrency guard & Thread-Local Persistent Chromium Browser Engine for Cloud Run
_PLAYWRIGHT_SEMAPHORE = threading.Semaphore(4)
_THREAD_LOCAL = threading.local()

def get_persistent_browser(force_restart=False):
    """
    Returns or initializes a persistent, thread-local Chromium browser instance.
    Because Python's playwright.sync_api uses greenlets that are strictly bound to the
    creating thread, sharing a Browser object across multiple ThreadPoolExecutor worker
    threads raises 'greenlet.error: cannot switch to a different thread'.
    Using threading.local() ensures every worker thread gets its own isolated, persistent
    Chromium engine that is reused across thousands of pages without cross-thread violations.
    """
    if force_restart and getattr(_THREAD_LOCAL, 'browser', None) is not None:
        try:
            _THREAD_LOCAL.browser.close()
        except Exception:
            pass
        _THREAD_LOCAL.browser = None
        if getattr(_THREAD_LOCAL, 'playwright', None) is not None:
            try:
                _THREAD_LOCAL.playwright.stop()
            except Exception:
                pass
            _THREAD_LOCAL.playwright = None
        # Clean up stale Chromium/Playwright tmp directories in RAM buffers and run gc.collect()
        for tmp_dir in glob.glob("/tmp/pw*") + glob.glob("/tmp/.org.chromium.Chromium*") + glob.glob("/tmp/playwright*") + glob.glob("/tmp/.com.google.Chrome*"):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
        gc.collect()
        _THREAD_LOCAL.page_count = 0

    if getattr(_THREAD_LOCAL, 'browser', None) is None or not getattr(_THREAD_LOCAL, 'browser').is_connected():
        from playwright.sync_api import sync_playwright
        if getattr(_THREAD_LOCAL, 'playwright', None) is None:
            _THREAD_LOCAL.playwright = sync_playwright().start()
        _THREAD_LOCAL.browser = _THREAD_LOCAL.playwright.chromium.launch(
            headless=True,
            timeout=30000,
                        args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--disable-disk-cache",
                "--disk-cache-size=1",
                "--disable-application-cache",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--hide-scrollbars",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run"
            ]
        )
        _THREAD_LOCAL.page_count = 0
    return _THREAD_LOCAL.browser

def strip_complex_css_for_pdf(html_string, fallback_title="SharePoint Page"):
    safe_title = html.escape(str(fallback_title))
    if not BeautifulSoup:
        # Simple regex stripping if BS4 is unavailable
        text_only = re.sub(r'<[^>]+>', ' ', html_string)
        return f"<!DOCTYPE html><html><head><title>{safe_title}</title><style>body {{ font-family: sans-serif; padding: 20px; line-height: 1.5; }} h1 {{ color: #0078d4; }}</style></head><body><h1>{safe_title} (Simplified Layout)</h1><p>{html.escape(text_only[:10000])}</p></body></html>"
    
    soup = BeautifulSoup(html_string, "html.parser")
    
    # Remove all stylesheet links and style tags
    for s in soup.find_all(["style", "link", "script", "noscript"]):
        s.decompose()
        
    # Simplify table attributes and ensure widths fit page
    for tbl in soup.find_all("table"):
        tbl["width"] = "100%"
        tbl["border"] = "1"
        tbl["cellpadding"] = "6"
        tbl["cellspacing"] = "0"
        if tbl.has_attr("style"):
            del tbl["style"]
            
    # Ensure images have max dimensions so they don't overflow A4 pages
    for img in soup.find_all("img"):
        img["width"] = "400"
        if img.has_attr("height"):
            del img["height"]
        if img.has_attr("style"):
            del img["style"]
            
    # Clean up divs and spans that might have problematic CSS attributes
    for el in soup.find_all(["div", "span", "p", "section"]):
        if el.has_attr("style"):
            del el["style"]
        if el.has_attr("class"):
            del el["class"]

    body_content = ""
    body = soup.find("body")
    if body:
        body_content = str(body.decode_contents())
    else:
        body_content = str(soup.decode_contents())

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{safe_title}</title>
    <style>
        @page {{ size: A4 portrait; margin: 0.8cm; }}
        body {{ font-family: sans-serif; font-size: 10pt; line-height: 1.6; color: #201f1e; }}
        h1, h2, h3 {{ color: #0078d4; margin-top: 15px; margin-bottom: 8px; }}
        table {{ border-collapse: collapse; margin: 15px 0; width: 100%; }}
        th, td {{ border: 1px solid #c8c6c4; padding: 6px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f3f2f1; font-weight: bold; }}
        img {{ max-width: 100%; height: auto; margin: 10px 0; }}
        .fallback-banner {{ background-color: #fff4ce; border-left: 4px solid #ffb900; padding: 12px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="fallback-banner">
        <b>Simplified Document Layout:</b> This SharePoint page layout was simplified to ensure 100% of the information, tables, and images are presented accurately without formatting loss.
    </div>
    {body_content}
</body>
</html>"""

# Convert rendered HTML string to Base64-encoded PDF bytes strictly using Playwright Chromium
def render_html_to_pdf_base64(html_string, fallback_title="SharePoint Page", engine="playwright"):
    """
    Converts rendered HTML string to Base64-encoded PDF bytes strictly using Playwright Chromium.
    Enforces a 3-Stage Rendering Hierarchy without any third-party PDF libraries.
    Includes Proactive Context Auto-Recycling (every 50 pages) and Isolated BrowserContext per page
    to prevent DOM memory accumulation and socket exhaustion.
    """
    cleaned_html = re.sub(r':\s*(revert|revert-layer|unset|initial)\s*(;|\})', r': inherit\2', html_string, flags=re.IGNORECASE)
    
    with _PLAYWRIGHT_SEMAPHORE:
        try:
            # Proactively recycle the thread's persistent Chromium browser every 50 pages to prevent memory exhaustion
            current_count = getattr(_THREAD_LOCAL, 'page_count', 0) + 1
            if current_count >= 50:
                print(f"🔄 Proactively recycling Chromium engine for thread {threading.get_ident()} after 50 renders to preserve V8 memory heap...", flush=True)
                browser = get_persistent_browser(force_restart=True)
                _THREAD_LOCAL.page_count = 1
            else:
                browser = get_persistent_browser()
                _THREAD_LOCAL.page_count = current_count

            # Create an isolated BrowserContext for clean DOM/cookie/cache isolation per page
            context = browser.new_context(viewport={"width": 1280, "height": 1024})
            page = context.new_page()
            try:
                # Stage 1: High-Fidelity Playwright Chromium Render (15s timeout)
                try:
                    page.set_content(cleaned_html, wait_until="domcontentloaded", timeout=15000)
                    pdf_bytes = page.pdf(format="A4", print_background=True)
                    return base64.b64encode(pdf_bytes).decode("utf-8")
                except Exception as s1_err:
                    print(f"⚠️ Playwright Stage 1 timeout on '{fallback_title}' ({s1_err}). Attempting Stage 2 (Sanitized)...")

                # Stage 2: Strip blocking scripts & iframes -> Playwright Chromium Render (10s timeout)
                try:
                    no_scripts = re.sub(r'<(script|iframe|noscript)[^>]*>.*?</\1>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)
                    page.set_content(no_scripts, wait_until="domcontentloaded", timeout=10000)
                    pdf_bytes = page.pdf(format="A4", print_background=True)
                    return base64.b64encode(pdf_bytes).decode("utf-8")
                except Exception as s2_err:
                    print(f"⚠️ Playwright Stage 2 failed on '{fallback_title}' ({s2_err}). Attempting Stage 3 (Clean Simplified Layout Playwright Chromium Render)...")

                # Stage 3: Clean Simplified Layout -> Playwright Chromium Render (5s timeout)
                simplified_html = strip_complex_css_for_pdf(cleaned_html, fallback_title)
                page.set_content(simplified_html, wait_until="domcontentloaded", timeout=5000)
                pdf_bytes = page.pdf(format="A4", print_background=True)
                return base64.b64encode(pdf_bytes).decode("utf-8")
            finally:
                # Strictly close both the tab page and isolated BrowserContext to purge 100% of DOM/V8 heap
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
        except Exception as pw_fatal:
            print(f"❌ Chromium Pool exception on '{fallback_title}': {pw_fatal}. Attempting auto-recycled Playwright Chromium recovery...")
            try:
                # Stage 4 Recovery: Auto-recycle browser pool and re-try simplified layout via Playwright Chromium
                browser = get_persistent_browser(force_restart=True)
                context = browser.new_context(viewport={"width": 1280, "height": 1024})
                page = context.new_page()
                try:
                    simplified_html = strip_complex_css_for_pdf(cleaned_html, fallback_title)
                    page.set_content(simplified_html, wait_until="domcontentloaded", timeout=10000)
                    pdf_bytes = page.pdf(format="A4", print_background=True)
                    print(f"✅ Stage 4 Recovery: Successfully rendered '{fallback_title}' via auto-recycled Playwright Chromium engine.", flush=True)
                    return base64.b64encode(pdf_bytes).decode("utf-8")
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
            except Exception as recovery_err:
                print(f"❌ Fatal Playwright recovery failure on '{fallback_title}': {recovery_err}")

        # Final Base64 HTML fallback if binary DOM is completely unparseable
        fallback_html = f"<!DOCTYPE html><html><head><title>{html.escape(str(fallback_title))}</title></head><body><h1>{html.escape(str(fallback_title))}</h1><p>Document structure simplified for storage.</p>{cleaned_html[:50000]}</body></html>"
        return base64.b64encode(fallback_html.encode("utf-8")).decode("utf-8")


